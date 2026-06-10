import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import worker  # noqa: E402


def _completed(returncode=0, stdout="", stderr=""):
    return worker.subprocess.CompletedProcess(
        args=[],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def test_surface_auth_hint_only_prints_actionable_lines(capsys, monkeypatch):
    notified = []
    monkeypatch.setattr(
        worker,
        "_notify_auth_required",
        lambda device_name, code: notified.append((device_name, code)),
    )

    worker._surface_auth_hint("yahaha", "normal launcher noise")
    worker._surface_auth_hint(
        "yahaha",
        "\x1b[36mhttps://gifted-balloon-65.authkit.app/device?user_code=ABCD-EFGH",
    )
    worker._surface_auth_hint("yahaha", "ABCD-EFGH")

    captured = capsys.readouterr()
    assert "normal launcher noise" not in captured.err
    assert (
        "AUTH REQUIRED for yahaha: "
        "https://gifted-balloon-65.authkit.app/device?user_code=ABCD-EFGH"
    ) in captured.err
    assert "AUTH REQUIRED for yahaha: ABCD-EFGH" in captured.err
    assert notified == [("yahaha", "ABCD-EFGH"), ("yahaha", "ABCD-EFGH")]


def test_notify_auth_required_dedupes_codes(monkeypatch):
    calls = []
    monkeypatch.setattr(worker, "_notified_auth_codes", set())
    monkeypatch.setattr(worker.subprocess, "run", lambda *args, **kwargs: calls.append(args))

    worker._notify_auth_required("yahaha", "ABCD-EFGH")
    worker._notify_auth_required("yahaha", "ABCD-EFGH")

    assert len(calls) == 1


def test_kill_and_reopen_docker_retries_with_noninteractive_sudo(monkeypatch):
    calls = []
    responses = iter([
        _completed(),
        _completed(returncode=1, stderr="error=Error D"),
        _completed(),
        _completed(),
    ])

    def fake_run(args, **kwargs):
        calls.append(args)
        return next(responses)

    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    monkeypatch.setattr(worker, "_wait_for_docker_ready", lambda name: (True, "docker ready"))

    ok, detail = worker.kill_and_reopen_docker("002")

    assert ok is True
    assert detail == "docker ready"
    assert calls == [
        ["ssh", "002", worker._STOP_DOCKER],
        ["ssh", "002", "open -a Docker"],
        ["ssh", "002", worker._SUDO_STOP_DOCKER],
        ["ssh", "002", "open -a Docker"],
    ]


def test_kill_and_reopen_docker_reports_failed_sudo_retry(monkeypatch):
    calls = []
    responses = iter([
        _completed(),
        _completed(returncode=1, stderr="error=Error D"),
        _completed(),
        _completed(returncode=1, stderr="still wedged"),
    ])

    def fake_run(args, **kwargs):
        calls.append(args)
        return next(responses)

    monkeypatch.setattr(worker.subprocess, "run", fake_run)

    ok, detail = worker.kill_and_reopen_docker("002")

    assert ok is False
    assert detail == "open -a Docker failed after sudo cleanup: still wedged"
    assert calls[-2:] == [
        ["ssh", "002", worker._SUDO_STOP_DOCKER],
        ["ssh", "002", "open -a Docker"],
    ]


def test_missing_worker_images_detects_absent_required_containers():
    images = [
        "ionetcontainers/io-auth-sidecar:latest",
        "ionetcontainers/io-worker-vc@sha256:abc",
    ]

    assert worker._missing_worker_images(images) == [
        "ionetcontainers/io-worker-monitor"
    ]


def test_missing_worker_images_accepts_required_containers():
    images = [
        "ionetcontainers/io-auth-sidecar:latest",
        "ionetcontainers/io-worker-vc@sha256:abc",
        "ionetcontainers/io-worker-monitor",
    ]

    assert worker._missing_worker_images(images) == []
