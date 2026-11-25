---
name: dev-harness-review
description: Review workshop harness pins, agent releases and workaround probes when the twice-yearly review is due or PA asks for it.
argument-hint: '[--dry-run]'
---

Run `./dev x python3 -B tools/workshop/harness_review.py` from the workshop checkout on the Mac. Pass `--dry-run` for a list of probes and stop after relaying the last three lines. If the workshop check fails, use its diagnostic as the first finding and stop.

For a full review, use the script's versions and probe results with `mise.toml`, `mise.lock`, `specs.lock` and `docs/workaround-register.md`. Read the latest specs bump PR and public agent release notes since the versions in the register. Review core size and duplication, client hook bindings, pinned Actions, and the consumer versions relative to the latest core tag. Does GitHub's Dependabot supported-ecosystems page list mise as generally available (not beta)? If so, propose replacing the mise-bump job with a `mise` entry in `dependabot.yml`. Report unread sources and inconclusive probes.

For repository settings, use `/dev-github-settings-check-drift` to compare the read-back with the workshop’s [settings baseline](../../../tools/new-repo/baseline.json), and include the browser checklist findings.

Report the summary, pins, specs, agent releases, register results, core and consumer findings, numbered proposals and verification limits. For each proposal give the reason, files, size and required approval. Capture versions and decisive output. A probe that twice meets its exit condition supports a proposal for removal. Record other observations as findings. Relay the script's last three lines.

Keep the review read-only. PA decides which proposals become PRs. After approval, include register updates with the corresponding work and close the due issue with the review summary.
