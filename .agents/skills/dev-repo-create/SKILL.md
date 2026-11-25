---
name: dev-repo-create
description: Prepare a new GitHub repository clone from a released harness with the plain or live settings profile and an owner checklist.
argument-hint: '<checkout> --profile <plain|live> [--dry-run]'
disable-model-invocation: true
compatibility: "Requires the workshop checkout, Git, and its pinned tools. GitHub provisioning requires owner approval and access."
---

Use the workshop checkout. Obtain the absolute path to the new clone and the profile. The operator creates the repository in GitHub and installs the three agent Apps. The checkout must have its GitHub origin set.

For the local and API plan, run `python3 -B ./tools/new-repo/init.py <checkout> --profile <profile> --defer-hooks --dry-run` with the supplied arguments quoted. This plan needs no token. Report any conflicts before asking the operator to approve the settings write.

When the operator approves applying the settings, give them this command for their own terminal. Substitute the absolute workshop checkout and target clone paths and the chosen profile.

```bash
cd "<workshop>" && ./harness/gh-token.sh owner -- python3 -B ./tools/new-repo/init.py "<checkout>" --profile "<profile>" --defer-hooks --apply-settings --yes
```

Use the reported settings read-back and browser checklist. Review the new files and prepare the initial workflow commit under the repository's commit approval rules. Ask separately before the first workflow push. The operator runs it with the owner token from the new clone's terminal. Keep the hooks deferred before that initial push. After it succeeds, rerun the setup without `--defer-hooks` or `--apply-settings` to activate the hooks and run the local checks. Run `/dev-github-settings-check-drift` to verify checks that needed the default branch.
