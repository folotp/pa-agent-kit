---
name: dev-run-ci-locally
description: Runs the repository's checks locally the way CI does: ./dev check before a commit, ./dev ci before a push, and reports what to fix. Use it before every commit and push, when a git hook or CI failed, or when a guard refusal names it after a skipped hook.
metadata:
  audience: agents
---

# Run CI locally

`./dev check` is what the pre-commit hook runs (tools under mise, the core's checksums and hooks, the core checks of pins, Dependabot and guard bindings, then the repository's own offline check). `./dev ci` is that plus every check of `harness.toml`'s `[checks]`, in order: the same command CI runs. Skipping a hook is refused by the guard; this is the way to see and fix what the hook reports.

`<core>` is `.harness` in a repository that syncs the core and `harness` in the workshop (`pa-agent-kit`); run from the repository root. `<bot>` is your own GitHub App: `claude` in Claude Code, `codex` in Codex, `antigravity` in Antigravity.

## Run

```bash
./dev check     # before a commit
./dev ci        # before a push
```

Inside the agent sandbox, mise may be refused its trust or cache writes: the error names a path under mise's state. Run the same command with the sandbox off (it changes nothing outside the checkout), or ask PA to.

## Relay

Show PA the script's output, then its last three lines (`done:`, `left for PA:`, `next:`) verbatim: they say what happened, what is left for PA and the one next step. Do not paraphrase them or add a next step of your own.

Fix what a failing line names and run the command again; never commit or push past a failure.
