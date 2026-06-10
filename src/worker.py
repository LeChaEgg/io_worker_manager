"""Docker + worker control on a remote device."""

from __future__ import annotations

import json
import os
import pty
import re
import selectors
import shlex
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Binary lives in the user's home directory on each remote device.
LAUNCH_BINARY = "$HOME/io_net_launch_binary_mac"
# Docker CLI is not on the non-interactive SSH PATH (which is /usr/bin:/bin:
# /usr/sbin:/sbin only). Use an absolute path everywhere we shell out.
REMOTE_DOCKER = "/usr/local/bin/docker"
REMOTE_PATH = "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

KILL_TIMEOUT_S = 30
OPEN_DOCKER_TIMEOUT_S = 25
DOCKER_READY_TIMEOUT_S = 90
DOCKER_READY_POLL_S = 3
POST_LAUNCH_STABILITY_S = 45
# The launcher pulls Docker images and waits ~30 s for sidecar health, so a
# real launch routinely takes 3–5 min. 15 min gives generous headroom on
# slow links without letting a truly hung run linger forever.
LAUNCH_TIMEOUT_S = 900
SUCCESS_MARKER = "IO Worker is launched and ready"
REQUIRED_WORKER_IMAGES = ("ionetcontainers/io-worker-vc", "ionetcontainers/io-worker-monitor")
CACHE_READ_TIMEOUT_S = 15
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
DEVICE_CODE_RE = re.compile(r"^[A-Z0-9]{4}-[A-Z0-9]{4}$")
DEVICE_CODE_URL_RE = re.compile(r"user_code=([A-Z0-9]{4}-[A-Z0-9]{4})")

# Keep the long SSH connection alive while the launcher is pulling images.
SSH_KEEPALIVE = ["-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=4"]

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
_notified_auth_codes: set[tuple[str, str]] = set()

_STOP_DOCKER = (
    "osascript -e 'quit app \"Docker\"' >/dev/null 2>&1 || true; "
    "sleep 3; "
    "pkill -f '/Applications/Docker.app' >/dev/null 2>&1 || true; "
    "pkill -f 'Docker Desktop' >/dev/null 2>&1 || true; "
    "pkill -x 'com.docker.backend' >/dev/null 2>&1 || true"
)
_SUDO_STOP_DOCKER = "sudo -n pkill -f docker >/dev/null 2>&1 || true; sleep 3"


def kill_and_reopen_docker(device_name: str) -> tuple[bool, str]:
    """Stop Docker, start it again, and wait until the daemon is responding.

    Returns (ok, message). `ok` is True only once `docker info` succeeds —
    a launch attempted against a half-booted Docker silently no-ops.
    """
    subprocess.run(
        ["ssh", device_name, _STOP_DOCKER],
        capture_output=True, text=True, timeout=KILL_TIMEOUT_S,
    )
    reopen = subprocess.run(
        ["ssh", device_name, "open -a Docker"],
        capture_output=True, text=True, timeout=OPEN_DOCKER_TIMEOUT_S,
    )
    if reopen.returncode != 0:
        first_err = reopen.stderr.strip()[:200]
        subprocess.run(
            ["ssh", device_name, _SUDO_STOP_DOCKER],
            capture_output=True, text=True, timeout=KILL_TIMEOUT_S,
        )
        reopen = subprocess.run(
            ["ssh", device_name, "open -a Docker"],
            capture_output=True, text=True, timeout=OPEN_DOCKER_TIMEOUT_S,
        )
        if reopen.returncode != 0:
            return False, (
                "open -a Docker failed after sudo cleanup: "
                f"{reopen.stderr.strip()[:200] or first_err}"
            )

    ready, detail = _wait_for_docker_ready(device_name)
    return ready, detail


def _wait_for_docker_ready(device_name: str) -> tuple[bool, str]:
    deadline = time.monotonic() + DOCKER_READY_TIMEOUT_S
    last_err = ""
    while time.monotonic() < deadline:
        try:
            r = subprocess.run(
                ["ssh", device_name,
                 f"{REMOTE_DOCKER} info --format '{{{{.ServerVersion}}}}' 2>&1"],
                capture_output=True, text=True, timeout=15,
            )
        except subprocess.TimeoutExpired:
            last_err = "docker info ssh timeout"
            time.sleep(DOCKER_READY_POLL_S)
            continue
        out = (r.stdout + r.stderr).strip()
        # Daemon-ready response is a single version string like "28.4.0".
        if r.returncode == 0 and out and "Cannot connect" not in out:
            return True, f"docker ready (server {out})"
        last_err = out[:160]
        time.sleep(DOCKER_READY_POLL_S)
    return False, f"docker not ready after {DOCKER_READY_TIMEOUT_S}s: {last_err}"


def fetch_cached_device_name(device_name_ssh: str) -> str | None:
    """Read $HOME/ionet_device_cache.json on the device and return its
    device_name. The launcher uses this as the registered name with io.net;
    passing a different value on the CLI re-registers the device, which is
    not what we want."""
    try:
        r = subprocess.run(
            ["ssh", device_name_ssh, "cat $HOME/ionet_device_cache.json"],
            capture_output=True, text=True, timeout=CACHE_READ_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return None
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout).get("device_name")
    except json.JSONDecodeError:
        return None


def restart_worker(device_name: str, device_id: str, user_id: str) -> tuple[bool, str]:
    """Run the launch binary on the remote device.

    Success is determined ONLY by the launcher's "IO Worker is launched and
    ready" banner. Exit code is not trusted (we have seen it return 0 even
    when nothing was actually launched, because Docker hadn't finished
    booting yet). The full launcher output is persisted to
    data/launch_<name>_<timestamp>.log for post-mortem debugging.
    """
    cached_name = fetch_cached_device_name(device_name)
    effective_name = cached_name or device_name

    launch = (
        f"{LAUNCH_BINARY}"
        f" --device_id={shlex.quote(device_id)}"
        f" --user_id={shlex.quote(user_id)}"
        f" --operating_system=macOS"
        f" --usegpus=false"
        f" --device_name={shlex.quote(effective_name)}"
    )
    remote = f"export PATH={shlex.quote(REMOTE_PATH)}; yes Yes | {launch}"
    combined, timed_out = _run_launcher_streaming_auth_hints(
        ["ssh", "-tt", *SSH_KEEPALIVE, device_name, remote],
        device_name,
    )

    log_path = _persist_launch_log(device_name, combined, cached_name,
                                    effective_name, timed_out)

    if timed_out:
        return False, f"launch timeout (>{LAUNCH_TIMEOUT_S}s); see {log_path.name}"
    if SUCCESS_MARKER not in combined:
        tail = " ".join(ANSI_RE.sub("", combined).split())[-200:]
        return False, f"no success marker; see {log_path.name}; tail: {tail}"
    stable, stable_msg = _verify_worker_containers(device_name)
    if not stable:
        return False, f"launcher banner found but worker containers not stable; {stable_msg}; see {log_path.name}"
    return True, f"launched ({log_path.name})"


def _verify_worker_containers(device_name: str) -> tuple[bool, str]:
    time.sleep(POST_LAUNCH_STABILITY_S)
    cmd = (
        f"export PATH={shlex.quote(REMOTE_PATH)}; "
        "docker ps --format '{{.Image}}' 2>&1"
    )
    try:
        running = subprocess.run(
            ["ssh", device_name, cmd],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return False, "docker ps timeout after launcher success"
    if running.returncode != 0:
        return False, f"docker ps failed after launcher success: {running.stderr.strip()[:160]}"

    images = [line.strip() for line in running.stdout.splitlines() if line.strip()]
    missing = _missing_worker_images(images)
    if not missing:
        return True, "worker containers stable"

    all_cmd = (
        f"export PATH={shlex.quote(REMOTE_PATH)}; "
        "docker ps -a --format '{{.Image}} {{.Status}} {{.Names}}' | head -20"
    )
    detail = subprocess.run(
        ["ssh", device_name, all_cmd],
        capture_output=True,
        text=True,
        timeout=30,
    )
    snapshot = " ".join((detail.stdout or detail.stderr).split())[:240]
    return False, f"missing running containers: {', '.join(missing)}; docker snapshot: {snapshot}"


def _missing_worker_images(images: list[str]) -> list[str]:
    return [
        required
        for required in REQUIRED_WORKER_IMAGES
        if not any(image.startswith(required) for image in images)
    ]


def _run_launcher_streaming_auth_hints(cmd: list[str],
                                       device_name: str) -> tuple[str, bool]:
    """Run the launcher and surface device-auth hints before they expire."""
    master_fd, slave_fd = pty.openpty()
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=slave_fd,
        stderr=slave_fd,
        close_fds=True,
    )
    os.close(slave_fd)

    sel = selectors.DefaultSelector()
    sel.register(master_fd, selectors.EVENT_READ)
    chunks: list[str] = []
    pending_line = ""
    timed_out = False
    deadline = time.monotonic() + LAUNCH_TIMEOUT_S

    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                proc.kill()
                break

            for key, _ in sel.select(timeout=min(1, remaining)):
                try:
                    data = os.read(key.fd, 4096)
                except OSError:
                    break
                if not data:
                    break
                text = data.decode(errors="replace")
                chunks.append(text)
                pending_line = _surface_auth_hints(
                    device_name, pending_line + text
                )

            if proc.poll() is not None:
                if pending_line:
                    _surface_auth_hint(device_name, pending_line)
                break
    finally:
        sel.close()
        os.close(master_fd)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    return "".join(chunks), timed_out


def _surface_auth_hints(device_name: str, text: str) -> str:
    lines = text.splitlines(keepends=True)
    if not lines:
        return ""
    pending = ""
    if not lines[-1].endswith(("\n", "\r")):
        pending = lines.pop()
    for line in lines:
        _surface_auth_hint(device_name, line)
    return pending


def _surface_auth_hint(device_name: str, line: str) -> None:
    text = ANSI_RE.sub("", line).strip()
    if (
        "/device?user_code=" not in text
        and not text.startswith("at: https://")
        and not DEVICE_CODE_RE.fullmatch(text)
    ):
        return
    print(f"AUTH REQUIRED for {device_name}: {text}", flush=True, file=sys.stderr)
    code = _extract_device_code(text)
    if code:
        _notify_auth_required(device_name, code)


def _extract_device_code(text: str) -> str | None:
    if DEVICE_CODE_RE.fullmatch(text):
        return text
    match = DEVICE_CODE_URL_RE.search(text)
    return match.group(1) if match else None


def _notify_auth_required(device_name: str, code: str) -> None:
    key = (device_name, code)
    if key in _notified_auth_codes:
        return
    _notified_auth_codes.add(key)
    try:
        subprocess.run(
            [
                "osascript",
                "-e",
                (
                    f'display notification "Code {code}" '
                    f'with title "io.net auth needed" '
                    f'subtitle "{device_name}" sound name "Glass"'
                ),
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        # The terminal hint is authoritative; desktop notification is best effort.
        return


def _persist_launch_log(device_name: str, combined: str,
                         cached_name: str | None, effective_name: str,
                         timed_out: bool) -> Path:
    DATA_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    path = DATA_DIR / f"launch_{device_name}_{ts}.log"
    header = (
        f"# device_name(ssh)={device_name}\n"
        f"# device_name(cached)={cached_name}\n"
        f"# device_name(used)={effective_name}\n"
        f"# timed_out={timed_out}\n"
        f"# captured_at={datetime.now().isoformat(timespec='seconds')}\n"
        f"# success_marker_present={SUCCESS_MARKER in combined}\n"
        "---\n"
    )
    path.write_text(header + combined)
    return path
