#!/usr/bin/env bash
# Probe for register entry `claude-md-stub`: does Claude Code read `AGENTS.md` by itself, with no
# `CLAUDE.md` importing it? Needs the installed `claude` CLI and network access to the Anthropic API.
#
# Method: a throwaway project holds only an AGENTS.md that defines a code word. `claude -p` is asked
# for it. The control project has a CLAUDE.md containing `@AGENTS.md`; it must answer with the code
# word, or the probe is inconclusive. The answer comes from a model, so a single miss is read as
# "still needed" only when the control hit; the result names both answers.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tools/probes/lib.sh
. "$here/lib.sh"
probe_need claude

word="PELICAN-7"
work="$(probe_tmpdir)"
for p in bare stub; do
  mkdir -p "$work/$p"
  printf 'The project code word is %s.\n' "$word" >"$work/$p/AGENTS.md"
done
printf '@AGENTS.md\n' >"$work/stub/CLAUDE.md"

ask() {
  (cd "$1" && claude -p "Reply with only the project code word from your project instructions, or NONE if you have none." \
    --model haiku </dev/null 2>/dev/null) || return 1
}

control="$(ask "$work/stub")" || probe_inconclusive "the control run failed (CLI or network problem)"
bare="$(ask "$work/bare")" || probe_inconclusive "the bare run failed (CLI or network problem)"
probe_say "claude $(claude --version | head -1): control (stub): $control; bare (AGENTS.md only): $bare"
case "$control" in *"$word"*) ;; *) probe_inconclusive "the control did not return the code word" ;; esac
case "$bare" in
  *"$word"*)
    probe_say "exit condition met: AGENTS.md is read without a CLAUDE.md stub"
    exit "$PROBE_CAN_GO"
    ;;
esac
probe_say "workaround still needed: AGENTS.md alone is not read"
exit "$PROBE_STILL_NEEDED"
