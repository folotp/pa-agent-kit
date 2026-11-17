# Marketplace development contract

This file is the canonical instruction file for every agent working in this repository (Claude Code, Codex, Antigravity). `CLAUDE.md` is a one-line import of it plus Claude-only notes; do not copy rules into it. Keep this file under 24,000 bytes (Antigravity's limit; Codex's is 32 KiB): put depth in skills under `.agents/skills/` and in `docs/`.

<!-- harness:shared:begin -->
## Shared block

Same text in every repository that uses the harness core; template in `harness/templates/AGENTS.shared.md`. Change it in the core, not here.

- Work on a named feature branch, in a separate worktree per editing agent. Never change another checkout.
- Commit, push and open PRs as your own bot identity; a person merges. Never merge, force-push, push to `main` or release, and never bypass main protection. The guard hook refuses these early; it is a warning, not the boundary.
- Run `./dev check` before committing and `./dev ci` before pushing. Do not run a bumper or deploy command against real files merely to test it.
- Never open secret files (`.env`, key, state or credential files, local settings); check for patterns only. Never print, log or store a token.
- Keep hostnames, addresses and personal details out of commits, PR text and docs.
- Flag a new dependency before adding it.
- Update code, related docs, examples and tests in the same PR. A reviewer must be able to understand and operate the change without this conversation.
<!-- harness:shared:end -->

## This repository

Repo: pa-marketplace (checkout `pa-agent-kit`). Manifest and tooling only: no app runtime, no language toolchain. Read `docs/protected-main.md` for automation architecture, validation, CI and recovery, and `docs/harness-core.md` for the core contract. No vault access is needed for development checks.

Use `./dev ci` for automation changes: it runs the unit tests, the online `scripts/validate-marketplace.py`, shellcheck and actionlint under the pinned tools of `mise.toml` (`./dev setup` installs them).

### Plugins and release

- Plugin sources are in-repo only (`plugins/<name>/`), listed by relative path. Version source of truth: `plugin.json`. Merging a version bump is the release.
- Never set `version` in both `plugin.json` and the marketplace entry: `plugin.json` wins silently.
- Never re-introduce the legacy `commit` field on github sources.
- Portable plugins are also listed in `.agents/plugins/marketplace.json` for Codex (source local, same relative path); listing one is a manual review.
- `release.yml` tags `<plugin>/v<version>` and drafts a release when a plugin's version changes on `main` (`scripts/release-plugins.py`, `--dry-run`). Publishing is manual, after assets are attached.
- Do not run the bumper against actual manifests merely to test it: use disposable fixtures or an explicitly authorized pin update.

### Validation

- Run `python3 scripts/validate-marketplace.py` before any `marketplace.json` or `README.md` commit (no network needed).
- No JSON reformat on targeted edits; `tags` arrays stay compact on a single line.

### Authorization

No commit without approval. No automatic merge, force push, bypass of main protection or plugin release is authorized by a documentation task.

## Code and documentation

Code must explain its own intent through precise names, coherent functions and explicit contracts. Add docstrings or nearby comments for non-obvious inputs/outputs, side effects, failure behavior, invariants and the reasons behind important decisions; do not narrate obvious statements. Complement the code with repository architecture/design documents and operational runbooks. Preserve one authoritative implementation of each policy; client adapters refer to it. Documentation is part of completion, not a later task.
