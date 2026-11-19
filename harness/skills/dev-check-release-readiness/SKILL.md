---
name: dev-check-release-readiness
description: Says whether this commit can be released, with the exact next line. Runs the release gate's read-only checks (clean tree, tip of main, CI green, PR merged by PA and first-parent history). Run when PA types /dev-check-release-readiness or asks whether a deploy or apply may go.
disable-model-invocation: true
---

# Check release readiness

Wraps `./dev gate [<sha>]`: the read-only checks of the release gate (`<core>/gate`). It uses the current agent’s read-only bot wrapper and releases nothing; the release itself (`./dev apply` or `./dev deploy`) is PA's, in PA's own terminal.

`<core>` is `.harness` in a repository that syncs the core and `harness` in the workshop (`pa-agent-kit`); run from the repository root. `<bot>` is your own GitHub App: `claude` in Claude Code, `codex` in Codex, `antigravity` in Antigravity.

## Run

```bash
<core>/gh-token.sh <bot> --read-only -- ./dev gate
<core>/gh-token.sh <bot> --read-only -- ./dev gate <sha>
```

A repository without a `[gate]` table in `harness.toml` (the workshop) has no gate: the command says so; relay that.

## Relay

Show PA the script's output, then its last three lines (`done:`, `left for PA:`, `next:`) verbatim: they say what happened, what is left for PA and the one next step. Do not paraphrase them or add a next step of your own.

Historical mode verifies CI and the PR merger for the named commit. HEAD mode also checks the tree, current tip and first-parent changes since the baseline. The guarded diff and confirmation happen during release. After a successful HEAD assessment, its `next:` line is the release command for PA to run; never run it yourself (the guard refuses it to agents).
