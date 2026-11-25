# Set up a repository from the workshop

Use `plain` for a standalone repository and `live` for a repository in front of a live system. The [settings baseline](../tools/new-repo/baseline.json) records the desired values and their sources.

1. **Create and clone the repository.** Create it in GitHub with the intended visibility. Leave the README, license and ignore file initialization unchecked. Under account settings, add it to the Claude Code, Codex and Antigravity App installations. Clone it using the repository-scoped App access and keep the absolute clone path.

2. **Plan and apply the baseline.** Run `/dev-repo-create` in the workshop with the clone path and profile. The dry run lists the files and API calls. Review the plan and run the owner command prepared by the skill in your terminal. Choose **Allow** once in Keychain. This installs the released core and starter files, applies settings that differ, reads them back, and prints the browser checklist. Branch protection and rulesets require a supporting plan for private repositories. Where branch protection is available, confirm the up-to-date requirement when creating the rule.

3. **Approve the initial workflow push separately.** Have the agent validate the scaffold in a disposable copy and prepare an initial commit on a local bootstrap branch. Check that the commit contains the CI workflow, mise bump workflow and CODEOWNERS. With hooks still deferred in the new clone, run the exact owner push command provided by `/dev-repo-create` in your terminal. Confirm that the command names the approved commit and targets the new default branch.

4. **Activate hooks and verify main.** Have the agent fetch `main`, verify its exact commit and CODEOWNERS, then rerun the local setup from `/dev-repo-create` with hook activation enabled. Use `/dev-github-settings-check-drift` for the owner read-back after the first push. Complete the printed browser checklist and confirm the initial CI run is green. For `live`, fill in the gate fields and verify the scoped credential prompt before using the release verb.

5. **Open the first bot PR.** Have the agent change an ordinary file on a named branch, run `/dev-run-ci-locally`, and open a draft PR with the bot identity. Confirm **Core checks** passes. When a later mise bump PR has a held run, use **Approve and run** in that PR's checks. The owner reviews and merges.
