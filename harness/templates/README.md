# Templates for consumer repositories

Used by `./dev sync`. Each has one authoritative text here; the table says how each one lands in a consumer and whose it is afterwards.

| Template | Lands as | Rule |
|---|---|---|
| `AGENTS.shared.md` | the block between `harness:shared:begin` and `harness:shared:end` in `AGENTS.md` | Replaced as a whole at every sync; everything outside it is kept. `AGENTS.md` is canonical and stays under 24,000 bytes (Antigravity's limit; Codex allows 32 KiB). Depth goes into skills. |
| `AGENTS.md` | `AGENTS.md`, only when absent | A heading, an empty marked block (filled from `AGENTS.shared.md` in the same sync) and a 'This repository' section; then the repository's own file. Without it no shared-block line reaches Codex or Antigravity (24g F1). |
| `CLAUDE.md` | `CLAUDE.md`, only when absent | First line `@AGENTS.md`, then Claude-only notes. Claude Code reads `AGENTS.md` alone only when no `CLAUDE.md` exists, so keep the stub anyway. A kept `CLAUDE.md` without that first line is reported. |
| `dev` | `dev`, only when absent | The entry point; a differing one stops the sync unless kept with `--keep-root`. |
| `dependabot.yml` | `.github/dependabot.yml`, only when the repository has none (`.yml` or `.yaml`) | The workshop's own settings (a test keeps them equal); then the repository's file, which adds its other ecosystems. `./dev check` judges its `github-actions` entry (24g D2). |
| `ci.yml` | never written; reported | The CI skeleton: pinned mise, `./dev setup`, `./dev ci`. The sync reports when no workflow runs `./dev ci`; PA copies it to `.github/workflows/ci.yml` and pushes it (a bot cannot push a workflow file) (24g W6). |
| the skills symlink | `.claude/skills` | Where `.claude/skills` is not a real directory: one committed directory symlink, `mkdir -p .agents/skills .claude && ln -s ../.agents/skills .claude/skills`. Claude Code does not load `.agents/skills/` directly; it follows this link (probe in `docs/harness-core.md`, 'Agent files'). Where `.claude/skills` is a real directory (a repository with its own Claude skills there), the sync links each core skill into it one by one, as relative links into `.harness/skills/`, and `./dev check` verifies them (24i, 24g I7; built with the core skills). |

A symlink cannot be templated as a file, so its command is recorded here and checked by the core sync.
