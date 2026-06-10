# AGENTS.md

## Project Context

A management tool that maximizes uptime of io.net workers running on macOS
hosts. It monitors device status via the io.net public API, reconnects
devices that fall offline, investigates zkTFLOPs / Proof of Timelock
failures, and prints a per-check report (also appended to `reports.md`).

User and device identifiers live in `ID.md`. Live status for any device can
be read at:

- Summary (used by the monitor): `GET https://api.io.solutions/v1/io-explorer/devices/{device_id}/summary`
- Details (richer info, on demand): `GET https://api.io.solutions/v1/io-explorer/devices/{device_id}/details`

The API requires no auth, but does require the header
`Frontend-Version: 1.106.0`. The browser page
`https://explorer.io.net/explorer/devices/{device_id}` is a SPA that calls
the same endpoints under the hood.

Each device is reachable over SSH via its alias (the name in `ID.md`).
SSH host aliases live in `~/.ssh/config` on the machine running this tool.

## Basic workflow

- Check the status of all devices every 5 hours when installed as the
  background daemon.
- If a device is offline AND reachable over SSH → restart Docker, relaunch
  the worker.
- If a device is offline AND not reachable over SSH → MANUAL (likely
  power/network/reboot).
- If a device has a one-time proof failure → wait for the next round.
- If a device has continuous proof failures (≥2 consecutive checks) AND
  battery > 20% → restart Docker, relaunch.
- If battery ≤ 20% → wait until > 50% before reconnecting.
- Continuous proof-failure and low-battery wait state are persisted in
  `data/state.json`, so restarting the manager does not forget them.
- Append a brief summary to `reports.md` every check. Only entries needing
  attention (MANUAL/FIXED/SKIPPED) are listed; healthy devices are counted
  only.

## Common reasons devices go offline / fail proofs

- Device restarted, lost Internet, or lost power → SSH probe confirms.
- Docker daemon dies or wedges → kill + reopen Docker, then relaunch.
- Continuous proof failure with low battery → macOS throttles → wait for
  battery > 50%.
- One-time proof failure → network jitter or scheduling noise → ignore one
  cycle.

## Known limitations (real-world)

These are not bugs — fixing them requires user action.

- **OAuth refresh tokens in `~/ionet_device_cache.json` expire periodically.**
  When that happens the launcher prints a device-code URL and waits for a
  human to authorize in a browser. After the timeout the device exits with
  `device code expired`. Until the user re-authenticates manually on the
  device, automated relaunch cannot recover it. During a launch attempt,
  the tool prints `AUTH REQUIRED for <name>: ...` lines immediately and
  sends a best-effort macOS notification with the code. If the code still
  expires, the tool surfaces this as MANUAL and writes the launcher's full
  stdout to `data/launch_<name>_<ts>.log`.
- **The io.net API lags behind the launcher.** A successful relaunch is
  authoritative when the launcher prints `IO Worker is launched and ready`.
  The `/summary` endpoint may continue to report `status: "down"` for
  10+ min after that. Do NOT verify a launch by re-polling the API
  immediately. Verify locally by requiring the launcher banner and then
  checking that both `io-worker-vc` and `io-worker-monitor` remain running
  after a short stability window.

## How Agents Should Work

- First inspect the relevant files and existing patterns.
- Make the smallest change that solves the task.
- Prefer clarity over cleverness.
- Preserve existing style unless there is a clear reason not to.
- Do not rewrite unrelated code.
- Do not change public APIs, schemas, configs, or workflows unless asked.
- When uncertain, state the assumption and proceed with the safest option.
- Keep final answers concise: explain what changed, what was tested, and
  any remaining risk.
- Real actions on devices (SSH, docker kill, launcher) are irreversible
  per cycle and visible to io.net. Always confirm before running anything
  beyond `--device NAME` test scope.

## Commands

Run from the repo root, with the venv active.

```bash
# one-time setup
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# one-shot check, all devices
.venv/bin/python run.py --once

# one-shot check, a single device (safe test path)
.venv/bin/python run.py --device yahaha

# loop forever (5h cadence)
.venv/bin/python run.py

# install/uninstall the 5h macOS background job
bash scripts/install_launchd.sh
bash scripts/uninstall_launchd.sh

# tests
.venv/bin/python -m pytest tests/ -q
```

### Remote commands (what the tool runs over SSH)

```bash
# access a device
ssh <device_name>          # alias from ~/.ssh/config

# stop Docker without sudo (macOS, Docker Desktop runs as the user)
osascript -e 'quit app "Docker"' || true
sleep 3
pkill -f '/Applications/Docker.app' || true
pkill -f 'Docker Desktop' || true
pkill -x 'com.docker.backend' || true

# start Docker, then wait until daemon is ready (NOT a fixed sleep)
open -a Docker
# poll until success, up to ~90s:
/usr/local/bin/docker info --format '{{.ServerVersion}}'

# relaunch the worker (uses cached device_name from ~/ionet_device_cache.json,
# not the SSH alias — they may differ, e.g. yahaha → YahahaMac001)
export PATH=/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin
yes Yes | $HOME/io_net_launch_binary_mac \
  --device_id=<device_id> \
  --user_id=<user_id> \
  --operating_system=macOS \
  --usegpus=false \
  --device_name="<cached_name>"

# success signal — wait for this exact substring in launcher stdout:
#   "IO Worker is launched and ready"
# then wait briefly and confirm these Docker images are still running:
#   ionetcontainers/io-worker-vc
#   ionetcontainers/io-worker-monitor
```

### Gotchas

- Non-interactive SSH PATH on macOS is only `/usr/bin:/bin:/usr/sbin:/sbin`.
  Always use absolute paths for `docker`, `open`, etc., or set PATH
  explicitly before invoking them. The launcher's own Docker check also
  depends on PATH, so export the full PATH before running it.
- Docker Desktop takes 30–60 s to be ready after `open -a Docker`. A fixed
  `sleep 8` is **not** enough — poll `docker info` until success.
- The launcher exits 0 in some half-failed states. Do **not** trust exit
  code. The success banner is necessary but not sufficient: the worker
  containers can exit shortly after it. Require the banner plus stable
  `io-worker-vc` and `io-worker-monitor` containers.
- The launcher may buffer device-code prompts unless it runs under a
  pseudo-terminal. Keep the PTY-backed launcher path so users can authorize
  before the code expires.
- Do not immediately re-run a full API check to verify a successful relaunch.
  The API can lag for 10+ minutes and may cause an unnecessary second
  Docker restart. Trust the launcher success banner plus local Docker
  container stability check.
- The registered `device_name` in the launcher cache (`~/ionet_device_cache.json`)
  often differs from the SSH alias. Pass the cached value to `--device_name`
  so io.net does not reregister the device under a new name.

## Code Style

- Follow conventions already in the code being changed.
- Use explicit names for files, functions, variables, tests.
- Keep functions focused and reasonably small.
- Avoid unnecessary abstractions.
- Comments only where the reason is not obvious from the code.
- No new dependencies without clear justification.

## Testing

- Pytest is wired up via `requirements.txt`; run with
  `.venv/bin/python -m pytest tests/ -q`.
- Add or update tests when behavior changes.
- The tests that exist cover parsing (`tests/test_devices.py`,
  `tests/test_explorer.py`) and report rendering (`tests/test_report.py`).
- The remote-action paths (`worker.py`, `ssh_check.py`) are not unit-tested
  because they shell out to SSH/Docker. Manual smoke-test by running
  `.venv/bin/python run.py --device <name>` against one device and reading
  the resulting `data/launch_*.log`.

## Safety Rules

- Do not commit secrets, tokens, refresh tokens, wallet addresses, or
  device IDs to git history (they appear in `ID.md` and `data/last_*.json`
  — both should be gitignored before any push).
- Do not print refresh tokens to stdout or `reports.md`.
- Destructive remote actions (killing Docker, relaunching workers) affect
  earnings on those devices. Confirm scope before running multi-device.
- Prefer `--device <name>` for testing new behavior; only escalate to a
  full `--once` after a successful single-device verification.

## Git and Review Rules

- Keep diffs small and easy to review.
- Do not reformat unrelated files.
- Do not mix refactors with behavior changes unless requested.
- Mention important files changed in the final response.
- Call out risks, assumptions, and follow-up work clearly.

## Repository Map

```text
src/
  devices.py      Parses ID.md → (user_id, [Device])
  explorer.py    /summary, /details fetch + parse + raw dump
  ssh_check.py    SSH reachability probe + battery read
  worker.py       Docker stop/start + worker relaunch over SSH
  report.py       Rendered report + reports.md append
  manager.py      Per-device decision tree + persisted state + loop
tests/            Unit tests (parsers + report rendering + manager decisions)
data/             Per-run artifacts: last_<name>.json, launch_*.log, state.json
launchd/          macOS LaunchAgent plist for 5h unattended checks
scripts/          launchd install/uninstall helpers
logs/             launchd stdout/stderr when daemon is installed
ID.md             user_id + device_id list
reports.md        Append-only check log
run.py            CLI entry point (--once, --device NAME)
requirements.txt  Pinned floor versions for requests + pytest
```

## Tool Notes

Tool-agnostic. Recommended layout:

```text
AGENTS.md          Canonical project instructions (this file)
CLAUDE.md          Pointer to AGENTS.md
.cursor/rules/     Optional tool-specific pointers
```

If another tool needs its own instruction file, keep it short and link
back here to avoid drift.
