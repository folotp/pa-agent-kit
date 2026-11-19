---
name: dev-help
description: Lists every dev- command and what waits for you. Groups include core, this repository, plugins, this Mac, used by agents. Run when PA types /dev-help or asks which commands exist.
disable-model-invocation: true
---

# List the dev- commands

The index of every `dev-` command, so PA never has to remember one. It reads skill folders and frontmatter only; it changes nothing and contacts nothing.

`<core>` is `.harness` in a repository that syncs the core and `harness` in the workshop (`pa-agent-kit`); run from the repository root. `<bot>` is your own GitHub App: `claude` in Claude Code, `codex` in Codex, `antigravity` in Antigravity.

## Run

```bash
<core>/commands list
```

`list --check` is the test of the same index (a missing description, a name that differs from its folder, a name defined twice); run it when PA asks whether the commands are in order.

## Relay

Show PA the script's output, then its last three lines (`done:`, `left for PA:`, `next:`) verbatim: they say what happened, what is left for PA and the one next step. Do not paraphrase them or add a next step of your own.

The 'Waiting for you' group holds the offline checks only; `/dev-status` adds what GitHub knows (pull requests, merged branches, draft releases, a newer core).
