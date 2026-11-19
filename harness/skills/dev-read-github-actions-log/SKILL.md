---
name: dev-read-github-actions-log
description: Reads GitHub Actions logs of a failed check, workflow run or job, as the bot and from inside the agent sandbox (where a plain `gh run view --log` fails), and names the failing step and its error. Use this skill whenever a check is red on a PR, a workflow run failed, CI fails on GitHub but passes locally, or the user asks what an Actions log says, rather than asking PA for a summary. Not for writing, pinning or re-running workflows.
metadata:
  audience: agents
---

# Read a GitHub Actions log

PA wants agents to read the logs themselves rather than hand over summaries. Two things stop `gh run view --log` in the sandbox, and both have a fix that stays inside it:

1. `gh` writes a cache under `~/.cache/gh`, which the sandbox refuses. Set `XDG_CACHE_HOME` to a directory under `$TMPDIR` **inside** the command run through the token wrapper (`GH_CACHE_DIR` is not honoured).
2. The log itself comes from `results-receiver.actions.githubusercontent.com`. Allow exactly that host for the command (in Claude Code's auto mode, its `allowed_domains`). Do not use the `gh api …/jobs/<id>/logs` route: it redirects to a rotating storage host that cannot be allowed narrowly.

`<core>` is `.harness` in a repository that syncs the core and `harness` in the workshop (`pa-agent-kit`); run from the repository root. `<bot>` is your own GitHub App: `claude` in Claude Code, `codex` in Codex, `antigravity` in Antigravity.

## Run

```bash
<core>/gh-token.sh <bot> -- gh pr checks <pr>          # the run and job links
<core>/gh-token.sh <bot> -- bash -c 'export XDG_CACHE_HOME="$TMPDIR/xdgcache"; mkdir -p "$XDG_CACHE_HOME"; gh run view <run-id> --log-failed'
```

Use `--log` for the whole log and `--job <job-id>` for one job. Grep the log for the failing script's own prefix, or for `error`, instead of printing it all.

## Relay

Quote the failing lines and the step they come from, then the fix you propose; the token script's last three lines say whether the token was revoked.
