# io.net Worker Manager

Small macOS monitor for keeping io.net workers online. It checks device status,
restarts Docker, relaunches workers when safe, and records short run reports.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Create a local `ID.md` file:

```text
user_id=<io.net user id>
device_id list
device_name: <device id>
```

`ID.md` is intentionally ignored because it contains private device data.

## Run

```bash
# one check for all devices
.venv/bin/python run.py --once

# one check for one device
.venv/bin/python run.py --device yahaha

# loop every 5 hours
.venv/bin/python run.py
```

## Background Service

```bash
bash scripts/install_launchd.sh
bash scripts/uninstall_launchd.sh
```

Status and logs:

```bash
launchctl print gui/$(id -u)/com.hxie.io-worker-manager
tail -n 80 logs/launchd.out.log
tail -n 80 logs/launchd.err.log
```

## Test

```bash
.venv/bin/python -m pytest tests/ -q
```
