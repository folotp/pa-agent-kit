#!/usr/bin/env bash
# Claude Code cloud environment — setup script.
#
# Purpose:   give cloud (claude.ai/code) sessions the tool versions CI uses, so a
#            cloud session can catch red CI before pushing instead of after.
# Usage:     run `bash scripts/cloud-env-setup.sh` once the repository is checked
#            out. A pasted setup script can run the mise bootstrap before checkout:
#            the repository step is then deferred until `./dev` and `mise.toml` exist.
# Network:   downloads use GitHub releases (mise, then the tools in mise.lock).
#
# Repository tools come from mise.lock via ./dev. Keep MISE_VERSION and MISE_SHA256
# below in sync with .github/workflows/validate.yml, specs-bump.yml and mise-bump.yml
# (a person moves them, the mise-bump job only reports a newer release).
#
# Failures are reported but never abort the script: a missing tool only degrades a
# cloud session, whereas a failed setup script blocks the session from starting.

# The install_* functions run indirectly through step "$@", which ShellCheck
# cannot follow, so it reports them as never invoked.
# shellcheck disable=SC2329
set -uo pipefail

MISE_VERSION="v2026.11.12"
MISE_SHA256="9c12c24f5eac6b6357e5265e2629166cc3005459037f5d747680a99e375ff2ab"

failures=()

step() {
  local name="$1"
  shift
  printf '==> %s\n' "$name"
  if ! "$@"; then
    printf '!! %s failed (continuing)\n' "$name"
    failures+=("$name")
  fi
}

# sudo is absent when the environment already runs as root.
as_root() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  else
    sudo "$@"
  fi
}

install_guard_jq() {
  # The guard parses hook input before a repository command can run under mise.
  command -v jq >/dev/null 2>&1 && return 0
  command -v apt-get >/dev/null 2>&1 || return 1
  as_root apt-get update -qq &&
    as_root env DEBIAN_FRONTEND=noninteractive \
      apt-get install -y -qq --no-install-recommends jq
}

install_mise() {
  if [ "$(uname -s)" != Linux ] || [ "$(uname -m)" != x86_64 ]; then
    printf 'mise bootstrap expects a Linux x64 cloud session\n' >&2
    return 1
  fi
  local tmp rc
  tmp="$(mktemp -d)" || return 1
  curl -fsSL -o "$tmp/mise" "https://github.com/jdx/mise/releases/download/${MISE_VERSION}/mise-${MISE_VERSION}-linux-x64" &&
    (cd "$tmp" && printf '%s  mise\n' "$MISE_SHA256" | sha256sum -c -) &&
    mkdir -p "$HOME/.local/bin" &&
    install -m 0755 "$tmp/mise" "$HOME/.local/bin/mise" &&
    "$HOME/.local/bin/mise" --version
  rc=$?
  rm -rf "$tmp"
  return "$rc"
}

run_dev() {
  # Scope the mise location to ./dev; no activation or shim directory on the outer PATH.
  PATH="$HOME/.local/bin:$PATH" ./dev "$@"
}

step "mise ${MISE_VERSION}" install_mise
if [ ! -x ./dev ] || [ ! -f mise.toml ]; then
  printf '\nRepository setup deferred until checkout.\n'
else
  if [ -z "${failures[*]:-}" ]; then
    step "trust repository mise config" "$HOME/.local/bin/mise" trust mise.toml
  fi
  if [ -z "${failures[*]:-}" ]; then
    step "locked repository tools" run_dev setup
  else
    printf 'Repository setup skipped after a bootstrap failure.\n'
  fi
fi
# The guard needs jq even when repository setup is deferred.
step "guard jq" install_guard_jq

if [ -n "${failures[*]:-}" ]; then
  printf '\nSetup finished with %d failed step(s): %s\n' \
    "${#failures[@]}" "${failures[*]}"
elif [ -x ./dev ] && [ -f mise.toml ]; then
  printf '\nSetup finished: locked tools ready; run ./dev ci.\n'
else
  printf '\nSetup finished: cloud prerequisites ready, repository setup deferred.\n'
fi
exit 0
