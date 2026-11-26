# Marketplace development contract

This file is the canonical instruction file for every agent working in this repository (Claude Code, Codex, Antigravity). `CLAUDE.md` is a one-line import of it plus Claude-only notes; do not copy rules into it. Keep this file under 24,000 bytes (Antigravity's limit; Codex's is 32 KiB): put depth in skills under `.agents/skills/` and in `docs/`.

<!-- harness:shared:begin -->
## Shared block

Same text in every repository that uses the harness core; copied from `harness/templates/AGENTS.shared.md` by the core sync. Change it in the core, not here.

- Work on a named feature branch, in a separate worktree per editing agent. Never change another checkout.
- Commit, push and open PRs as your own bot identity; a person merges. Never merge, force-push, push to `main` or release, and never bypass main protection. The guard hook refuses these early; it is a warning, not the boundary.
- Local macOS Codex with per-command approvals: for a GitHub bot scope check, call `exec_command` with `cmd="harness/gh-token.sh codex --read-only --info"`, `workdir` set to the workshop root, `sandbox_permissions="require_escalated"` and a justification naming the operation. Use the same fields on the first call for each wrapped command, e.g. `harness/gh-token.sh codex --read-only -- gh pr view NUMBER`. In a consumer use its root and `.harness/gh-token.sh`. Request only the individual command, without a prefix rule. For an explicitly authorized owner operation use the same fields with `owner -- CMD`; PA approves the separate Keychain prompt. If escalation is unavailable or refused, stop and report it.
- Run `./dev check` before committing and `./dev ci` before pushing. Do not run a bumper or deploy command against real files merely to test it.
- Never open secret files (`.env`, key, state or credential files, local settings); check for patterns only. Never print, log or store a token.
- Keep hostnames, addresses and personal details out of commits, PR text and docs.
- Flag a new dependency before adding it.
- Update code, related docs, examples and tests in the same PR. A reviewer must be able to understand and operate the change without this conversation.
- When PA must act, in a reply, a report or a PR body, end with what happened, what is left for PA and the one exact next step, by its `/dev-` command; `/dev-help` lists them, `.harness/README.md` explains the core; a PA step with no command is reported as a candidate.
- Commands for PA are skills named `dev-<subject>-<action>`; never reuse a core `dev-` name.
- A refusal by the guard, a hook or the gate is final: do not retry it another way; run the command its message names, or tell PA.
- Commit and PR titles follow Conventional Commits.
<!-- harness:shared:end -->

## This repository

Repo: pa-marketplace (checkout `pa-agent-kit`). Manifest and tooling only: no app runtime, no language toolchain. Read `docs/protected-main.md` for automation architecture, validation, CI and recovery, and `docs/harness-core.md` for the core contract. No vault access is needed for development checks.

Use `/dev-help` for the workshop command index. Use `./dev ci` for automation changes: it runs the unit tests, the online `scripts/validate-marketplace.py`, shellcheck and actionlint under the pinned tools of `mise.toml` (`./dev setup` installs them).

### Plugins and release

- Plugin sources are in-repo only (`plugins/<name>/`), listed by relative path. Version source of truth: `plugin.json`. Merging a version bump is the release.
- Never set `version` in both `plugin.json` and the marketplace entry: `plugin.json` wins silently.
- Never re-introduce the legacy `commit` field on github sources.
- Portable plugins are also listed in `.agents/plugins/marketplace.json` for Codex (source local, same relative path); listing one is a manual review.
- Use `/dev-plugin-create` to scaffold a listed plugin. Use `/dev-plugin-release` to plan a bump PR, prepare the owner-token tag push and prepare publication after the workflow uploads the assets. See `docs/releases.md`.
- Do not run the bumper against actual manifests merely to test it: use disposable fixtures or an explicitly authorized pin update.

### Validation

- Run `./dev x python3 scripts/validate-marketplace.py` before any `marketplace.json` or `README.md` commit (no network needed).
- No JSON reformat on targeted edits; `tags` arrays stay compact on a single line.

### Authorization

No commit without approval. No automatic merge, force push, bypass of main protection or plugin release is authorized by a documentation task.

## Code and documentation

Code must explain its own intent through precise names, coherent functions and explicit contracts. Add docstrings or nearby comments for non-obvious inputs/outputs, side effects, failure behavior, invariants and the reasons behind important decisions; do not narrate obvious statements. Complement the code with repository architecture/design documents and operational runbooks. Preserve one authoritative implementation of each policy; client adapters refer to it. Documentation is part of completion, not a later task.
