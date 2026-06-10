import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import devices  # noqa: E402
import explorer  # noqa: E402
import manager  # noqa: E402
import report  # noqa: E402


def _status(*, online=True, proof_failure=False):
    return explorer.Status(
        online=online,
        proof_failure=proof_failure,
        is_working=False,
        status_text="up" if online else "down",
        raw={},
    )


def test_continuous_proof_failure_requires_consecutive_checks(monkeypatch):
    dev = devices.Device("a", "dev-a")
    state = {"devices": {}}
    launches = []

    monkeypatch.setattr(manager.explorer, "fetch", lambda *args, **kwargs: _status(proof_failure=True))
    monkeypatch.setattr(manager.ssh_check, "battery_percent", lambda name: 80)
    monkeypatch.setattr(manager.worker, "kill_and_reopen_docker", lambda name: (True, "ready"))
    monkeypatch.setattr(
        manager.worker,
        "restart_worker",
        lambda name, device_id, user_id: launches.append(name) or (True, "launched"),
    )
    monkeypatch.setattr(manager.time, "sleep", lambda seconds: None)

    first = manager.check_device(dev, "user", state=state)
    second = manager.check_device(dev, "user", state=state)

    assert first.status == report.SKIPPED
    assert second.status == report.FIXED
    assert launches == ["a"]
    assert state["devices"]["a"]["proof_failure_history"] == []
    assert state["devices"]["a"]["low_battery_hold"] is False


def test_low_battery_hold_waits_until_above_recovery_threshold(monkeypatch):
    dev = devices.Device("a", "dev-a")
    state = {"devices": {}}
    battery = iter([10, 35, 51])
    launches = []

    monkeypatch.setattr(manager.explorer, "fetch", lambda *args, **kwargs: _status(online=False))
    monkeypatch.setattr(manager.ssh_check, "reachable", lambda name: (True, ""))
    monkeypatch.setattr(manager.ssh_check, "battery_percent", lambda name: next(battery))
    monkeypatch.setattr(manager.worker, "kill_and_reopen_docker", lambda name: (True, "ready"))
    monkeypatch.setattr(
        manager.worker,
        "restart_worker",
        lambda name, device_id, user_id: launches.append(name) or (True, "launched"),
    )
    monkeypatch.setattr(manager.time, "sleep", lambda seconds: None)

    first = manager.check_device(dev, "user", state=state)
    second = manager.check_device(dev, "user", state=state)
    third = manager.check_device(dev, "user", state=state)

    assert first.status == report.SKIPPED
    assert "waiting until >50%" in first.detail
    assert second.status == report.SKIPPED
    assert "still waiting until >50%" in second.detail
    assert third.status == report.FIXED
    assert launches == ["a"]


def test_offline_status_does_not_count_as_proof_failure(monkeypatch):
    dev = devices.Device("a", "dev-a")
    state = {"devices": {}}

    monkeypatch.setattr(
        manager.explorer,
        "fetch",
        lambda *args, **kwargs: _status(online=False, proof_failure=True),
    )
    monkeypatch.setattr(manager.ssh_check, "reachable", lambda name: (False, "down"))

    result = manager.check_device(dev, "user", state=state)

    assert result.status == report.MANUAL
    assert state["devices"]["a"]["proof_failure_history"] == [False]


def test_run_lock_reports_busy_when_already_held(tmp_path):
    lock_path = tmp_path / "run.lock"
    with manager._run_lock(lock_path) as first:
        assert first is True
        with manager._run_lock(lock_path) as second:
            assert second is False


def test_notify_if_action_needed_only_for_manual(monkeypatch):
    calls = []
    monkeypatch.setattr(manager.subprocess, "run", lambda *args, **kwargs: calls.append(args))

    manager._notify_if_action_needed([
        report.DeviceReport("a", report.OK, "fine"),
        report.DeviceReport("b", report.FIXED, "relaunched"),
    ])
    assert calls == []

    manager._notify_if_action_needed([
        report.DeviceReport("a", report.MANUAL, "ssh down"),
        report.DeviceReport("b", report.OK, "fine"),
    ])
    assert len(calls) == 1
