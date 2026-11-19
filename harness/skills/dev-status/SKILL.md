---
name: dev-status
description: Shows what waits for you, each item with its command. PRs to merge or mark ready, merged branches to delete, main behind GitHub, hooks not installed, draft releases, a newer core, gh logged in. Run when PA types /dev-status.
disable-model-invocation: true
---

# What waits for PA

Reads local state and, as the bot, GitHub's; changes nothing.

`<core>` is `.harness` in a repository that syncs the core and `harness` in the workshop (`pa-agent-kit`); run from the repository root. `<bot>` is your own GitHub App: `claude` in Claude Code, `codex` in Codex, `antigravity` in Antigravity.

## Run

```bash
<core>/gh-token.sh <bot> -- <core>/commands next --online
```

The token is the bot's ordinary one, not `--read-only`: GitHub shows draft releases only to a token that may write. The command itself only reads (`gh pr list`, `gh release list`, the prune script's `--all --dry-run`, `git ls-remote` of the public workshop). If the token cannot be minted (no Keychain item for the bot, a denied dialog), run `<core>/commands next --online` without a token to report verified local items and the incomplete online check.

## Relay

Show PA the script's output, then its last three lines (`done:`, `left for PA:`, `next:`) verbatim: they say what happened, what is left for PA and the one next step. Do not paraphrase them or add a next step of your own.

Never act on an item yourself: each is PA's to decide (a merge, a ready, a release are PA's; the guard refuses them to agents).
