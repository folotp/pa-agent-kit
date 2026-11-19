#!/usr/bin/env bash
# git-prune-merged.sh: delete local branches whose pull request is merged, with their worktrees,
# after checking that nothing would be lost. Core file (24g row H1); the skill
# /dev-delete-merged-branches wraps it, and `./dev update-local-repo` runs it with --all.
#
# Why: every repository squash-merges, so git never sees a merged branch as merged; `git branch -d`
# refuses it and only a forced delete works. The core guard refuses a forced delete from agent
# sessions on purpose: it cannot tell a merged branch from unmerged work. This script is the narrow
# way through: it deletes a branch only when GitHub proves the work landed.
#
# Usage (from the main checkout, never from inside the worktree being removed):
#   .harness/gh-token.sh <bot> -- .harness/git-prune-merged.sh [--dry-run] BRANCH...
#   .harness/gh-token.sh <bot> -- .harness/git-prune-merged.sh [--dry-run] --all
# (in the workshop the paths are harness/…). --all considers every local branch: one without a
# merged pull request is skipped quietly (it is still being worked on), every other refusal is
# reported as for a named branch.
#
# For each branch, every check must pass, or the branch is left alone:
#   1. the name is not protected: main, master, and the `protected_branches` array of the
#      repository's harness.toml (read through conf.awk; standing branches a repository keeps);
#   2. the local branch exists;
#   3. a pull request from the branch is merged on GitHub, and its last commit is exactly the
#      local branch tip, so nothing was committed after it;
#   4. if a worktree has the branch checked out: it is not the current directory, and
#      `git status --porcelain` is empty there (untracked files count).
# Then the worktree is removed (`git worktree remove`, no --force) and the branch is deleted
# (forced, which is safe after check 3).
#
# Branches are handled one by one; one refusal does not stop the others. Exit 0 when nothing was
# refused (every named branch pruned, or would be with --dry-run), 1 when at least one branch was
# refused, 2 on a usage error or a repository it cannot read. The last three lines follow the
# core's output rule (done: / left for PA: / next:). Needs `gh` with a token in the environment:
# the gh-token.sh wrapper provides one.
#
# Local only: the branch on GitHub is never touched. GitHub deletes it at merge only when the
# repository setting "Automatically delete head branches" is on; otherwise it stays on GitHub
# until PA deletes it (the PR page's "Delete branch" button).
set -euo pipefail

here_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# The path PA or an agent types to run this script again: .harness/… in a consumer, harness/… here.
self_name="$(basename "$here_dir")/$(basename "${BASH_SOURCE[0]}")"

say() { printf 'git-prune-merged: %s\n' "$*"; }
refuse() { printf 'git-prune-merged: KEEP %s: %s\n' "$1" "$2" >&2; }

# The output rule's three lines, on stdout (or stderr for a usage error).
ending() { printf 'done: %s\nleft for PA: %s\nnext: %s\n' "$1" "$2" "$3"; }

# A usage error or an unreadable repository: nothing was looked at, nothing changed. Exit 2.
stop() {
  say "$1"
  ending "refused; nothing changed" "nothing" "${2:-/dev-delete-merged-branches <branch>…, or --all}" >&2
  exit 2
}

usage() {
  printf 'usage: %s [--dry-run] BRANCH... | [--dry-run] --all\n' "$self_name" >&2
  ending "refused; nothing changed" "nothing" "/dev-delete-merged-branches <branch>…, or --all" >&2
  exit 2
}

dry_run=0
all=0
branches=()
for arg in "$@"; do
  case "$arg" in
    --dry-run) dry_run=1 ;;
    --all) all=1 ;;
    -h | --help) usage ;;
    -*) say "unknown option $arg"; usage ;;
    *) branches+=("$arg") ;;
  esac
done
if [ "$all" = 1 ]; then
  [ "${#branches[@]}" -eq 0 ] || { say "--all takes no branch names"; usage; }
else
  [ "${#branches[@]}" -gt 0 ] || usage
fi

top=$(git rev-parse --show-toplevel 2>/dev/null) || stop "not inside a git repository"

# Protected names: the two defaults plus the repository's own standing branches. A harness.toml
# that conf.awk refuses stops the run: a typo there must not unprotect a branch.
protected="main master"
if [ -f "$top/harness.toml" ]; then
  conf=$(awk -f "$here_dir/conf.awk" "$top/harness.toml") || stop "harness.toml is refused (line above)" "fix harness.toml, then /dev-delete-merged-branches"
  extra=$(printf '%s\n' "$conf" | awk -F'\t' '$1 == "conf" && $2 == "protected_branches" { print $3 }')
  protected="$protected${extra:+ $extra}"
fi

# owner/name from the origin remote: https://github.com/o/n(.git) or git@github.com:o/n(.git)
origin_url=$(git remote get-url origin 2>/dev/null) || stop "no origin remote"
repo_slug=$(printf '%s\n' "$origin_url" | sed -E -n 's#^.*github\.com[:/]([^/]+/[^/]+)$#\1#p' | sed 's/\.git$//')
[ -n "$repo_slug" ] || stop "origin is not a GitHub remote: $origin_url"

if [ "$all" = 1 ]; then
  names=$(git for-each-ref --format='%(refname:short)' refs/heads/) || stop "cannot enumerate branches"
  while IFS= read -r b; do
    [ -n "$b" ] || continue
    case " $protected " in *" $b "*) continue ;; esac
    branches+=("$b")
  done <<<"$names"
fi

here=$(pwd -P)
status=0
pruned=()
kept=()
open=0

for b in ${branches[@]+"${branches[@]}"}; do
  case " $protected " in
    *" $b "*) refuse "$b" "protected branch name"; status=1; kept+=("$b"); continue ;;
  esac

  tip=$(git rev-parse --verify -q "refs/heads/$b^{commit}") || {
    refuse "$b" "no such local branch"; status=1; kept+=("$b"); continue
  }

  # Every merged PR whose head branch is this one; a reused name can have several.
  if ! heads=$(gh pr list --repo "$repo_slug" --state merged --head "$b" --limit 50 \
      --json number,headRefOid --jq '.[] | "\(.number) \(.headRefOid)"' 2>&1); then
    refuse "$b" "could not ask GitHub ($(printf '%s' "$heads" | tr '\n' ' '))"; status=1; kept+=("$b"); continue
  fi
  pr=""
  while read -r num oid; do
    [ -n "${num:-}" ] || continue
    if [ "$oid" = "$tip" ]; then pr="$num"; break; fi
  done <<<"$heads"
  if [ -z "$pr" ]; then
    if [ -z "$heads" ]; then
      if [ "$all" = 1 ]; then open=$((open + 1)); continue; fi
      refuse "$b" "no merged pull request from this branch"
    else
      refuse "$b" "local tip ${tip:0:7} is not the last commit of any merged pull request from it (commits after the merge, or a different branch of the same name)"
    fi
    status=1; kept+=("$b"); continue
  fi

  wt=$(git worktree list --porcelain \
    | awk -v ref="branch refs/heads/$b" '/^worktree /{w=substr($0,10)} $0==ref{print w; exit}')
  if [ -n "$wt" ]; then
    wt_real=$(cd "$wt" 2>/dev/null && pwd -P) || wt_real=$wt
    case "$here/" in
      "$wt_real"/*) refuse "$b" "run from another checkout: the current directory is inside its worktree $wt"; status=1; kept+=("$b"); continue ;;
    esac
    if [ -d "$wt" ]; then
      flags=$(git -C "$wt" ls-files -v) || {
        refuse "$b" "cannot read worktree index"; status=1; kept+=("$b"); continue
      }
      if grep -Eq '^([a-z]|S) ' <<<"$flags"; then
        refuse "$b" "index hides local changes"; status=1; kept+=("$b"); continue
      fi
      changes=$(git -C "$wt" -c core.fsmonitor=false -c core.untrackedCache=false status --porcelain --untracked-files=all --ignored --ignore-submodules=none) || {
        refuse "$b" "cannot read worktree status"; status=1; kept+=("$b"); continue
      }
    else
      changes=""
    fi
    if [ -n "$changes" ]; then
      refuse "$b" "worktree $wt has uncommitted or untracked files (including ignored files)"; status=1; kept+=("$b"); continue
    fi
  fi

  if [ "$(git rev-parse --verify "refs/heads/$b")" != "$tip" ]; then
    refuse "$b" "tip changed during verification"; status=1; kept+=("$b"); continue
  fi
  if [ "$dry_run" = 1 ]; then
    say "would prune $b (PR #$pr merged at ${tip:0:7})${wt:+, removing worktree $wt}"
    pruned+=("$b")
    continue
  fi
  if [ -n "$wt" ] && [ -d "$wt" ]; then
    git worktree remove "$wt" || { refuse "$b" "git worktree remove failed for $wt"; status=1; kept+=("$b"); continue; }
  elif [ -n "$wt" ]; then
    git worktree prune # the directory is already gone; drop its stale record
  fi
  # Compare and delete in one ref transaction. A concurrent commit must survive.
  remaining=$(git worktree list --porcelain) || stop "cannot verify remaining worktrees"
  if grep -Fxq "branch refs/heads/$b" <<<"$remaining"; then
    refuse "$b" "branch is checked out"; status=1; kept+=("$b"); continue
  fi
  git update-ref -d "refs/heads/$b" "$tip" || {
    refuse "$b" "could not delete verified tip"; status=1; kept+=("$b"); continue
  }
  say "pruned $b (PR #$pr merged at ${tip:0:7})${wt:+, worktree $wt removed}"
  pruned+=("$b")
done

# Summary under the output rule. Names are joined with ", " for one readable line each.
join() { local IFS=,; printf '%s' "$*" | sed 's/,/, /g'; }
verb="pruned"; [ "$dry_run" = 0 ] || verb="would prune"
if [ "${#pruned[@]}" -gt 0 ]; then done_line="$verb ${#pruned[@]}: $(join "${pruned[@]}")"; else done_line="nothing pruned"; fi
[ "${#kept[@]}" -eq 0 ] || done_line="$done_line; kept ${#kept[@]}: $(join "${kept[@]}")"
[ "$open" -eq 0 ] || done_line="$done_line; $open without a merged pull request, left alone"
if [ "${#kept[@]}" -gt 0 ]; then
  left="decide each KEEP line above (commit or discard the work, or keep the branch)"
  next="fix what a KEEP line names, then /dev-delete-merged-branches <branch>"
elif [ "$dry_run" = 1 ] && [ "${#pruned[@]}" -gt 0 ]; then
  left="nothing"
  next="/dev-delete-merged-branches $(printf '%s ' "${pruned[@]}" | sed 's/ $//') (without --dry-run)"
else
  left="nothing"
  next="/dev-status"
fi
ending "$done_line" "$left" "$next"
exit "$status"
