from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Delayed dehydration scanner for Ombre-Brain buckets."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect only (default). Use --write to apply changes.",
    )
    parser.add_argument("--write", action="store_true", help="Actually dehydrate and persist.")
    parser.add_argument(
        "--freshness-days",
        type=int,
        default=0,
        help="Override config N (0 = use config default / env).",
    )
    parser.add_argument("--limit", type=int, default=50, help="Max buckets to process per run.")
    parser.add_argument("--loop", action="store_true", help="Run forever instead of once.")
    parser.add_argument("--interval-minutes", type=float, default=60.0)
    return parser.parse_args(argv)


async def amain() -> int:
    import server  # triggers config/dehydrator/bucket_mgr setup

    args = parse_args()
    dry_run = not args.write
    while True:
        try:
            result = await server.run_delayed_dehydration(
                dry_run=dry_run,
                freshness_days=args.freshness_days or None,
                limit=args.limit,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
        except Exception as e:
            print(json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False))
            if not args.loop:
                return 1
        if not args.loop:
            return 0
        await asyncio.sleep(max(5.0, float(args.interval_minutes) * 60.0))


if __name__ == "__main__":
    raise SystemExit(asyncio.run(amain()))
