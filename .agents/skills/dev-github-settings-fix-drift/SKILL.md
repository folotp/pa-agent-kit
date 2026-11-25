---
name: dev-github-settings-fix-drift
description: Prepare an owner-approved reconciliation of GitHub settings against the workshop baseline and verify the result by reading it back.
argument-hint: '<owner/repo> --profile <plain|live>'
disable-model-invocation: true
compatibility: "Requires the workshop checkout and GitHub CLI. Applying changes requires owner approval and access."
---

Run `/dev-github-settings-check-drift` first and summarize the drift. Get explicit approval for the settings write on that repository. Use the profile and any required check name selected for the read.

Give the operator the command for their own terminal, substituting the absolute workshop path and actual values.

```bash
cd "<workshop>" && ./harness/gh-token.sh owner -- python3 -B ./tools/new-repo/settings.py apply "<owner/repo>" --profile "<profile>" --yes
```

Relay the settings read-back and browser checklist. If a write fails partway, get a fresh read with `/dev-github-settings-check-drift` before asking for another write. CODEOWNERS changes use an ordinary pull request.
