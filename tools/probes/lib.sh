#!/usr/bin/env bash
# Shared helpers of the workaround probes (docs/workaround-register.md). Sourced, never run.
#
# Exit-code contract of every probe, so that /dev-harness-review can read the result without parsing text:
#   0   the workaround is still needed (the exit condition is NOT met)
#   10  the exit condition is met: the workaround can be proposed for removal
#   2   inconclusive (agent CLI missing, no network, unexpected output): nothing is concluded
# A probe only reads and reports. It never edits the repository; scratch projects live under mktemp.

# shellcheck disable=SC2034  # used by the sourcing probes
PROBE_STILL_NEEDED=0
# shellcheck disable=SC2034
PROBE_CAN_GO=10
PROBE_INCONCLUSIVE=2

probe_say() { printf '%s\n' "$*"; }

probe_inconclusive() {
  probe_say "inconclusive: $*"
  exit "$PROBE_INCONCLUSIVE"
}

# Scratch directory removed on exit. Prints its path.
probe_tmpdir() {
  local d
  d="$(mktemp -d "${TMPDIR:-/tmp}/probe.XXXXXX")" || probe_inconclusive "mktemp failed"
  # shellcheck disable=SC2064  # expand now: the path is fixed
  trap "rm -rf '$d'" EXIT
  printf '%s\n' "$d"
}

probe_need() {
  command -v "$1" >/dev/null 2>&1 || probe_inconclusive "$1 not installed"
}
