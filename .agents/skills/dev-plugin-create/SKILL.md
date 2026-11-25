---
name: dev-plugin-create
description: Scaffold a workshop plugin with a manifest, component stub, marketplace entry and README row.
argument-hint: <name>
disable-model-invocation: true
compatibility: "Requires a separate feature worktree of the workshop, Git, and its pinned Python environment."
---

Ask for the plugin identifier, display name, one-line description, category, tags, author name and HTTPS profile URL, license, initial version (default `0.1.0`), and first component (default skills). Tags also seed the manifest keywords. For a skill, collect its environment requirements as compatibility text and load skill-creator before generating the stub.

From a separate feature worktree, pass the approved values to the scaffold command.

```text
./dev x python3 -B tools/workshop/plugins.py create <name> --display-name <name> --description <text> --category <category> --tags <tags> --author-name <name> --author-url <url> --license <license> --compatibility <requirements>
```

Quote each value that contains spaces. For a component other than a skill, use `--component commands|agents|hooks` and omit `--compatibility`. Pass `--version` when using a version other than the default. Add `--dry-run` for a preview. Relay the last three lines verbatim.
