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


if __name__ == "__main__":
    unittest.main()
