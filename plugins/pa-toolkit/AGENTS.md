# pa-toolkit development contract

<context>
Repo: folotp/pa-toolkit — PA's personal plugin (agents + skills), separate from organon-plugin, which stays vault infrastructure. Distributed via GitHub Release .plugin asset; consumed by folotp/pa-marketplace. Tracked in vault note SD-BL-0066.
No bundled .mcp.json: vault access uses the Organon MCP each surface already provides (claude.ai connector or organon plugin); bundling another would shadow it. Tool prefixes differ by surface (mcp__claude_ai_organon__*, mcp__organon__*), so agents and skills refer to tools by bare name (search_vault_smart) and don't pin `tools:` to one prefix.
</context>

<design>
decision-gatekeeper is domain-agnostic. Domain knowledge lives in each domain's "Profil de gouvernance des décisions" section in the vault, read fresh on every call; adding a domain means writing its profile, not editing this repo. Keep domain rules out of agents/ so the vault stays the single source of truth.
Finance skills are named fin-<tool>-<action>.
</design>

<workflow>
Version SOT: .claude-plugin/plugin.json (semver). .plugin is gitignored; it exists only as a Release asset.
Release: verify the exact release commit is already merged to remote main before tagging. gh release create: --notes-from-tag is incompatible with --repo; use --notes-file.
</workflow>

<constraints>
Work on a branch (feat/ fix/ chore/ perf/ docs/) and merge by PR rather than committing to main, so release tags always point at reviewed commits.
</constraints>

## Code and documentation

Code must explain its own intent through precise names, coherent functions and explicit contracts. Add docstrings or nearby comments for non-obvious inputs/outputs, side effects, failure behavior, invariants and the reasons behind important decisions; do not narrate obvious statements. Complement the code with repository architecture/design documents and operational runbooks. Update code, related docs, examples and tests together in the same PR. Preserve one authoritative implementation of each policy; client adapters refer to it. Documentation is part of completion, not a later task. A reviewer must be able to understand, operate and modify the change without this conversation or private agent memory.

## Shared release infrastructure

Read `skills/plugin-release/references/development.md` for architecture, extension/receipt contracts, tests and CI. The canonical general release procedure is `skills/plugin-release/references/runbook.md`; the Claude executor is an adapter. Run `python3 -m unittest discover -s tests -v` before committing release infrastructure changes. Use one named branch/worktree per editing agent and merge through a PR. Do not publish, tag or change marketplace pins without an authorized release request.

## Development in the workshop

This plugin lives in the `pa-marketplace` workshop (checkout `pa-agent-kit`, `plugins/pa-toolkit/`).
Its development gate is the workshop's, not a script of this plugin: run `./dev check` from the
workshop root before committing and `./dev ci` before pushing (`./dev setup` installs the pinned
tools). The `plugin-pa-toolkit` job of the workshop's `validate.yml` runs this plugin's unit tests
(`python3 -B -m unittest discover -s tests -v` from `plugins/pa-toolkit/`) when the plugin changes;
it is part of the required `Marketplace validation` check. A change under `plugins/pa-toolkit/`
carries a version bump (`scripts/check-version-bump.py`).

The standalone toolkit repository's `scripts/dev` (doctor, check, format, worktree, session,
install-hooks), its `release-checks.yml` workflow and its `docs/` were not carried into the
workshop: this plugin has no `scripts/dev`, and the links to that repository's documents
are historical. Worktree and hook setup now come from the workshop's core
(`docs/harness-core.md`). Do not install the old toolkit's hooks from a transient checkout.

Runtime files are explicitly selected by `config/package-files.json`. Update this
inventory with runtime additions and verify a real archive through the generic
release driver from a clean worktree. This repository's `config/release.json` selects
its shared full gate and runtime package command. The general runbook/driver remains
the only release implementation; require exact merged remote-main identity again
before an authorized tag. Development adapters/configuration/environments never ship.

## Supported development agents

Supported targets are Codex, Claude Code, GitHub Copilot on GitHub.com (cloud agent
and pull-request code review), and Google Antigravity,
plus GitHub Actions CI for deterministic repository validation. Capabilities and
observed test coverage differ by client/surface; consult the
[supported-agent contract](https://github.com/folotp/pa-toolkit/blob/main/docs/supported-agents.md)
and [reusable acceptance plan](https://github.com/folotp/pa-toolkit/blob/main/docs/agent-test-plan.md).
Client files point here; they do not redefine repository policy. Native hooks need
actual delivery evidence and never replace the staged-index/required-CI gates.
