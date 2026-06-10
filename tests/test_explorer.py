import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import explorer  # noqa: E402

# Sample from the live /summary endpoint, captured 2026-05-25.
SAMPLE_OK = {
    "status": "succeeded",
    "data": {
        "device_id": "b4c3d88a-c5a0-418e-9e63-43b5d60435c7",
        "status": "up",
        "status_duration": "0 days 10:57:27.208203",
        "is_working": False,
        "last_audit_successful": True,
        "last_challenge_successful": True,
        "total_jobs": 414,
    },
}


def test_parse_healthy_device():
    s = explorer._parse(SAMPLE_OK)
    assert s.online is True
    assert s.proof_failure is False
    assert s.status_text == "up"
    assert s.is_working is False


def test_parse_offline_status():
    p = dict(SAMPLE_OK)
    p["data"] = {**SAMPLE_OK["data"], "status": "down"}
    s = explorer._parse(p)
    assert s.online is False
    assert s.proof_failure is False
    assert s.status_text == "down"


def test_parse_challenge_failure():
    p = dict(SAMPLE_OK)
    p["data"] = {**SAMPLE_OK["data"], "last_challenge_successful": False}
    s = explorer._parse(p)
    assert s.online is True
    assert s.proof_failure is True


def test_parse_audit_failure():
    p = dict(SAMPLE_OK)
    p["data"] = {**SAMPLE_OK["data"], "last_audit_successful": False}
    s = explorer._parse(p)
    assert s.proof_failure is True


def test_parse_missing_proof_fields_is_not_a_failure():
    # If the API simply doesn't report the field, don't fabricate a failure.
    p = dict(SAMPLE_OK)
    p["data"] = {"device_id": "x", "status": "up", "is_working": False}
    s = explorer._parse(p)
    assert s.online is True
    assert s.proof_failure is False


def test_parse_api_error_surfaces_as_offline():
    s = explorer._parse({"status": "error", "message": "boom"})
    assert s.online is False
    assert s.status_text == "api_error"
