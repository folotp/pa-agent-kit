@AGENTS.md

## Claude Code only

- Edit hook `.claude/hooks/validate-json.sh` (PostToolUse) runs `scripts/validate-marketplace.py` automatically after manifest edits.
- Read-only agents, use them instead of ad-hoc checks: `marketplace-consistency-checker`, `new-plugin-quality-reviewer`, `release-notes-drafter` (`.claude/agents/`).
- Run `/dev-help` to list the core and workshop commands.
- Skills load from `.claude/skills`, a committed symlink to `../.agents/skills`.
