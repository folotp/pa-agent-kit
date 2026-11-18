# PA's Marketplace (`pa-marketplace`)

PA's Marketplace. Hosts plugins for AI agents: Claude through `.claude-plugin/marketplace.json`, and ChatGPT through `.agents/plugins/marketplace.json`, which lists only plugins reviewed as portable. Gemini joins once it supports marketplaces.

## Install

```text
/plugin marketplace add folotp/pa-agent-kit
/plugin install <plugin-name>@pa-marketplace
/reload-plugins
```


Codex: `codex plugin marketplace add folotp/pa-agent-kit`, then `codex plugin add <plugin-name>@pa-marketplace` (only the plugins reviewed as portable are listed). To pin an install to the `stable` tag, see [docs/releases.md](docs/releases.md).

## Plugins

| Plugin | Version | Source | Description |
| --- | --- | --- | --- |
| [`projectionlab`](plugins/projectionlab/) | 0.1.0 | in-repo | Read-only access to ProjectionLab financial plans via the Chrome MCP. |
| [`session-telemetry`](plugins/session-telemetry/) | 0.2.1 | in-repo | Captures a structured snapshot of the current Claude session and appends one NDJSON line to the Organon vault telemetry log via Organon MCP. |
| [`organon`](plugins/organon/) | 1.5.6 | in-repo | Organon vault conventions for Claude — 8 description-triggered skills covering read and write discipline, frontmatter, markdown style, session discipline, Bases, JSON Canvas, and diagramming. |
| [`pa-toolkit`](plugins/pa-toolkit/) | 0.1.4 | in-repo | PA's personal toolkit — decision-gatekeeper agent (triages a proposed change against a domain's decision records, driven by governance profiles in the Organon vault), six fin-* PocketSmith/Rogers skills, and a generalized plugin-release runbook for all of PA's plugins. |

## Plugin sources

Every plugin lives under `plugins/<name>/` of this repository, and both manifests list it by relative path: `"source": "./plugins/<name>"` for Claude Code, `{"source": "local", "path": "./plugins/<name>"}` for Codex. The version lives in the plugin's `plugin.json`; bump it on each meaningful change so users get an Update notification (`/bump-plugin <name> <version>`).

**Single source of truth for version.** Per the [official docs](https://code.claude.com/docs/en/plugin-marketplaces#version-resolution-and-release-channels), Claude Code resolves a plugin's version from the first of these set: `version` in `plugin.json` -> `version` in the marketplace entry -> the source's commit SHA. **Don't set `version` in both `plugin.json` and the marketplace entry** — `plugin.json` always wins silently, so a stale duplicate can mask a real bump. This marketplace keeps `version` in `plugin.json` only.

## Releases

Merging a version bump is the release: see [docs/releases.md](docs/releases.md).

## Layout

```
.claude-plugin/
  marketplace.json          ← marketplace metadata + plugin registry
.agents/plugins/
  marketplace.json          ← Codex registry (portable plugins only)
plugins/                    ← every plugin
  <plugin-name>/
    .claude-plugin/
      plugin.json           ← per-plugin manifest (optional but recommended)
    skills/<skill>/SKILL.md
    commands/<cmd>.md
    agents/<agent>.md
    hooks/hooks.json
README.md
```

Skills, commands, agents, and hooks are auto-discovered from their conventional folders inside each plugin — no explicit declaration in `plugin.json` required.

## Adding a new plugin

1. Create `plugins/<name>/` with at minimum a `skills/<name>/SKILL.md` (or commands/agents/hooks).
2. Create `plugins/<name>/.claude-plugin/plugin.json` with `name`, `version`, `description`, `author`. **The `version` here drives Update detection — bump it on every meaningful change.**
3. Add an entry to `.claude-plugin/marketplace.json` under `plugins[]` with `name`, `source: "./plugins/<name>"`, `description`, `category`, `tags`. Do **not** duplicate `version` here.
4. Use `/bump-plugin <name> <version>` to bump on each release (updates `plugin.json` and the README plugins table).
5. Open a PR; merge it. Re-installation: `/plugin marketplace update pa-marketplace` then `/plugin install <name>@pa-marketplace`.

## License

Private. Not for redistribution.
