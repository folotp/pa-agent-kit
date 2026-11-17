---
name: harness-review
description: Twice-yearly review of the agent harness. Use when the "Harness review due" issue is open, when PA asks for a harness review, or to check whether a workaround (the .claude/skills symlink, the CLAUDE.md stub, the .plugin zips) can go. Runs the workaround probes, reads tool pins, specs.lock and agent release notes, and reports proposals. Proposes only; applies nothing.
---

# Harness review

Reviews the harness twice a year and reports what to keep, change or remove. **It only proposes.** Nothing in this review edits a file, opens a PR, releases a tag or syncs a repository: PA reads the report and approves each proposal, and each approved one then becomes an ordinary branch and PR (a person merges). Run it on the Mac: the probes need the installed agent CLIs and network access to their APIs.

## Pick the mode

- **Workshop mode:** `harness.toml` and `docs/workaround-register.md` exist, and the core is `harness/` (this repository, `pa-agent-kit`).
- **Consumer mode:** the repository has `.harness/` (a synced copy of the core) and no `harness/` directory.
- Neither: stop and say so. Do not guess.

Run `./dev check` first in either mode. If it fails, report that as the first finding and stop: the rest depends on a working toolchain.

## What it reads (both modes)

1. **Tool pins:** `mise.toml` and `mise.lock`. For each pinned tool, compare with the latest release (`mise latest <tool>`, or the tool's release page) and note security fixes. Report the gap; do not bump.
2. **`specs.lock`:** `./dev specs check` (offline) and the date of the last bump PR (`gh pr list --state all --search "specs.lock" --limit 5`). A bump PR left open is a finding.
3. **Agent release notes:** the installed versions (`claude --version`, `codex --version`, `gemini --version`, `agy --version`) and the release notes since the version recorded in the register's last results. Look for: native `AGENTS.md` or `.agents/skills` support, hook changes, plugin or marketplace changes, anything that makes a workaround obsolete or breaks a binding. Fetch only public release-note pages; a page that cannot be read is listed as unread, not assumed unchanged.
4. **The workaround register:** `docs/workaround-register.md`. In consumer mode read the copy in the core release the repository is synced to (the workshop's, via `gh api` or the tag), since the register lives in the workshop.

## Workshop mode

1. **Probes.** For every register entry run its probe (`tools/probes/<id>.sh`; Anthropic API access is needed, and the probes print what they ran). Exit code 0: still needed. 10: the exit condition is met, so propose removal. 2: inconclusive, say why and what PA must do (the `plugin-zips` probe always needs a manual step). Quote the probe's own output, including tool versions, in the report. One model-answered run is thin evidence: for a "can go" result, run the probe a second time before proposing, and name what is not yet checked (desktop app, cloud session, other agents).
2. **The core.** Review `harness/` against the report's aims: does each file still earn its place, is anything duplicated, do the bindings in `harness/bindings/` still match what each agent supports, do the pinned actions in `.github/workflows/` have newer commits. The core is meant to stay small; a growing line count is a finding.
3. **Consumers.** For each repository that syncs the core, compare the synced tag in its `.harness/` with the latest core tag. Report how far behind each is. Only after PA approves a core release, propose `./dev sync <tag>` for each consumer (one PR each); never run it as part of this review.
4. **Register upkeep.** Any workaround the review found that has no register entry is a proposal to add one, with reason, exit condition and a probe.

## Consumer mode

1. `./dev check` already detects a changed `.harness/` file (checksum). A failure is a finding, not something to repair.
2. List the repository's own additions and overrides: files in `harness.toml` `[checks]` and `[verbs]`, the repository's `AGENTS.md` beyond the shared block, local hooks and bindings, workflows.
3. Compare each with the core and sort into three lists: **drifted** (a copy of core text that has diverged), **duplicates** (does what the core already does), **should move up** (generic, would help every consumer). Name file and line for each.
4. The synced tag against the latest core tag, and what the newer tags change.

## The report

Print it in the chat; write no file unless PA asks. Use these sections, in this order, and leave a section in with "nothing found" rather than dropping it:

1. **Summary:** mode, repository, date, `./dev check` result, number of proposals.
2. **Pins:** table of tool, pinned, latest, gap.
3. **Specs:** lock state, last bump, open bump PR.
4. **Agent releases:** per agent, installed version, notable changes, unread pages.
5. **Register:** table of entry, probe result (still needed, can go, inconclusive), evidence in one line, what is not yet checked.
6. **Core or consumer findings** (by mode).
7. **Proposals:** numbered. Each has: what to change, why, the files, the size (trivial or needs a plan), and what PA must approve. Mark any that touch `.github/workflows/` (bots cannot push those; PA releases the push).
8. **Not verified:** everything the review could not check, so silence is never read as a pass.

After PA has read it, record in each register entry's **Last result** the date, versions and decision (in a PR PA approves), and close the review issue with the report's summary.

## Rules

- Never print or log a token or a secret; never open secret files (`.env`, key, credential, state or local settings files).
- No live-system action. The probes use throwaway projects under the temp directory and remove them.
- Do not merge, release, tag or sync as part of the review.
- Keep hostnames, addresses and personal details out of the report if PA pastes it into an issue or PR.
