# pa-toolkit

Pierre-André's personal Claude plugin for Claude Code and Cowork. It holds cross-cutting agents and skills. [`organon-plugin`](https://github.com/folotp/organon-plugin) stays the vault infrastructure (conventions, read/write discipline); this plugin builds on it.

## What it provides

### Agents

- **`decision-gatekeeper`** (sonnet, read-only): before a decision record is written, triages a proposed change against one domain's records and returns one outcome:
  - **(a)** covered by an existing record (quoted);
  - **(b)** new record (working title ≤ 8 words + 2–3 decision drivers, no ID guess — Templater assigns it);
  - **(b′)** supersede an existing record via `Supersede-ADR-template.md`;
  - **(c)** another note type (rule, assumption, runbook, backlog item…);
  - **(d)** operational, proceed.

  It is domain-agnostic. Everything it knows about a domain comes from that domain's **« Profil de gouvernance des décisions »** section in the Organon vault, read fresh on every call. It follows `superseded-by` so it never cites a superseded record, and it stops if a domain has no profile. Current profiles:
  - FIN — `99 - Méta/AI/Claude/Finance Bootstrap.md`
  - SD — `99 - Méta/Système documentaire/ADR/Index — SD-ADR.md`

  **Triggering.** Explicit requests work everywhere: « passe ça au gatekeeper », « est-ce que ça mérite une DEC », "run the decision gatekeeper". In Claude Code it may also trigger proactively on policy-shaped proposals. In Cowork, proactive use happens when the domain profile directs it, as the FIN profile does.

  **Transparency.** A subagent's reply goes only to the session that called it. So the calling session must tell PA it is consulting the gatekeeper and show the output block verbatim. The agent's description and the FIN profile both say so. The block always starts with `decision-gatekeeper — <prefix>`.


### Skills

| Skill | Invocation | Purpose |
| --- | --- | --- |
| `fin-pocketsmith-categorize-amazon` | description-triggered | Categorize/split Amazon transactions from real order contents |
| `fin-pocketsmith-categorize-apple` | description-triggered | Categorize/split APPLE.COM/BILL charges from receipts in Apple Mail |
| `fin-pocketsmith-categorize-netflix` | description-triggered | Split the monthly Netflix charge into its three fixed shares |
| `fin-pocketsmith-categorize-rogers` | description-triggered | Split Rogers wireless charges per line from the invoice |
| `fin-pocketsmith-manage-vacation` | description-triggered | Full vacation lifecycle in PocketSmith (label, categorization, close, Alimentation prorata) |
| `fin-rogers-download-invoice` | description-triggered | Download and archive Rogers invoice PDFs |

The `fin-*` skills were migrated verbatim from PA's account skills. Their MCP tool names are unprefixed. Several depend on Cowork-only tools and will not run in Claude Code:
- `fin-rogers-download-invoice`: `device_bash`, the `~/mnt` mount;
- `fin-pocketsmith-categorize-rogers`: `device_list_dir`;
- `fin-pocketsmith-categorize-amazon`: the built-in browser.

## Install

```text
/plugin marketplace add folotp/pa-marketplace
/plugin install pa-toolkit@pa-marketplace
/reload-plugins
```

Each GitHub Release also carries `pa-toolkit-v<version>.plugin` for a direct install in Cowork.

After installing, remove the account-level copies of the `fin-*` skills so they don't trigger twice.

**Requirements.** The Organon MCP must be available on the surface: the claude.ai connector (`mcp__claude_ai_organon__*`) or the organon plugin's server. There is no bundled `.mcp.json`, because a second server would shadow the one the surface already provides. For the same reason `decision-gatekeeper` refers to vault tools by bare name and doesn't pin `tools:`. The `fin-*` skills also need the PocketSmith MCP.

## Adding a domain to the gatekeeper

Write a section titled « Profil de gouvernance des décisions » in that domain's canonical vault note, following the FIN and SD profiles. It should state:
- the decision prefix, folder and index;
- each neighbouring note type and when to choose it;
- what does and does not warrant a decision, with examples;
- the supersession template.

No change to this repo is needed.

## Releases

From the workshop use `/dev-plugin-release pa-toolkit`. For release steps see the [workshop release guide](../../docs/releases.md).

## Development

Development happens in the `pa-marketplace` workshop. Run `./dev check` from the workshop root
before committing and `./dev ci` before pushing; the `plugin-pa-toolkit` job in the workshop's
`validate.yml` runs this plugin's unit tests when it changes, and a change here needs a version
bump. Development requires no vault/finance connection or AI client. Development
configuration and adapters are excluded from the distributed plugin. The standalone toolkit
repository's `scripts/dev`, `release-checks.yml` and `docs/` did not move with it.

## Layout

```
.claude-plugin/plugin.json      version source of truth (semver)
agents/                         decision-gatekeeper
skills/fin-*/SKILL.md           six finance skills
config/                        runtime inventory and development fixtures
tests/                         development tests
```

Tracked in Organon as SD-BL-0066.

Supported development agents are Codex, Claude Code, GitHub Copilot and Google
Antigravity, with GitHub Actions CI for deterministic checks. See the
[support matrix](https://github.com/folotp/pa-toolkit/blob/main/docs/supported-agents.md)
and [reusable acceptance scenarios](https://github.com/folotp/pa-toolkit/blob/main/docs/agent-test-plan.md).
