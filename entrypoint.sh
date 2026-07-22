#!/bin/bash
set -e
if [ "$OMBRE_SERVICE_ROLE" = "gateway" ]; then
  TOKEN="${OMBRE_GITHUB_TOKEN:-}"
  if [ -n "$TOKEN" ]; then
    CLONE_URL="https://x-access-token:${TOKEN}@github.com/yanshishi777/memory.git"
  else
    CLONE_URL="https://github.com/yanshishi777/memory.git"
  fi
  if [ ! -d /data/.git ]; then
    echo "[entrypoint] cloning memory repo..."
    git clone --depth 1 "$CLONE_URL" /data 2>&1 || { echo "[entrypoint] clone failed, using empty /data"; mkdir -p /data; }
  fi
  # background pull loop every 5 min
  (while true; do sleep 300; git -C /data pull --rebase >/dev/null 2>&1 || true; done) &
  echo "[entrypoint] starting gateway (buckets from /data/ombre)"
  exec python gateway.py
else
  echo "[entrypoint] starting brain"
  # 后台 sync：把 buckets 镜像到 yanshishi777/memory 的 ombre/ 下，供 Gateway pull
  SYNC_TOKEN="${OMBRE_GITHUB_TOKEN:-}"
  BD="${OMBRE_BUCKETS_DIR:-/app/buckets}"
  if [ -n "$SYNC_TOKEN" ] && [ -d "$BD" ]; then
    SYNC_URL="https://x-access-token:${SYNC_TOKEN}@github.com/yanshishi777/memory.git"
    (
      set +e
      SYNC_WS="/tmp/ombre-sync"
      rm -rf "$SYNC_WS"
      git clone --depth 1 "$SYNC_URL" "$SYNC_WS" 2>/dev/null || { mkdir -p "$SYNC_WS"; cd "$SYNC_WS"; git init >/dev/null 2>&1; git remote add origin "$SYNC_URL" 2>/dev/null; }
      cd "$SYNC_WS" || exit 0
      git config user.email "brain@ombre.local" 2>/dev/null
      git config user.name "Ombre Brain" 2>/dev/null
      sync_once() {
        rm -rf ombre; mkdir -p ombre
        for sub in permanent dynamic archive feel; do
          [ -d "$BD/$sub" ] && cp -r "$BD/$sub" ombre/ 2>/dev/null
        done
        python - "$BD" <<'PY' 2>/dev/null
import os,json,time,sys
n=sum(len(fs) for _,_,fs in os.walk('ombre'))
json.dump({"synced_at":time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),"file_count":n,"buckets_dir":sys.argv[1]},open(os.path.join('ombre','_ombre_backup_manifest.json'),'w'))
PY
        git add -A >/dev/null 2>&1
        git commit -m "Ombre Brain sync — $(date -u '+%Y-%m-%d %H:%M UTC') ($(find ombre -type f 2>/dev/null | wc -l) files)" >/dev/null 2>&1 && git push origin HEAD:main >/dev/null 2>&1
      }
      sync_once
      while true; do sleep 300; sync_once; done
    ) &
  else
    echo "[entrypoint] OMBRE_GITHUB_TOKEN 未设或 buckets 目录缺失，跳过 sync"
  fi
  exec python server.py
fi
