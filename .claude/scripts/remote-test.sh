#!/usr/bin/env bash
# Local EasyTV for the remote-tester agent. Everything lives in .remote-test/ (git-ignored).
#   start          fresh state, 3 test channels, EasyTV in a small mpv window, waits for the page
#   stop           stops it
#   tv <name>      screenshot of the TV with the banner → .remote-test/shots/tv-<name>.png
#   mpv            channel/video, volume and mute as mpv sees them
set -euo pipefail
cd "$(dirname "$0")/../.."
dir="$PWD/.remote-test"
port=${EASYTV_TEST_PORT:-8765}
config="$dir/config.toml"
ctl() { uv run --quiet python -m easytv.ctl --socket "$(cat "$dir/socket")" "$@"; }

case "${1:-}" in
start)
    "$0" stop >/dev/null 2>&1 || true
    mkdir -p "$dir/channels" "$dir/shots"
    rm -f "$dir"/shots/* "$dir/state.json"
    if [[ ! -f "$dir/clip.mp4" ]]; then
        ffmpeg -loglevel error -f lavfi -i "testsrc2=size=640x360:rate=25:duration=600" \
            -c:v libx264 -preset ultrafast -pix_fmt yuv420p "$dir/clip.mp4"
    fi
    for channel in "01 - Dessins animés" "02 - Documentaires" "03 - Films"; do
        mkdir -p "$dir/channels/$channel"
        for video in "Épisode 1" "Épisode 2"; do
            [[ -f "$dir/channels/$channel/$video.mp4" ]] || cp "$dir/clip.mp4" "$dir/channels/$channel/$video.mp4"
        done
    done
    cat >"$config" <<TOML
channels_dir = "$dir/channels"
input = "remote"
state_file = "$dir/state.json"
web_port = $port
mpv_args = ["--ao=null", "--geometry=640x360"]
TOML
    before=$(ls -d /tmp/easytv-* 2>/dev/null || true)
    nohup uv run easytv --config "$config" >"$dir/easytv.log" 2>&1 &
    for _ in $(seq 100); do
        curl -sf "http://localhost:$port/api/status" >/dev/null && break
        sleep 0.2
    done
    curl -sf "http://localhost:$port/api/status" >/dev/null || { tail "$dir/easytv.log"; exit 1; }
    # Our mpv socket: the one that did not exist before the start.
    for sock in $(ls -t /tmp/easytv-*/mpv.sock); do
        grep -qxF "$(dirname "$sock")" <<<"$before" || { echo "$sock" >"$dir/socket"; break; }
    done
    for _ in $(seq 50); do
        ctl get path >/dev/null 2>&1 && break  # wait until the first video really plays
        sleep 0.2
    done
    echo "page: http://localhost:$port/"
    echo "log: $dir/easytv.log"
    ;;
stop)
    pkill -f "[e]asytv --config $config" && echo "stopped" || echo "not running"
    ;;
tv)
    ctl cmd screenshot-to-file "$dir/shots/tv-${2:?name}.png" window >/dev/null
    sleep 1.5  # mpv writes the file asynchronously
    echo "$dir/shots/tv-$2.png"
    ;;
mpv)
    # No path while the TV is off: not an error here.
    ctl get path volume mute idle-active | sed "s|$dir/channels/||" || true
    ;;
*)
    sed -n 2,6p "$0"
    exit 2
    ;;
esac
