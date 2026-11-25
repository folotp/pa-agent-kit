---
name: dev-github-settings-check-drift
description: Read GitHub repository settings against the workshop baseline and list browser checks with their pages and expected values.
argument-hint: '<owner/repo> --profile <plain|live> [--dry-run]'
disable-model-invocation: true
---

Use the workshop checkout. Collect the repository and its profile. If its CI check name differs from the starter, include the repository's existing check name as `--required-check "<name>"`.

Give the operator the read-only command for their terminal, substituting the absolute workshop path and actual values. They release the owner token for this one read.

```bash
cd "<workshop>" && ./harness/gh-token.sh owner -- python3 -B ./tools/new-repo/settings.py check "<owner/repo>" --profile "<profile>"
```

For an offline plan, omit the token wrapper and add `--dry-run`. Relay the returned differences and browser checklist. Exit 1 indicates verified drift. Exit 2 indicates an error that needs diagnosis.
