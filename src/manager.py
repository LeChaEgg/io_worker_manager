"""Top-level monitoring + remediation loop."""

from __future__ import annotations

import fcntl
import json
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import devices as devices_mod
import explorer
import report
import ssh_check
import worker

CHECK_INTERVAL_S = 5 * 3600
LOW_BATTERY_PCT = 20
# A device is considered in continuous failure once it has shown the bad
# state across this many consecutive checks.
CONTINUOUS_THRESHOLD = 2
HISTORY_LEN = 4
LOW_BATTERY_RECOVER_PCT = 50

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
STATE_PATH = DATA_DIR / "state.json"
LOCK_PATH = DATA_DIR / "run.lock"


def _load_state(path: Path = STATE_PATH) -> dict[str, Any]:
    if not path.exists():
        return {"devices": {}}
    try:
        state = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {"devices": {}}
    if not isinstance(state, dict):
        return {"devices": {}}
    state.setdefault("devices", {})
    return state


def _save_state(state: dict[str, Any], path: Path = STATE_PATH) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


@contextmanager
def _run_lock(path: Path = LOCK_PATH) -> Any:
    DATA_DIR.mkdir(exist_ok=True)
    with path.open("w") as lock_file:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def _device_state(state: dict[str, Any], name: str) -> dict[str, Any]:
    devices = state.setdefault("devices", {})
    return devices.setdefault(name, {})


def _record_proof_result(state: dict[str, Any], name: str, failed: bool) -> int:
    dev_state = _device_state(state, name)
    history = list(dev_state.get("proof_failure_history") or [])
    history.append(bool(failed))
    history = history[-HISTORY_LEN:]
    dev_state["proof_failure_history"] = history

    streak = 0
    for item in reversed(history):
        if not item:
            break
        streak += 1
    return streak


def _battery_hold_report(
    state: dict[str, Any],
    name: str,
    battery_pct: int | None,
) -> report.DeviceReport | None:
    dev_state = _device_state(state, name)
    holding = bool(dev_state.get("low_battery_hold"))

    if battery_pct is not None and battery_pct <= LOW_BATTERY_PCT:
        dev_state["low_battery_hold"] = True
        return report.DeviceReport(
            name,
            report.SKIPPED,
            f"battery {battery_pct}% — waiting until >{LOW_BATTERY_RECOVER_PCT}% before reconnecting",
        )

    if holding:
        if battery_pct is not None and battery_pct > LOW_BATTERY_RECOVER_PCT:
            dev_state["low_battery_hold"] = False
            return None
        detail = "battery unavailable" if battery_pct is None else f"battery {battery_pct}%"
        return report.DeviceReport(
            name,
            report.SKIPPED,
            f"{detail} — still waiting until >{LOW_BATTERY_RECOVER_PCT}% before reconnecting",
        )

    return None


def check_device(
    dev: devices_mod.Device,
    user_id: str,
    *,
    state: dict[str, Any] | None = None,
) -> report.DeviceReport:
    state = state if state is not None else {"devices": {}}
    try:
        status = explorer.fetch(dev.device_id, name=dev.name)
    except Exception as e:
        return report.DeviceReport(dev.name, report.MANUAL,
                                    f"explorer fetch failed: {e}")

    proof_streak = _record_proof_result(
        state,
        dev.name,
        status.online and status.proof_failure,
    )

    if status.online and not status.proof_failure:
        return report.DeviceReport(dev.name, report.OK, "online; no proof failure")

    if not status.online:
        ok, err = ssh_check.reachable(dev.name)
        if not ok:
            return report.DeviceReport(
                dev.name, report.MANUAL,
                f"offline + ssh unreachable ({err}) — check power/network/reboot",
            )
        battery_report = _battery_hold_report(state, dev.name,
                                              ssh_check.battery_percent(dev.name))
        if battery_report is not None:
            return battery_report
        return _remediate(dev, user_id, reason="offline (ssh ok)", state=state)

    # proof failure path
    if proof_streak < CONTINUOUS_THRESHOLD:
        return report.DeviceReport(
            dev.name, report.SKIPPED,
            "one-time proof failure — waiting for next round",
        )

    batt = ssh_check.battery_percent(dev.name)
    battery_report = _battery_hold_report(state, dev.name, batt)
    if battery_report is not None:
        return battery_report

    return _remediate(dev, user_id, reason="continuous proof failure", state=state)


def _remediate(
    dev: devices_mod.Device,
    user_id: str,
    *,
    reason: str,
    state: dict[str, Any] | None = None,
) -> report.DeviceReport:
    try:
        kill_ok, kill_msg = worker.kill_and_reopen_docker(dev.name)
        if not kill_ok:
            return report.DeviceReport(
                dev.name, report.MANUAL,
                f"{reason}; docker restart failed: {kill_msg[:120]}",
            )
        # small grace period before launching the worker against fresh docker
        time.sleep(8)
        launch_ok, launch_msg = worker.restart_worker(dev.name, dev.device_id, user_id)
    except Exception as e:
        return report.DeviceReport(
            dev.name, report.MANUAL,
            f"{reason}; remediation crashed: {e}",
        )
    if launch_ok:
        if state is not None:
            dev_state = _device_state(state, dev.name)
            dev_state["proof_failure_history"] = []
            dev_state["low_battery_hold"] = False
        return report.DeviceReport(dev.name, report.FIXED,
                                    f"{reason}; worker relaunched")
    return report.DeviceReport(
        dev.name, report.MANUAL,
        f"{reason}; worker relaunch failed: {launch_msg[:160]}",
    )


REPORT_MD = Path(__file__).resolve().parents[1] / "reports.md"


def run_once(id_file: Path, *, report_path: Path = REPORT_MD,
             only: str | None = None) -> str:
    with _run_lock() as acquired:
        if not acquired:
            return "io.net worker check skipped: another run is already active"

        user_id, device_list = devices_mod.load(id_file)
        state = _load_state()
        if only is not None:
            device_list = [d for d in device_list if d.name == only]
            if not device_list:
                raise ValueError(f"device {only!r} not in {id_file}")
        results = [check_device(d, user_id, state=state) for d in device_list]
        _save_state(state)
        text = report.render(results)
        report.append_markdown(report_path, report.render_markdown(results))
        _notify_if_action_needed(results)
        return text


def _notify_if_action_needed(results: list[report.DeviceReport]) -> None:
    manual = [r for r in results if r.status == report.MANUAL]
    if not manual:
        return
    names = ", ".join(r.name for r in manual[:5])
    if len(manual) > 5:
        names += f", +{len(manual) - 5} more"
    try:
        subprocess.run(
            [
                "osascript",
                "-e",
                (
                    f'display notification "{names}" '
                    f'with title "io.net action needed" '
                    f'subtitle "{len(manual)} manual device(s)" '
                    f'sound name "Glass"'
                ),
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return


def run_forever(
    id_file: Path,
    *,
    report_path: Path = REPORT_MD,
    interval_s: int = CHECK_INTERVAL_S,
) -> None:
    while True:
        print(run_once(id_file, report_path=report_path), flush=True)
        time.sleep(interval_s)
