# gh-token.sh — agent GitHub identities and PA's prompted token

Agents (Claude, Codex, Antigravity) act on GitHub as their own GitHub App, so
their commits, PRs and comments show as `<slug>[bot]`. PA's own token is not
held by any agent shell: it is released through a Keychain prompt, for one
command at a time. Design: harness report §2.3 item 6.

The script is part of the harness core (`harness/gh-token.sh` in `pa-agent-kit`,
`.harness/gh-token.sh` in a repository that syncs the core). It moved here
unchanged from `ha-config/scripts/` in session 20; until each live repository
syncs the core, its own copy stays and works the same way. The examples below
use the `pa-agent-kit` path; any copy of the script serves any repository.

## What each identity can do

| Identity | Rights | Lifetime | Released by |
|---|---|---|---|
| `<app>[bot]` (claude, codex, antigravity) | Contents, Pull requests, Issues: read and write. Actions, Checks, Commit statuses, Dependabot alerts, Code scanning alerts, Code quality: read. No Workflows, no Administration, no Secret scanning alerts, no Actions write | One hour, one repository, revoked when the wrapped command ends | The App key in the Keychain, no prompt |
| PA | Everything PA's token carries (merge, settings, workflow files, direct push to `main`) | The one wrapped command | Keychain prompt on every read |

A bot cannot push a change to `.github/workflows/` (no Workflows permission;
GitHub rejects the push, tested 2026-11-13). Contents write still lets a bot
merge a PR or push to `main` on Free private repositories: agents must not, PA
merges, and the deploy wrapper's "PR merged by PA" check is what keeps such a
commit off the house.

Read back an App's real permissions after any change on its settings page:

```bash
~/Developer/pa-agent-kit/harness/gh-token.sh claude --info
```

## Run a command as an agent

```bash
# Current repository (from the origin remote):
~/Developer/pa-agent-kit/harness/gh-token.sh claude -- git push -u origin my-branch
~/Developer/pa-agent-kit/harness/gh-token.sh claude -- gh pr create --draft --fill

# Another repository:
~/Developer/pa-agent-kit/harness/gh-token.sh claude --repo OWNER/NAME -- gh pr create -R OWNER/NAME --fill
```

The wrapper mints a token for that one repository, sets the bot as git author
and committer, points git and `gh` at the token (stored credentials are
bypassed, `git@github.com:` remotes are rewritten to HTTPS), runs the command,
then revokes the token. The revocation is an exit trap set right after the
token is minted, so a failing command, an error of the script or Ctrl-C revoke
it too; the command's exit status is kept. Commit inside the wrapper so the
commit carries the bot identity:

```bash
~/Developer/pa-agent-kit/harness/gh-token.sh claude -- git commit -m "feat: ..."
```

Other modes:

```bash
gh-token.sh claude --read-only -- ./dev deploy   # every permission narrowed to read: the release gate's call
gh-token.sh claude --info      # expiry, permissions and scope as JSON; the token is revoked, never printed
gh-token.sh claude --print     # prints a one-hour token on stdout, for a tool that needs it raw; not revoked
```

With no mode (`gh-token.sh claude` alone) the script prints its usage and
exits 2: printing a token is asked for by name, never a default (session 24c,
finding K24). Prefer the `--` form: the token never reaches the agent's
transcript. `--read-only` asks GitHub for every permission the installation
holds at level read; `--info --read-only` shows the result.

## Run one command as PA

```bash
~/Developer/pa-agent-kit/harness/gh-token.sh pa -- gh pr merge 123 --squash
```

macOS shows a Keychain prompt. PA clicks **Allow** (never **Always Allow**).
Deny exits non-zero and nothing runs. Agents ask PA before running this form,
naming the exact command; PA answers the prompt.

**Reach of owner mode.** The script exports PA's token (`GH_TOKEN` and the git
credential entries) to the command and to everything that command starts, for
as long as they run. Nothing here narrows or revokes it: it is PA's long-lived
token, so the command must be a single, named operation (`gh pr merge 123`),
never a shell (`bash -c …`) or a tool that runs other code (a build, a test
suite, `./dev`).

## One-time setup (PA)

Agent App keys, one Keychain item each, readable without a prompt:

```bash
security add-generic-password -U -s github-app-key -a claude -T /usr/bin/security \
  -w "$(base64 -i ~/Downloads/<app-slug>.<date>.private-key.pem)"
rm -P ~/Downloads/<app-slug>.<date>.private-key.pem
```

PA's token, prompting on every read (`-T ""`). With no value after `-w`,
`security` asks for the token instead of taking it on the command line:

```bash
security add-generic-password -U -s github-pa-token -a folotp -T "" -w
```

Client IDs are recorded in `app_client_id()` in the script (public values from
each App's settings page).

## Failure behaviour

Errors print the failing step, the HTTP status and GitHub's message, never a
key or a token. Common causes: no Keychain item for the App; the App is not
installed on the repository (HTTP 404 on `/repos/OWNER/NAME/installation`); the
Keychain prompt denied.

## Renewal

App keys do not expire. Rotate one by generating a new key on the App page,
storing it with the same command (`-U` updates the item), then deleting the old
key on GitHub.
