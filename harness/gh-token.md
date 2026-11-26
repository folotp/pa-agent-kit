# gh-token.sh — agent GitHub identities and PA's prompted token

Agents (Claude, Codex, Antigravity) act on GitHub as their own GitHub App, so
their commits, PRs and comments show as `<slug>[bot]`. PA's own token (the
owner token) is not held by any agent shell: it is released through a Keychain
prompt, for one command at a time. Design: harness report §2.3 item 6.

The script is part of the harness core. The examples below run from the root of
a repository that syncs the core, where it is `.harness/gh-token.sh`; in the
workshop (`pa-agent-kit`) the same script is `harness/gh-token.sh`. It moved
from `ha-config/scripts/` in session 20; until each live repository syncs the
core, its own copy stays (with the old `pa` mode).

## What each identity can do

| Identity | Rights | Lifetime | Released by |
|---|---|---|---|
| `<app>[bot]` (claude, codex, antigravity) | Contents, Pull requests, Issues: read and write. Actions, Checks, Commit statuses, Dependabot alerts, Code scanning alerts, Code quality: read. No Workflows, no Administration, no Secret scanning alerts, no Actions write | One hour, one repository, revoked when the wrapped command ends | The App key in the Keychain, no prompt |
| owner (PA) | Everything PA's token carries (merge, settings, workflow files, direct push to `main`) | The one wrapped command | Keychain prompt on every read |

A bot cannot push a change to `.github/workflows/` (no Workflows permission;
GitHub rejects the push, tested 2026-11-13). Contents write still lets a bot
merge a PR or push to `main` on Free private repositories: agents must not, PA
merges, and the guard refuses both early.

Read back an App's real permissions after any change on its settings page:

```bash
.harness/gh-token.sh claude --info
```

## Run a command as an agent

One command per call; a push and a PR creation are two calls.

```bash
# Current repository (from the origin remote):
.harness/gh-token.sh claude -- git commit -m "feat: ..."
.harness/gh-token.sh claude -- git push origin HEAD:refs/heads/<branch>
.harness/gh-token.sh claude -- gh pr create --draft --base main --head <branch> --fill

# Another repository:
.harness/gh-token.sh claude --repo OWNER/NAME -- gh pr create -R OWNER/NAME --draft --fill

# Several steps under one token:
.harness/gh-token.sh claude -- bash -c '…'
```

Push with the explicit refspec, not `git push -u`: `-u` writes the upstream
into `.git/config`, which the agent sandbox refuses. Commit inside the wrapper,
so that the commit carries the bot identity.

The wrapper mints a token for that one repository, sets the bot as git author
and committer, points git and `gh` at the token (stored credentials are
bypassed, `git@github.com:` remotes are rewritten to HTTPS), runs the command,
then revokes the token. The revocation is an exit trap set right after the
token is minted, so a failing command, an error of the script or Ctrl-C revoke
it too; the command's exit status is kept.

Other modes:

```bash
.harness/gh-token.sh claude --read-only -- ./dev deploy   # every permission narrowed to read: the release gate's call
.harness/gh-token.sh claude --info      # expiry, permissions and scope as JSON; the token is revoked, never printed
.harness/gh-token.sh claude --print     # prints a one-hour token on stdout, for a tool that needs it raw; not revoked
```

With no mode (`gh-token.sh claude` alone) the script prints its usage and
exits 2: printing a token is asked for by name, never a default (session 24c,
finding K24). Prefer the `--` form: the token never reaches the agent's
transcript. `--read-only` asks GitHub for every permission the installation
holds at level read; `--info --read-only` shows the result.

## Cleanup after a merge

PA merges with a squash, so the local branch never looks merged to git, and the
guard refuses `git branch -D`. Use `/dev-delete-merged-branches`: it runs

```bash
.harness/gh-token.sh claude -- .harness/git-prune-merged.sh <branch>
```

which deletes the local branch (and its worktree, when clean) only when GitHub
shows a merged PR from that branch whose last commit is exactly the local tip.

## Run one command as the owner

```bash
.harness/gh-token.sh owner -- gh pr merge 123 --squash
```

`/dev-run-with-owner-token` holds the recipes. macOS shows a Keychain dialog
for `github-owner-token`. PA clicks **Allow** (never **Always Allow**). A
failed value read exits 1 before the command starts. Agents ask PA before running
this form, naming the exact command and why; local Codex requests per-command escalation as described in the shared block of `AGENTS.md`. PA answers the dialog.

**Reach of owner mode.** The script exports PA's token (`GH_TOKEN` and the git
credential entries) to the command and to everything that command starts, for
as long as they run. Nothing here narrows or revokes it: it is PA's long-lived
token, so the command must be a single, named operation (`gh pr merge 123`),
never a shell (`bash -c …`) or a tool that runs other code (a build, a test
suite, `./dev`).

The mode was called `pa` until session 24h; `gh-token.sh pa -- …` is now
refused with one line naming `owner`.

## Owner token

The owner token lives in the Keychain item `github-owner-token` (account
`folotp`), created so that every read prompts (`-T ""`). For initial setup, PA runs this command once in Terminal; with no value after `-w`, `security` prompts for the
token, which never shows:

```bash
security add-generic-password -U -s github-owner-token -a folotp -T "" -w
```

**Moving from the old owner item.** PA performs the migration in a private terminal. Keep the old item and its GitHub credential available throughout verification.

1. Create a replacement credential on GitHub with the approved owner scope. Enter it at the hidden prompt of the command above. Supply the value only at that prompt.
2. Run `harness/gh-token.sh owner -- gh api user --jq .login` in the workshop. Choose **Allow** once. Verify the expected owner login. Repeat the read and verify that it prompts again. In the GitHub credential settings, compare the replacement’s repository selection and granted permissions with the approved owner prerequisite. An identity read alone verifies only the login. If either check fails, keep the old credential and repair the new item's account, access controls or scope.
3. After verification, retire the old credential on GitHub and remove the old item in Keychain Access. Keep the verified `github-owner-token` item.

## One-time setup of the App keys (PA)

Agent App keys, one Keychain item each, readable without a prompt:

```bash
security add-generic-password -U -s github-app-key -a claude -T /usr/bin/security \
  -w "$(base64 -i ~/Downloads/<app-slug>.<date>.private-key.pem)"
rm -P ~/Downloads/<app-slug>.<date>.private-key.pem
```

Client IDs are recorded in `app_client_id()` in the script (public values from
each App's settings page).

## Failure behaviour

A failed App key read triggers one metadata lookup for the same account. Owner
mode checks metadata first and requests the value only when the item is visible.
A lookup failure reports the shell exit statuses and suppresses Keychain output.
A failed metadata lookup describes what this process can see. Compare the
metadata-only Terminal command in the error before considering any item change.
If metadata succeeds but the value read fails, check access to that specific
item. For owner mode, establish whether PA saw and approved the one-time prompt.

Local Codex uses the per-command approval recipe in the shared block of
`AGENTS.md`. If the wrapper ran in the default sandbox and the item was
invisible, request escalation once for the same authorized operation. If it
already ran with escalation, report both lookup results. A tool approval
refusal happens before the wrapper starts. Leave the working credential in place.

GitHub API failures report the request, HTTP status and GitHub message. For
example, HTTP 404 on the repository installation lookup can indicate the App
is not installed on that repository.

## Renewal

App keys do not expire. Rotate one by generating a new key on the App page,
storing it with the same command (`-U` updates the item), then deleting the old
key on GitHub. The owner token is renewed the same way: the prompting command
of 'Owner token' with `-U` replaces the value.
