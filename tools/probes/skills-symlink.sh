#!/usr/bin/env bash
# Probe for register entry `skills-symlink`: does Claude Code load skills from `.agents/skills/`
# without the committed `.claude/skills` symlink? Needs the installed `claude` CLI and network
# access to the Anthropic API (a nested `claude -p` run with the cheapest model).
#
# Method (notes 13.11): a throwaway project holds one SKILL.md under `.agents/skills/probe-skill/`.
# `claude -p` is run in it with stream-json output; the skill name is looked up in the `skills`
# list of the `system`/`init` event. Run twice: bare (no symlink) and with the symlink as control.
# The control must list the skill, or the probe cannot tell anything and is inconclusive.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tools/probes/lib.sh
. "$here/lib.sh"
probe_need claude
probe_need python3

work="$(probe_tmpdir)"
make_project() { # $1 = directory, $2 = "link" to add the symlink
  mkdir -p "$1/.agents/skills/probe-skill"
  cat >"$1/.agents/skills/probe-skill/SKILL.md" <<'SKILL'
---
name: probe-skill
description: Probe only. Use when told to run the harness probe.
---
Probe skill.
SKILL
  if [ "$2" = link ]; then
    mkdir -p "$1/.claude"
    ln -s ../.agents/skills "$1/.claude/skills"
  fi
}

# Prints "yes" when the init event lists probe-skill, "no" when it does not; fails on no init event.
lists_skill() {
  (cd "$1" && claude -p "ok" --model haiku --output-format stream-json --verbose </dev/null 2>/dev/null) |
    python3 -I -c '
import json, sys
for line in sys.stdin:
    try:
        event = json.loads(line)
    except ValueError:
        continue
    if event.get("type") == "system" and event.get("subtype") == "init":
        names = [s if isinstance(s, str) else s.get("name", "") for s in event.get("skills", [])]
        print("yes" if any(n.endswith("probe-skill") for n in names) else "no")
        sys.exit(0)
sys.exit(1)
'
}

make_project "$work/bare" none
make_project "$work/linked" link
bare="$(lists_skill "$work/bare")" || probe_inconclusive "no init event without the symlink (CLI or network problem)"
linked="$(lists_skill "$work/linked")" || probe_inconclusive "no init event with the symlink (CLI or network problem)"
probe_say "claude $(claude --version | head -1): without symlink: $bare; with symlink (control): $linked"
[ "$linked" = yes ] || probe_inconclusive "the control (with symlink) does not list the skill"
if [ "$bare" = yes ]; then
  probe_say "exit condition met: .agents/skills is loaded without the symlink"
  exit "$PROBE_CAN_GO"
fi
probe_say "workaround still needed: .agents/skills is not loaded without the symlink"
exit "$PROBE_STILL_NEEDED"
