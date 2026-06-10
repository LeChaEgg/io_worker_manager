"""Query io.net for a single device's current status.

API endpoints (no auth required, verified 2026-05-25):
    GET https://api.io.solutions/v1/io-explorer/devices/{device_id}/summary
    GET https://api.io.solutions/v1/io-explorer/devices/{device_id}/details

We only call /summary on each check — it carries the up/down state and the
last challenge/audit signals, which is everything the monitor needs. The
/details endpoint stays available via fetch_details() for richer context
when reporting a problem (downtime history, success rates, etc.).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

SUMMARY_URL = "https://api.io.solutions/v1/io-explorer/devices/{device_id}/summary"
DETAILS_URL = "https://api.io.solutions/v1/io-explorer/devices/{device_id}/details"
HEADERS = {"Accept": "application/json", "Frontend-Version": "1.106.0"}
DEFAULT_TIMEOUT_S = 10.0
DATA_DIR = Path(__file__).resolve().parents[1] / "data"


@dataclass(frozen=True)
class Status:
    online: bool
    proof_failure: bool
    is_working: bool
    status_text: str
    raw: dict[str, Any]


def fetch(device_id: str, *, name: str | None = None,
          timeout: float = DEFAULT_TIMEOUT_S) -> Status:
    resp = requests.get(
        SUMMARY_URL.format(device_id=device_id),
        timeout=timeout, headers=HEADERS,
    )
    resp.raise_for_status()
    payload = resp.json()
    if name:
        _persist_raw(name, payload)
    return _parse(payload)


def fetch_details(device_id: str, *, timeout: float = DEFAULT_TIMEOUT_S) -> dict[str, Any]:
    """Richer per-device info — call this on-demand when building a report
    for a problematic device, not during the regular polling loop."""
    resp = requests.get(
        DETAILS_URL.format(device_id=device_id),
        timeout=timeout, headers=HEADERS,
    )
    resp.raise_for_status()
    return resp.json().get("data") or {}


def _persist_raw(name: str, data: Any) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    (DATA_DIR / f"last_{name}.json").write_text(json.dumps(data, indent=2, default=str))


def _parse(payload: dict[str, Any]) -> Status:
    if payload.get("status") != "succeeded":
        # Whole API call did not succeed — surface as offline so it gets
        # investigated. raw retains the original payload for debugging.
        return Status(online=False, proof_failure=False, is_working=False,
                      status_text="api_error", raw=payload)

    data = payload.get("data") or {}
    status_text = str(data.get("status") or "").lower()
    online = status_text == "up"
    # last_challenge_successful covers zkTFLOPs/Proof of Timelock per the API.
    # A missing key (None) is not a failure — only an explicit False counts.
    proof_failure = (
        data.get("last_challenge_successful") is False
        or data.get("last_audit_successful") is False
    )
    is_working = bool(data.get("is_working"))
    return Status(
        online=online,
        proof_failure=proof_failure,
        is_working=is_working,
        status_text=status_text or "unknown",
        raw=data,
    )
