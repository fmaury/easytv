#!/usr/bin/env bash
# PostToolUse hook: format and lint any Python file Claude just edited.
# Exit code 2 sends remaining lint errors back to Claude so it fixes them.
file=$(python3 -c 'import json, sys; print(json.load(sys.stdin).get("tool_input", {}).get("file_path", ""))')
[[ "$file" == *.py && -f "$file" ]] || exit 0
command -v uv >/dev/null || exit 0
cd "$CLAUDE_PROJECT_DIR" || exit 0

uv run --quiet ruff format "$file" >/dev/null 2>&1
if ! out=$(uv run --quiet ruff check --fix "$file" 2>&1); then
    echo "$out" >&2
    exit 2
fi
