# io.net Worker Manager Daemon

This repo includes a macOS `launchd` job for unattended checks.

## Behavior

- Runs `.venv/bin/python run.py --once` every 5 hours.
- Runs once immediately when loaded.
- Appends every completed check to `reports.md`.
- Writes stdout/stderr to `logs/launchd.out.log` and `logs/launchd.err.log`.
- Uses `data/run.lock` so overlapping runs do not perform duplicate remote
  actions.
- Sends a macOS notification when any device ends in MANUAL.
- Sends live auth-code notifications during OAuth device-code relaunches.

## Install

```bash
bash scripts/install_launchd.sh
```

## Status

```bash
launchctl print gui/$(id -u)/com.hxie.io-worker-manager
tail -n 80 logs/launchd.out.log
tail -n 80 logs/launchd.err.log
tail -n 80 reports.md
```

## Run Now

```bash
launchctl kickstart -k gui/$(id -u)/com.hxie.io-worker-manager
```

## Uninstall

```bash
bash scripts/uninstall_launchd.sh
```

Uninstalling the LaunchAgent does not remove `reports.md`, `data/`, or
launch logs.
