"""Load user_id and device list from ID.md."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Device:
    name: str
    device_id: str


def load(id_file: Path) -> tuple[str, list[Device]]:
    user_id = ""
    devices: list[Device] = []
    for raw in id_file.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line == "device_id list":
            continue
        if line.startswith("user_id="):
            user_id = line.split("=", 1)[1].strip()
            continue
        if ":" in line:
            name, did = line.split(":", 1)
            devices.append(Device(name=name.strip(), device_id=did.strip()))
    if not user_id:
        raise ValueError("user_id missing from ID file")
    if not devices:
        raise ValueError("no devices listed in ID file")
    return user_id, devices
