---
name: dev-run-with-owner-token
description: Prepares one command for your own GitHub token (the owner token). Use it to push a workflow file, re-run CI, apply a settings batch, archive a repository, publish a draft release. Run when PA types /dev-run-with-owner-token or another command names it.
disable-model-invocation: true
---

# Prepare a command for the owner token

PA's own token is released only by `<core>/gh-token.sh owner -- CMD`, one command at a time, after a Keychain dialog PA answers. An agent never runs it and never sees the token: this skill writes the exact line, and PA runs it in a terminal (in Claude Code, by typing `!` and the line). `<core>/gh-token.md`, 'Owner token', is the reference.

`<core>` is `.harness` in a repository that syncs the core and `harness` in the workshop (`pa-agent-kit`); run from the repository root. `<bot>` is your own GitHub App: `claude` in Claude Code, `codex` in Codex, `antigravity` in Antigravity.

## Pick the recipe

If PA did not say which one, do the read-only part first (find the branch, the run id, the tag), then ask which recipe with the choices below.

| Recipe | Line for PA |
|---|---|
| Push a branch that changes a workflow file (a bot cannot) | `<core>/gh-token.sh owner -- git push origin HEAD:refs/heads/<branch>` |
| Re-run the failed jobs of a CI run | `<core>/gh-token.sh owner -- gh run rerun <run-id> --failed` |
| Publish a draft release once its assets are attached | `<core>/gh-token.sh owner -- gh release edit <tag> --draft=false` (in the workshop, `/dev-plugin-release` does it) |
| Apply a batch of repository settings from a JSON file | `<core>/gh-token.sh owner -- gh api -X PATCH repos/<owner>/<name> --input <file>` |
| Archive a repository | `<core>/gh-token.sh owner -- gh repo archive <owner>/<name> --yes` |
| List PA's repositories | `<core>/gh-token.sh owner -- gh repo list <owner> --limit 100` |
| Check the token works (info) | `<core>/gh-token.sh owner -- gh api user --jq .login` |
| Set up or move the Keychain item (once per Mac) | the commands of `<core>/gh-token.md`, 'Owner token' |

## Relay

Give PA the one line, with the values filled in, and what it will do. After PA runs it, the token script's last three lines (`done:`, `left for PA:`, `next:`) say what happened; relay them verbatim if PA pastes them.
