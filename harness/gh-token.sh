#!/usr/bin/env bash
# GitHub identities for agents on PA's Mac.
#
# Agents act on GitHub as their own GitHub App ("<slug>[bot]"), with a
# one-hour installation token limited to one repository. PA's own token is
# released only through a Keychain item that prompts on every read, for one
# command at a time. See harness/gh-token.md for setup and the routine.
#
# Usage: see usage() below (also printed by -h).
#
# Secrets: the App key and every token stay in shell variables and pipes.
# Nothing is written to disk, nothing is logged, and no error message
# includes a key or a token (only HTTP status and GitHub's own message).
# A token minted for --info or -- CMD is revoked by an exit trap set right
# after minting, so an error or Ctrl-C revokes it too. A --print token is
# the caller's, never revoked here: it expires within the hour.
# Owner mode (pa -- CMD) exports PA's token to CMD and everything CMD
# starts, for as long as they run; nothing here can narrow or revoke it.
set -euo pipefail

readonly API="https://api.github.com"
readonly KEY_SERVICE="github-app-key"     # Keychain: one item per App, account = <app>, base64 PEM
readonly PA_SERVICE="github-pa-token"     # Keychain: PA's token, created with -T "" (prompts on read)
readonly PA_ACCOUNT="folotp"

# Client IDs are public identifiers (shown on each App's settings page),
# used as the JWT issuer. They are not secrets.
app_client_id() {
  case "$1" in
    claude)      echo "Iv23li93JbcQEcW5fiFP" ;;
    codex)       echo "Iv23liyqCxYwVTXgMJgs" ;;
    antigravity) echo "Iv23liW8IXluzu06qaSm" ;;
    *)           return 1 ;;
  esac
}

die() { printf 'gh-token: %s\n' "$*" >&2; exit 1; }

usage() {
  cat >&2 <<'EOF'
Usage:
  gh-token.sh <app> [--repo OWNER/NAME] [--read-only] -- CMD...  run CMD as the bot, then revoke
  gh-token.sh <app> [--repo OWNER/NAME] [--read-only] --info     print expiry and scope, no token
  gh-token.sh <app> [--repo OWNER/NAME] [--read-only] --print    print a token on stdout (never revoked here)
  gh-token.sh pa -- CMD...                         run CMD with PA's token (prompts)

<app> is one of: claude, codex, antigravity.
--repo defaults to the origin remote of the current directory.
--read-only narrows every permission of the token to read (the release gate's reads).
EOF
  exit 2
}

# The token minted for --info or -- CMD, revoked by the exit trap (revoke_minted).
minted_token=""
revoke_minted() {
  [[ -n $minted_token ]] || return 0
  # In a subshell: a failed request (api dies) must not replace the command's exit status.
  (api DELETE /installation/token token "$minted_token" >/dev/null) ||
    printf 'gh-token: revoke failed; the token expires within the hour\n' >&2
  minted_token=""
}

b64url() { openssl base64 -A | tr '+/' '-_' | tr -d '='; }

# api METHOD PATH AUTH_SCHEME CREDENTIAL [JSON_BODY]
# The Authorization header goes to curl on stdin, never on its command line.
# On failure, prints only the HTTP status and GitHub's "message" field.
api() {
  local method=$1 path=$2 scheme=$3 cred=$4 body=${5:-} out status
  # --max-time: a request that hangs ends in a refusal, not a stuck command (Codex C23).
  local -a args=(-sS --max-time 30 -X "$method" -H @- -H "Accept: application/vnd.github+json"
                 -H "X-GitHub-Api-Version: 2022-11-28" -w '\n%{http_code}')
  [[ -n $body ]] && args+=(-H "Content-Type: application/json" --data "$body")
  out=$(printf 'Authorization: %s %s\n' "$scheme" "$cred" | curl "${args[@]}" "$API$path") \
    || die "request failed: $method $path (curl error)"
  status=${out##*$'\n'}
  out=${out%$'\n'*}
  if [[ $status != 2* ]]; then
    die "$method $path: HTTP $status: $(printf '%s' "$out" | jq -r '.message // "no message"' 2>/dev/null || echo 'unreadable body')"
  fi
  printf '%s' "$out"
}

# Resolve OWNER/NAME from --repo or from the origin remote (https or ssh form).
resolve_repo() {
  local repo=$1 url
  if [[ -z $repo ]]; then
    url=$(git remote get-url origin 2>/dev/null) || die "no --repo given and no origin remote here"
    repo=${url#*github.com[:/]}
    repo=${repo%.git}
  fi
  [[ $repo =~ ^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$ ]] || die "not an OWNER/NAME repository: $repo"
  printf '%s' "$repo"
}

# Sign a 9-minute App JWT. The PEM reaches openssl through a pipe, not a file.
app_jwt() {
  local client_id=$1 pem=$2 now header payload signature
  now=$(date +%s)
  header=$(printf '{"alg":"RS256","typ":"JWT"}' | b64url)
  payload=$(printf '{"iat":%d,"exp":%d,"iss":"%s"}' $((now - 60)) $((now + 540)) "$client_id" | b64url)
  signature=$(printf '%s.%s' "$header" "$payload" \
    | openssl dgst -sha256 -binary -sign <(printf '%s\n' "$pem") 2>/dev/null | b64url) \
    || die "could not sign the JWT (is the stored key a valid PEM?)"
  [[ -n $signature ]] || die "could not sign the JWT (is the stored key a valid PEM?)"
  printf '%s.%s.%s' "$header" "$payload" "$signature"
}

# Git and gh read the token from GH_TOKEN. The credential helper list is
# reset first, so no stored credential (osxkeychain) is ever consulted, and
# ssh remotes on github.com are rewritten to https for the same reason.
export_git_auth() {
  export GH_TOKEN=$1
  unset GITHUB_TOKEN
  export GIT_CONFIG_COUNT=3
  export GIT_CONFIG_KEY_0="credential.https://github.com.helper" GIT_CONFIG_VALUE_0=""
  # shellcheck disable=SC2016  # expanded by git's shell at use, not here
  export GIT_CONFIG_KEY_1="credential.https://github.com.helper" \
         GIT_CONFIG_VALUE_1='!f() { test "$1" = get && printf "username=x-access-token\npassword=%s\n" "$GH_TOKEN"; }; f'
  export GIT_CONFIG_KEY_2="url.https://github.com/.insteadOf" GIT_CONFIG_VALUE_2="git@github.com:"
}

# token_request NAME INSTALLATION_JSON READ_ONLY: the body of the token request. The token is
# always limited to the one repository NAME; with READ_ONLY non-empty, every permission the
# installation holds is requested at level read (GitHub accepts a subset of the installation's
# permissions, and refuses the request rather than widen one).
token_request() {
  if [[ -n $3 ]]; then
    printf '%s' "$2" | jq -c --arg r "$1" '{repositories: [$r], permissions: (.permissions | map_values("read"))}'
  else
    jq -cn --arg r "$1" '{repositories: [$r]}'
  fi
}

run_as_pa() {
  local token
  [[ $# -gt 0 ]] || die "pa needs a command after --"
  printf 'gh-token: releasing PA'"'"'s token for one command: %s\n' "$*" >&2
  token=$(security find-generic-password -s "$PA_SERVICE" -a "$PA_ACCOUNT" -w 2>/dev/null) \
    || die "PA's token was not released (prompt denied, or no Keychain item $PA_SERVICE)"
  export_git_auth "$token"
  unset token
  exec "$@"
}

main() {
  [[ $# -ge 1 ]] || usage
  local app=$1; shift
  local repo="" mode="" read_only=""
  case $app in -h|--help) usage ;; esac

  if [[ $app == pa ]]; then
    [[ ${1:-} == -- ]] || die "usage: gh-token.sh pa -- CMD..."
    shift
    run_as_pa "$@"
  fi

  while [[ $# -gt 0 ]]; do
    case $1 in
      --repo) repo=${2:?--repo needs OWNER/NAME}; shift 2 ;;
      --info) [[ -z $mode ]] || usage; mode="info"; shift ;;
      --print) [[ -z $mode ]] || usage; mode="print"; shift ;;
      --read-only) read_only=1; shift ;;
      --) [[ -z $mode ]] || usage; mode="exec"; shift; break ;;
      *) usage ;;
    esac
  done
  # Printing a token is never the default: it needs --print (finding K24).
  [[ -n $mode ]] || usage
  [[ $mode != exec || $# -gt 0 ]] || die "no command after --"

  local client_id key_b64 pem jwt install_json install_id token_json token slug bot_id
  client_id=$(app_client_id "$app") || die "unknown app: $app (claude, codex, antigravity)"
  [[ -n $client_id ]] || die "no Client ID recorded for $app in this script"
  repo=$(resolve_repo "$repo")

  key_b64=$(security find-generic-password -s "$KEY_SERVICE" -a "$app" -w 2>/dev/null) \
    || die "no Keychain item $KEY_SERVICE/$app (see harness/gh-token.md)"
  pem=$(printf '%s' "$key_b64" | tr -d ' \n' | openssl base64 -d -A 2>/dev/null) || true
  unset key_b64
  [[ $pem == -----BEGIN* ]] || die "Keychain item $KEY_SERVICE/$app is not a base64-encoded PEM"

  jwt=$(app_jwt "$client_id" "$pem")
  unset pem
  install_json=$(api GET "/repos/$repo/installation" Bearer "$jwt")
  install_id=$(printf '%s' "$install_json" | jq -r '.id')
  token_json=$(api POST "/app/installations/$install_id/access_tokens" Bearer "$jwt" \
    "$(token_request "${repo#*/}" "$install_json" "$read_only")")
  token=$(printf '%s' "$token_json" | jq -r '.token')
  [[ -n $token && $token != null ]] || die "GitHub returned no token"

  if [[ $mode == print ]]; then
    unset token_json
    printf '%s\n' "$token"
    return 0
  fi

  # From here on, every exit revokes the token: an error, Ctrl-C, or the end.
  minted_token=$token
  trap revoke_minted EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM

  if [[ $mode == info ]]; then
    # Scope and expiry only: the token itself is never printed.
    printf '%s' "$token_json" | jq --arg app "$app" --arg repo "$repo" \
      '{app: $app, repo: $repo, expires_at, permissions, repository_selection}'
    return 0
  fi
  unset token_json

  # exec: commit as the bot, run the command, revoke the token afterwards.
  slug=$(api GET /app Bearer "$jwt" | jq -r '.slug')
  unset jwt
  bot_id=$(api GET "/users/${slug}%5Bbot%5D" token "$token" | jq -r '.id')
  export GIT_AUTHOR_NAME="${slug}[bot]" GIT_COMMITTER_NAME="${slug}[bot]"
  export GIT_AUTHOR_EMAIL="${bot_id}+${slug}[bot]@users.noreply.github.com"
  export GIT_COMMITTER_EMAIL=$GIT_AUTHOR_EMAIL
  export_git_auth "$token"
  printf 'gh-token: running as %s[bot] on %s\n' "$slug" "$repo" >&2

  local rc=0
  "$@" || rc=$?
  revoke_minted
  unset token GH_TOKEN
  return "$rc"
}

# Run only when executed, so tests can source the functions.
if [[ ${BASH_SOURCE[0]} == "$0" ]]; then main "$@"; fi
