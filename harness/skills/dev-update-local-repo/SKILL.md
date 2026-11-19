---
name: dev-update-local-repo
description: Pulls main, sets up and deletes merged branches, after merges. Fetch, fast-forward, ./dev setup, prune, and a restart line when agent files changed; refuses, changing nothing, on uncommitted files or local commits GitHub lacks. Run when PA types /dev-update-local-repo.
disable-model-invocation: true
---

# Update the local repository

Wraps the core verb `./dev update-local-repo`, run as the bot so that the fetch and the prune of merged branches use the bot's token. It is idempotent: a second run says "already up to date".

`<core>` is `.harness` in a repository that syncs the core and `harness` in the workshop (`pa-agent-kit`); run from the repository root. `<bot>` is your own GitHub App: `claude` in Claude Code, `codex` in Codex, `antigravity` in Antigravity.

## Run

```bash
<core>/gh-token.sh <bot> -- ./dev update-local-repo
```

It works on the main checkout (the first entry of `git worktree list`) wherever it is run from. `./dev setup` inside it may need to write `.git/config` (the git hooks); the agent sandbox refuses that write, and the verb then names PA's own terminal: relay it.

## Relay

Show PA the script's output, then its last three lines (`done:`, `left for PA:`, `next:`) verbatim: they say what happened, what is left for PA and the one next step. Do not paraphrase them or add a next step of your own.

When `left for PA` asks for a restart, the agent files or plugins changed: PA restarts the session (in Claude Code, `/reload-plugins` is enough for plugins).
