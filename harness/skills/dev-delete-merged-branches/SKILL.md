---
name: dev-delete-merged-branches
description: Deletes local branches whose pull request GitHub shows as merged at the local tip, with their clean worktrees. Use it after a PR is merged, to clean up a squash-merged branch, or whenever a forced branch delete is refused by the guard: it is the sanctioned way, and the only one, to delete a merged branch.
metadata:
  audience: agents
---

# Delete merged branches

Every repository squash-merges, so git never sees a merged branch as merged and only a forced delete removes it. The guard refuses a forced delete from agents because it cannot tell merged work from unmerged work. The prune script is the narrow way through: it deletes a branch (and its worktree) only when GitHub shows a merged pull request whose last commit is exactly the local tip, and the worktree has nothing uncommitted or untracked. It never deletes `main`, `master` or a name in `harness.toml`'s `protected_branches`, and never touches the branch on GitHub.

`<core>` is `.harness` in a repository that syncs the core and `harness` in the workshop (`pa-agent-kit`); run from the repository root. `<bot>` is your own GitHub App: `claude` in Claude Code, `codex` in Codex, `antigravity` in Antigravity.

## Run

From the main checkout, never from inside the worktree being removed:

```bash
<core>/gh-token.sh <bot> -- <core>/git-prune-merged.sh <branch>…
<core>/gh-token.sh <bot> -- <core>/git-prune-merged.sh --all      # every local branch; open ones are skipped
```

Add `--dry-run` to see what would go without deleting anything. Without a branch name from PA, use `--all`.

## Relay

Show PA the script's output, then its last three lines (`done:`, `left for PA:`, `next:`) verbatim: they say what happened, what is left for PA and the one next step. Do not paraphrase them or add a next step of your own.

A `KEEP` line is a refusal with its reason (commits after the merge, uncommitted files, no merged PR). It is final: do not delete that branch another way; tell PA what the line says.
