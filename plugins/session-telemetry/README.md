# Session Telemetry

Capture a structured snapshot of the active Claude session and append it to an Organon telemetry log.

## Install

In Claude Code:

```text
/plugin marketplace add folotp/pa-agent-kit
/plugin install session-telemetry@pa-marketplace
/reload-plugins
```

Requires an Organon MCP connection with append access to the telemetry log. This plugin is currently distributed through the Claude catalog. The Codex marketplace lists plugins reviewed for that client.

## Skill

[`session-telemetry`](skills/session-telemetry/SKILL.md) — Records session context, tools, MCP activity, skills, and errors as one NDJSON entry.

## Releases

See the [changelog](CHANGELOG.md) and [workshop releases](https://github.com/folotp/pa-agent-kit/releases).

## License

[MIT](LICENSE).
