---
name: dev-plugin-create
description: Scaffold a workshop plugin with a manifest, component stub, marketplace entry and README row.
argument-hint: <name>
disable-model-invocation: true
---

Ask for any missing choices together. Collect name, one-line description, category, comma-separated tags, version (default `0.1.0`) and first component (skills, commands, agents or hooks, default skills). Before creating a skills stub, load skill-creator and use it to validate the result.

From a separate feature worktree run `python3 -B tools/workshop/plugins.py create <name> --description <text> --category <category> --tags <tags> --version <version> --component <component>` with the supplied values as quoted arguments. Omit flags whose defaults were accepted. For a safe trial, add `--dry-run`. Relay the script's last three lines verbatim.
