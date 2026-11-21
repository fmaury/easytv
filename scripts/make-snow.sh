#!/usr/bin/env bash
# Regenerates src/easytv/snow.mp4: the TV snow shown between channels (image and "shhh" sound), 2.2 s:
# EasyTV cuts it at snow_seconds (2 s at most).
# H.264 so that the Pi 3 decodes it in hardware; small and blocky like an old TV, mpv scales it up.
# Usage: scripts/make-snow.sh   (needs ffmpeg)
set -euo pipefail
out="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/src/easytv/snow.mp4"
ffmpeg -loglevel error -y \
    -f lavfi -i "nullsrc=size=320x180:rate=25:duration=2.2,geq=lum='random(1)*255':cb=128:cr=128" \
    -f lavfi -i "anoisesrc=color=white:amplitude=0.15:duration=2.2:sample_rate=48000" \
    -c:v libx264 -profile:v main -pix_fmt yuv420p -crf 32 \
    -c:a aac -b:a 64k -ac 2 \
    -shortest -movflags +faststart "$out"
echo "$out"
