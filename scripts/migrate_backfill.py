#!/usr/bin/env python3
"""Ombre-Brain 遗留桶元数据回填客户端。

调用 brain 的 /api/admin/migrate-backfill 端点（memory-write token 鉴权）。

用法：
  # 预览全量计划（不写库）
  python scripts/migrate_backfill.py --dry-run

  # 小范围应用 5 个桶
  python scripts/migrate_backfill.py --apply --limit 5

  # 全量应用
  python scripts/migrate_backfill.py --apply

  # 只回填 date
  python scripts/migrate_backfill.py --apply --modes date

环境变量：OMBRE_GATEWAY_TOKEN（缺省走命令行 --token）。
"""
import argparse
import json
import os
import sys

import httpx

DEFAULT_HOST = "https://ombre-brain-production-483d.up.railway.app"
ENDPOINT = "/api/admin/migrate-backfill"


def main() -> int:
    ap = argparse.ArgumentParser(description="Ombre-Brain 遗留桶元数据回填")
    ap.add_argument("--host", default=os.environ.get("OMBRE_BRAIN_HOST", DEFAULT_HOST))
    ap.add_argument("--token", default=os.environ.get("OMBRE_GATEWAY_TOKEN", ""))
    ap.add_argument("--dry-run", action="store_true", help="只生成计划（默认行为）")
    ap.add_argument("--apply", action="store_true", help="实际写库（与 --dry-run 互斥）")
    ap.add_argument("--limit", type=int, default=0, help="最多应用 N 个桶（0=不限）")
    ap.add_argument("--modes", default="date,proactive", help="回填字段，逗号分隔：date,proactive")
    args = ap.parse_args()

    if not args.token:
        print("ERROR: 需要 OMBRE_GATEWAY_TOKEN（env）或 --token", file=sys.stderr)
        return 2

    dry_run = not args.apply
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    url = f"{args.host.rstrip('/')}{ENDPOINT}"
    payload = {"dry_run": dry_run, "limit": args.limit, "modes": modes}

    print(f">> POST {url}")
    print(f"   dry_run={dry_run} limit={args.limit} modes={modes}")

    with httpx.Client(timeout=120) as c:
        r = c.post(
            url,
            headers={"Authorization": f"Bearer {args.token}"},
            json=payload,
        )
    print(f"<< HTTP {r.status_code}")
    try:
        data = r.json()
    except Exception:
        print(r.text[:500])
        return 1
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
