@AGENTS.md

<context>
Repo: pa-marketplace. Manifest + tooling only — no app runtime, no language toolchain.
Plugin sources: in-repo only (plugins/<name>/), listed by relative path. Version SOT: plugin.json. Merging a version bump is the release.
</context>

<workflow>
Portable plugins are also listed in .agents/plugins/marketplace.json for Codex (source local, same relative path): listing one is a manual review.
Validation: run python3 scripts/validate-marketplace.py before any marketplace.json or README.md commit (no network needed). Edit hook validate-json.sh (PostToolUse) runs it automatically.
Release: release.yml tags <plugin>/v<version> and drafts a release when a plugin's version changes on main (scripts/release-plugins.py, --dry-run). Publishing is manual, after assets are attached.
Agents (read-only): marketplace-consistency-checker · new-plugin-quality-reviewer. Use instead of ad-hoc checks.
</workflow>

<constraints>
Never set version in both plugin.json and marketplace entry — plugin.json wins silently.
Never re-introduce legacy commit field on github sources.
No commit without approval.
No JSON reformat on targeted edits; tags arrays = compact single-line.
</constraints>
