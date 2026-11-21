#!/usr/bin/env bash
# Stop hook: when Python files changed, block the end of the turn until ruff and mypy pass.
# Exit code 2 sends the errors back to Claude. pytest is left out (slow: it starts a real mpv).
active=$(python3 -c 'import json, sys; print(json.load(sys.stdin).get("stop_hook_active", False))')
[[ "$active" == "True" ]] && exit 0  # already relaunched once by this hook: never loop
command -v uv >/dev/null || exit 0
cd "$CLAUDE_PROJECT_DIR" || exit 0
[[ -n "$(git status --porcelain -- '*.py')" ]] || exit 0

failed=0
for check in "ruff format --check ." "ruff check ." "mypy"; do
    # shellcheck disable=SC2086
    if ! out=$(uv run --quiet $check 2>&1); then
        echo "\`$check\` failed:" >&2
        echo "$out" >&2
        failed=1
    fi
done
exit $((failed * 2))
