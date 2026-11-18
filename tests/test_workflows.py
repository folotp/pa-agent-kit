"""Structural checks of the workflows that gate a merge or hold a write token.

Text checks, no YAML parser (stdlib only): they read the job ids at two-space
indentation under `jobs:` and a few literal settings. actionlint (in `./dev ci`)
checks the syntax; these check the repository's own contracts.
"""
import re
import unittest
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
REQUIRED_CONTEXT = "Marketplace validation"


def jobs(text):
    """Return {job id: job body} for the workflow text."""
    body = text.split("\njobs:\n", 1)[1]
    parts = re.split(r"^  ([A-Za-z0-9_-]+):\n", body, flags=re.M)
    return dict(zip(parts[1::2], parts[2::2]))


class ValidateWorkflowTest(unittest.TestCase):
    """validate.yml: one aggregate job is the required context and needs every other job."""

    def setUp(self):
        self.jobs = jobs((WORKFLOWS / "validate.yml").read_text())

    def test_only_the_aggregate_carries_the_required_context(self):
        named = [job for job, body in self.jobs.items() if re.search(rf"^    name: {REQUIRED_CONTEXT}$", body, re.M)]
        self.assertEqual(named, ["gate"])

    def test_the_aggregate_needs_every_other_job_and_always_runs(self):
        gate = self.jobs["gate"]
        needs = re.search(r"^    needs: \[(.*)\]$", gate, re.M).group(1)
        self.assertEqual(sorted(n.strip() for n in needs.split(",")), sorted(j for j in self.jobs if j != "gate"))
        self.assertRegex(gate, r"(?m)^    if: always\(\)$")

    def test_the_aggregate_requires_the_core_and_filter_jobs_to_succeed(self):
        gate = self.jobs["gate"]
        self.assertIn('.validate.result == "success"', gate)
        self.assertIn('.changes.result == "success"', gate)
        self.assertIn('all(. == "success" or . == "skipped")', gate)


class WriteTokenWorkflowTest(unittest.TestCase):
    """release.yml and specs-bump.yml hold a contents-write token: keep it narrow (K8, K11)."""

    def test_release_refuses_a_bad_base_and_write_mode_off_main(self):
        text = (WORKFLOWS / "release.yml").read_text()
        self.assertIn('git rev-parse --verify --quiet "$BASE^{commit}"', text)
        self.assertIn('[ "$GITHUB_REF" = refs/heads/main ]', text)
        self.assertIn('git merge-base --is-ancestor "$GITHUB_SHA" origin/main', text)
        # The refusals come before the script that tags.
        self.assertLess(text.index("refs/heads/main ]"), text.index("scripts/release-plugins.py"))

    def test_specs_bump_keeps_no_credential_and_pushes_the_lock_only(self):
        text = (WORKFLOWS / "specs-bump.yml").read_text()
        self.assertIn("persist-credentials: false", text)
        self.assertNotIn("persist-credentials: true", text)
        steps = text.split("      - name: ")
        # Only the last step names the job token.
        self.assertEqual([s.split("\n", 1)[0] for s in steps if "github.token" in s], ["Open the bump PR"])
        self.assertIn('changed="$(git diff --name-only origin/main...HEAD)"', steps[-1])
        self.assertIn('[ "$changed" = "specs.lock" ]', steps[-1])
        self.assertLess(steps[-1].index('"specs.lock" ]'), steps[-1].index("push origin"))


if __name__ == "__main__":
    unittest.main()
