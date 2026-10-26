#!/bin/bash
# Build silent strip reels for every project that has strip.png but no upload/<name>_strip_reel.mp4.
# Safe to call any time: a lock directory makes a second call exit immediately instead of racing/deadlocking
# (don't use `pgrep -f` waiters — they match their own command line).
#   scripts/build_missing.sh            # loops until nothing is missing (picks up strips added meanwhile)
cd "$(dirname "$0")/.."
LOCK=/tmp/kawaii_build_missing.lock
mkdir "$LOCK" 2>/dev/null || { echo "already running"; exit 0; }
trap 'rmdir "$LOCK"' EXIT
while :; do
  todo=$(for d in projects/*/; do n=$(basename "$d"); [ -f "$d/strip.png" ] && [ ! -f "upload/${n}_strip_reel.mp4" ] && echo "$n"; done)
  [ -z "$todo" ] && break
  for n in $todo; do scripts/build_reel.sh "$n" 2>&1 | grep -E "upload|rror"; done
done
python3 scripts/update_trackers.py
