@AGENTS.md

## Claude Code only

- Edit hook `validate-json.sh` (PostToolUse) runs `scripts/validate-marketplace.py` automatically after manifest edits.
- Read-only agents, use them instead of ad-hoc checks: `marketplace-consistency-checker`, `new-plugin-quality-reviewer`, `release-notes-drafter` (`.claude/agents/`).
- Slash commands `/bump-plugin` and `/new-plugin-skeleton` live in `.claude/commands/`.
- Skills load from `.claude/skills`, a committed symlink to `../.agents/skills`.
