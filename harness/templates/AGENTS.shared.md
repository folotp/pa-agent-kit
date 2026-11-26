<!-- harness:shared:begin -->
## Shared block

Same text in every repository that uses the harness core; copied from `harness/templates/AGENTS.shared.md` by the core sync. Change it in the core, not here.

- Work on a named feature branch, in a separate worktree per editing agent. Never change another checkout.
- Commit, push and open PRs as your own bot identity; a person merges. Never merge, force-push, push to `main` or release, and never bypass main protection. The guard hook refuses these early; it is a warning, not the boundary.
- Local macOS Codex with per-command approvals: for a GitHub bot scope check, call `exec_command` with `cmd="harness/gh-token.sh codex --read-only --info"`, `workdir` set to the workshop root, `sandbox_permissions="require_escalated"` and a justification naming the operation. Use the same fields on the first call for each wrapped command, e.g. `harness/gh-token.sh codex --read-only -- gh pr view NUMBER`. In a consumer use its root and `.harness/gh-token.sh`. Request only the individual command, without a prefix rule. For an explicitly authorized owner operation use the same fields with `owner -- CMD`; PA approves the separate Keychain prompt. If escalation is unavailable or refused, stop and report it.
- Run `./dev check` before committing and `./dev ci` before pushing. Do not run a bumper or deploy command against real files merely to test it.
- Never open secret files (`.env`, key, state or credential files, local settings); check for patterns only. Never print, log or store a token.
- Keep hostnames, addresses and personal details out of commits, PR text and docs.
- Flag a new dependency before adding it.
- Update code, related docs, examples and tests in the same PR. A reviewer must be able to understand and operate the change without this conversation.
- When PA must act, in a reply, a report or a PR body, end with what happened, what is left for PA and the one exact next step, by its `/dev-` command; `/dev-help` lists them, `.harness/README.md` explains the core; a PA step with no command is reported as a candidate.
- Commands for PA are skills named `dev-<subject>-<action>`; never reuse a core `dev-` name.
- A refusal by the guard, a hook or the gate is final: do not retry it another way; run the command its message names, or tell PA.
- Commit and PR titles follow Conventional Commits.
<!-- harness:shared:end -->
