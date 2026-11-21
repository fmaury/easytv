#!/usr/bin/env bash
# PreToolUse hook on Bash: Claude may not bypass the git pre-commit hook or the protected tests.
# Exit code 2 blocks the command and tells Claude why.
cmd=$(python3 -c 'import json, sys; print(json.load(sys.stdin).get("tool_input", {}).get("command", ""))')

block() {
    echo "Blocked by .claude/hooks/guard.sh: $1. Ask the user instead." >&2
    exit 2
}

[[ "$cmd" == *--no-verify* ]] && block "--no-verify skips the pre-commit checks"
[[ "$cmd" =~ git[[:space:]].*commit.*[[:space:]]-[a-zA-Z]*n([[:space:]]|$) ]] &&
    block "git commit -n skips the pre-commit checks"
[[ "$cmd" == *EASYTV_ALLOW_TEST_CHANGES* ]] && block "only the user may allow test changes"
[[ "$cmd" == *core.hooksPath* && "$cmd" != *--get* ]] &&
    block "changing core.hooksPath disables the pre-commit checks"
exit 0
