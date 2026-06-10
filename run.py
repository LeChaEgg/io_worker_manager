"""Entry point.

Usage:
    python run.py                       # loop forever, checking every 5h
    python run.py --once                # one check on all devices, then exit
    python run.py --once --device NAME  # one check restricted to a single device
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import manager  # noqa: E402

ID_FILE = Path(__file__).resolve().parent / "ID.md"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true",
                   help="run a single check and exit")
    p.add_argument("--device", metavar="NAME",
                   help="restrict to a single device (implies --once)")
    p.add_argument("--interval-hours", type=float, default=5.0,
                   help="loop interval when not using --once (default: 5)")
    args = p.parse_args()

    if args.device and not args.once:
        args.once = True

    if args.once:
        print(manager.run_once(ID_FILE, only=args.device))
        return 0
    manager.run_forever(ID_FILE, interval_s=int(args.interval_hours * 3600))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
