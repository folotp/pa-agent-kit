#!/usr/bin/env bash
# Probe for register entry `plugin-zips`: do the Gemini hosts install skills or plugins without a
# hand-imported zip? Part of this cannot be automated: the Gemini app is a web and desktop UI.
#
# The script reports what it can see (the installed Gemini CLI and Antigravity, and what their help
# says about plugins and skills) and then prints the manual steps. It never concludes "can go" on
# its own: the exit code is 2 (inconclusive) until PA records the manual result in the register.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tools/probes/lib.sh
. "$here/lib.sh"

for cli in gemini agy; do
  if command -v "$cli" >/dev/null 2>&1; then
    probe_say "$cli: $("$cli" --version 2>/dev/null | head -1)"
    for word in plugin skill extension; do
      n="$("$cli" --help 2>&1 | grep -ci "$word" || true)"
      probe_say "  '$word' mentioned $n time(s) in --help"
    done
  else
    probe_say "$cli: not installed"
  fi
done
cat <<'MANUAL'

Manual part (the Gemini app; last result: refused a `.plugin`, accepted a per-skill zip, 2026-11-17):
  1. Build the zips: python3 scripts/plugin_zip.py --ref HEAD --out "$TMPDIR/zips" --skills --list
  2. In the Gemini app, import one `<plugin>.plugin`. Accepted = the exit condition for the .plugin zip.
  3. Import one `<skill>.zip`. If a skill folder, a git URL or a marketplace entry installs directly,
     the per-skill zips can go too.
  4. Record the result and date in the register entry, then re-run harness-review.
MANUAL
probe_inconclusive "manual part pending"
