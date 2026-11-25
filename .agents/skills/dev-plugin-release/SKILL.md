---
name: dev-plugin-release
description: Prepare the next workshop plugin release step from bump PR through marketplace refresh.
argument-hint: <plugin> [patch|minor|major]
disable-model-invocation: true
compatibility: "Requires the workshop checkout, its pinned tools, and GitHub access. Tagging and publication require owner approval."
---

Run `./dev x python3 -B tools/workshop/plugins.py release <plugin> [patch|minor|major] --bot <bot>` from the workshop. Use `claude` in Claude Code, `codex` in Codex and `antigravity` in Antigravity. Ask for the plugin if absent. If PA requests a new version and omitted the increment, ask which increment when the script reports that a bump is the next step.

Relay the script's last three lines verbatim. If it plans a bump PR, obtain explicit approval before rerunning the same command with `--open-pr <approved-version>`. If it prints an owner command, show it, ask for PA's separate go for that tag push or publication, and stop. PA runs the printed command in their terminal and selects **Allow** once when Keychain asks for the owner token. Run the inspection again after PA confirms completion.
