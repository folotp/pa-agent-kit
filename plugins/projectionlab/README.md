# ProjectionLab

Read plan data from a signed-in ProjectionLab session. Use it to review assumptions, compare inputs, or extract projection results.

## Install

In Claude Code:

```text
/plugin marketplace add folotp/pa-agent-kit
/plugin install projectionlab@pa-marketplace
/reload-plugins
```

Requires Claude in Chrome connected to a signed-in ProjectionLab session. This plugin is currently distributed through the Claude catalog. The Codex marketplace lists plugins reviewed for that client.

## Skill

[`projectionlab`](skills/projectionlab/SKILL.md) — Reads plan settings, milestones, income, expenses, account assumptions, withdrawal strategies, and Monte Carlo results.

## Releases

See the [changelog](CHANGELOG.md) and [workshop releases](https://github.com/folotp/pa-agent-kit/releases).

## License

[MIT](LICENSE).
