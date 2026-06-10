"""SSH probes against a device by its ~/.ssh/config alias."""

import subprocess

CONNECT_TIMEOUT_S = 15


def reachable(device_name: str) -> tuple[bool, str]:
    cmd = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", f"ConnectTimeout={CONNECT_TIMEOUT_S}",
        "-o", "StrictHostKeyChecking=accept-new",
        device_name,
        "echo ok",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=CONNECT_TIMEOUT_S + 5)
    except subprocess.TimeoutExpired:
        return False, "ssh timeout"
    if r.returncode == 0 and "ok" in r.stdout:
        return True, ""
    return False, (r.stderr or r.stdout).strip()


def battery_percent(device_name: str) -> int | None:
    """Battery % on a remote Mac, or None if it cannot be read."""
    try:
        r = subprocess.run(
            ["ssh", device_name, "pmset -g batt | grep -Eo '[0-9]+%' | head -1"],
            capture_output=True, text=True, timeout=20,
        )
    except subprocess.TimeoutExpired:
        return None
    if r.returncode != 0:
        return None
    txt = r.stdout.strip().rstrip("%")
    return int(txt) if txt.isdigit() else None
