#!/usr/bin/env bash
# Rebuilds the first (neon) Vào Được demo video: 56 s, 1920x1080, 60 fps.
# Needs: python3 + numpy + playwright (chromium), ffmpeg.
set -euo pipefail
cd "$(dirname "$0")"
python3 prep.py      # repo OSM / gaps / cameras / flood / tide -> data.js
python3 music.py     # -> music.wav
python3 shoot.py video 60   # -> frames.mkv
ffmpeg -hide_banner -loglevel error -y -i frames.mkv -i music.wav \
  -c:v libopenh264 -b:v 24M -maxrate 30M -pix_fmt yuv420p \
  -c:a aac -b:a 256k -shortest -movflags +faststart ../vao-duoc-neon-demo.mp4
rm -f frames.mkv
echo "done: ../vao-duoc-neon-demo.mp4"
