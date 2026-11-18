# Templates for consumer repositories

Copied into a consumer by `./dev sync`. One authoritative text each; consumers never edit the shared parts.

| Template | Lands as | Rule |
|---|---|---|
| `AGENTS.shared.md` | the block between `harness:shared:begin` and `harness:shared:end` in `AGENTS.md` | Replace the whole marked block; keep everything outside it. `AGENTS.md` is canonical and stays under 24,000 bytes (Antigravity's limit; Codex allows 32 KiB). Depth goes into skills. |
| `CLAUDE.md` | `CLAUDE.md` | First line `@AGENTS.md`, then Claude-only notes. Claude Code reads `AGENTS.md` alone only when no `CLAUDE.md` exists, so keep the stub anyway. |
| the skills symlink | `.claude/skills` | One committed directory symlink: `mkdir -p .agents/skills .claude && ln -s ../.agents/skills .claude/skills`. Claude Code does not load `.agents/skills/` directly; it follows this link (probe in `docs/harness-core.md`, 'Agent files'). Do not put per-skill links or copies in `.claude/skills`. |

A symlink cannot be templated as a file, so its command is recorded here and checked by the core sync.
