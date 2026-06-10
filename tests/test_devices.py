import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

import devices  # noqa: E402


def test_load_parses_user_and_devices(tmp_path):
    f = tmp_path / "ID.md"
    f.write_text(
        "user_id=abc\n"
        "\n"
        "device_id list\n"
        "000:dev-000\n"
        "yahaha:dev-y\n"
    )
    user_id, devs = devices.load(f)
    assert user_id == "abc"
    assert [(d.name, d.device_id) for d in devs] == [
        ("000", "dev-000"),
        ("yahaha", "dev-y"),
    ]


def test_load_rejects_missing_user(tmp_path):
    f = tmp_path / "ID.md"
    f.write_text("000:dev-000\n")
    with pytest.raises(ValueError):
        devices.load(f)


def test_load_rejects_no_devices(tmp_path):
    f = tmp_path / "ID.md"
    f.write_text("user_id=abc\n")
    with pytest.raises(ValueError):
        devices.load(f)


def test_load_against_real_id_md():
    real = Path(__file__).resolve().parents[1] / "ID.md"
    user_id, devs = devices.load(real)
    assert user_id
    assert len(devs) == 9
    assert {d.name for d in devs} == {
        "000", "001", "002", "003", "006", "008", "010", "011", "yahaha",
    }
