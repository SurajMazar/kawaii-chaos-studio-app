#!/bin/bash
# Strip -> silent strip reel -> Instagram upload copies, for one or more projects.
#   scripts/build_reel.sh rem_cooking waguri_selfie ...
# Needs projects/<name>/strip.png. Uses the real panel boxes (detect_panels.py), not the wireframe.
set -e
cd "$(dirname "$0")/.."
PY=${PY:-python3}
for p in "$@"; do
  d=projects/$p
  # HARD QA GATE (qa_rules.md): refuse unless qa.md holds "PASS <sha1 of strip.png>"
  sha=$(shasum $d/strip.png | cut -d' ' -f1)
  if ! grep -q "^PASS $sha" $d/qa.md 2>/dev/null; then echo "REFUSED $p: no QA pass for current strip.png (see qa_rules.md)"; continue; fi
  "$PY" scripts/detect_panels.py $d/strip.png --out $d/layout/layout_actual.json
  rm -rf $d/strip_reel
  "$PY" scripts/strip_reel.py $d/strip.png $d/strip_reel --layout $d/layout/layout_actual.json --silent --per 3.6 >/dev/null
  "$PY" scripts/render.py $d/strip_reel/storyboard.json >/dev/null 2>&1
  ffmpeg -v error -y -i $d/strip_reel/strip_reel.mp4 -c:v libx264 -preset slow -crf 20 -pix_fmt yuv420p \
    -movflags +faststart -c:a aac -b:a 128k upload/${p}_strip_reel.mp4
  cp $d/strip.png upload/${p}_strip.png
  echo "$p -> upload/${p}_strip_reel.mp4 ($(du -h upload/${p}_strip_reel.mp4 | cut -f1))"
done
