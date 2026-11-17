# Workaround register

Every workaround the harness carries is an entry here, so that none outlives its reason. An entry has four fields, and `tests/test_register.py` refuses an entry that lacks one or names a probe that does not exist:

- **Reason:** what the workaround compensates for.
- **Exit condition:** the observable fact that makes it removable.
- **Probe:** a script under `tools/probes/` that tests the exit condition. Exit code 0: still needed. 10: the condition is met. 2: inconclusive (agent CLI missing, no network, manual step pending). A probe only reports; it edits nothing.
- **Last result:** date, tool versions, what the probe said, and what was decided.

The `harness-review` skill (`.agents/skills/harness-review/`) runs the probes twice a year on the Mac, because they need the installed agent CLIs and network access to their APIs. The skill proposes; removing a workaround is a normal PR that PA merges. A new workaround is added in the same PR that introduces it. Format, in one line per field, so that the test and the skill can read it: a level-3 heading `### <id>`, then bullets starting with the four field names above in bold.

## Entries

### skills-symlink

- **Reason:** repository skills live in `.agents/skills/` (read by Codex and Antigravity). Claude Code reads `.claude/skills/` only, so `.claude/skills` is one committed directory symlink to `../.agents/skills`.
- **Exit condition:** Claude Code lists skills found under `.agents/skills/` when `.claude/skills` does not exist.
- **Probe:** `tools/probes/skills-symlink.sh`. Builds a throwaway project with and without the symlink and reads the `skills` list of the `system`/`init` event of `claude -p`. The run with the symlink is the control; without it the probe is inconclusive.
- **Last result:** 2026-11-17, Claude Code 2.1.326: not listed without the symlink, listed with it. Still needed. (Session 21 found the same; PA confirmed the symlink in the desktop app and a cloud session.)

### claude-md-stub

- **Reason:** `AGENTS.md` is the canonical instruction file. Claude Code reads `CLAUDE.md`, so `CLAUDE.md` is a stub that imports it with `@AGENTS.md` and adds the Claude-only notes. The stub text and the symlink README come from `harness/templates/`.
- **Exit condition:** Claude Code reads `AGENTS.md` in a project that has no `CLAUDE.md`, and the Claude-only notes have another home (for example `.claude/` settings, commands and agents, which are already separate).
- **Probe:** `tools/probes/claude-md-stub.sh`. Two throwaway projects hold the same `AGENTS.md` (a code word); one has a `CLAUDE.md` that imports it (control). `claude -p` is asked for the code word in each.
- **Last result:** 2026-11-17, Claude Code 2.1.326: the bare project answered the code word, so the condition holds for the CLI on this Mac. One model-answered run, and not yet checked in the desktop app or a cloud session. Decision: keep the stub; propose removal only after a second run and the desktop and cloud checks. The stub also carries the Claude-only notes, which would need a home first.

### plugin-zips

- **Reason:** the Gemini app imports files by hand and accepts skills, not plugins. Each release therefore carries a `<plugin>-v<version>.plugin` zip (built by `scripts/plugin_zip.py`) and one `<skill>.zip` per skill (`--skills`). Gemini refused the `.plugin` zip on 2026-11-17, so the plugin zips serve other hosts and as a reproducible payload; the per-skill zips are the ones Gemini takes.
- **Exit condition:** the Gemini app (or the Gemini CLI or Antigravity) installs a plugin or a skill directly from a git URL, a marketplace entry or a folder, with no hand-imported zip.
- **Probe:** `tools/probes/plugin-zips.sh`. Reports the installed Gemini CLI and Antigravity versions and what their help says about plugins and skills, then prints the manual import steps for the Gemini app. It cannot conclude on its own: it exits 2 until PA records the manual result below.
- **Last result:** 2026-11-17: the Gemini app refused a `.plugin` and accepted a per-skill zip (session 18). Manual probe not re-run since. Still needed.
