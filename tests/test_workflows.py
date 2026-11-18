"""Structural checks of the workflows that gate a merge or hold a write token.

Text checks, no YAML parser (stdlib only): they read the job ids at two-space
indentation under `jobs:` and a few literal settings. actionlint (in `./dev ci`)
checks the syntax; these check the repository's own contracts. The aggregate's
pass rule is also run, with jq, on the results GitHub would hand it.
"""
import json
import re
import subprocess
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


class AggregateRuleTest(unittest.TestCase):
    """Runs the aggregate's own jq rule, read from validate.yml, on the `needs` results
    GitHub would pass it: a failed or cancelled job must fail the required check.

    GitHub skips a job whose dependency failed, and branch protection counts a skipped
    required check as passing. `if: always()` makes the aggregate run anyway; this rule is
    what then turns a red plugin check into a red `Marketplace validation`. Needs jq on
    the system PATH, as the runner and the guard tests do.
    """

    CORE = ("validate", "changes")

    def setUp(self):
        gate = jobs((WORKFLOWS / "validate.yml").read_text())["gate"]
        self.rule = re.search(r"jq -e '(.*?)'", gate, re.S).group(1)
        self.needs = [n.strip() for n in re.search(r"^    needs: \[(.*)\]$", gate, re.M).group(1).split(",")]

    def gate_passes(self, **results):
        """True when the rule accepts `needs` where every job succeeded except `results`."""
        needs = {job: {"result": results.get(job.replace("-", "_"), "success"), "outputs": {}} for job in self.needs}
        run = subprocess.run(
            ["jq", "-e", self.rule], input=json.dumps(needs), capture_output=True, text=True,
            env={"PATH": "/usr/bin:/bin"}, timeout=30,
        )
        self.assertIn(run.returncode, (0, 1), run.stderr)
        return run.returncode == 0

    def test_every_job_green_passes(self):
        self.assertTrue(self.gate_passes())

    def test_a_failed_or_cancelled_job_fails_the_required_check(self):
        for job in self.needs:
            for result in ("failure", "cancelled"):
                with self.subTest(job=job, result=result):
                    self.assertFalse(self.gate_passes(**{job.replace("-", "_"): result}))

    def test_a_skipped_plugin_or_version_job_passes(self):
        # A plugin job is skipped when its plugin did not change; the version check outside PRs.
        for job in self.needs:
            if job not in self.CORE:
                with self.subTest(job=job):
                    self.assertTrue(self.gate_passes(**{job.replace("-", "_"): "skipped"}))

    def test_a_skipped_core_or_filter_job_fails(self):
        # When the filter fails, GitHub skips every plugin job: the filter must have succeeded.
        for job in self.CORE:
            with self.subTest(job=job):
                self.assertFalse(self.gate_passes(**{job: "skipped"}))

    def test_a_red_plugin_check_blocks_even_when_the_others_were_skipped(self):
        self.assertFalse(self.gate_passes(plugin_organon="failure", plugin_pa_toolkit="skipped", version_bump="skipped"))


class WriteTokenWorkflowTest(unittest.TestCase):
    """release.yml and specs-bump.yml hold a contents-write token: keep it narrow (K8, K11)."""

    def test_release_writes_only_for_a_pushed_tag_on_main(self):
        text = (WORKFLOWS / "release.yml").read_text()
        # Read-only by default: the write token is granted to one job, and only there.
        self.assertRegex(text, r"(?m)^permissions:\n  contents: read$")
        self.assertEqual(len(re.findall(r"contents: write", text)), 1)
        release = jobs(text)["release"]
        self.assertIn("contents: write", release)
        self.assertRegex(release, r"(?m)^    if: github\.ref_type == 'tag'$")
        # A tag on an unmerged commit would run unreviewed code with the token (Codex C1).
        script = release.index("python3 scripts/release-plugins.py")
        self.assertIn('git merge-base --is-ancestor "$GITHUB_SHA" origin/main', release[:script])
        # The tag name reaches the shell through the environment, never by interpolation.
        self.assertNotRegex(release, r"run:[^\n]*\$\{\{")
        self.assertIn('--tag "$TAG"', release)
        # One concurrency group per tag: a shared group cancels a pending run (Codex, PR 97).
        self.assertRegex(text, r"(?m)^  group: release-\$\{\{ github\.ref \}\}$")
        self.assertIn("cancel-in-progress: false", text)
        # The script never creates a tag: PA does (tag ruleset, session 25).
        self.assertNotIn("git push", release)

    def test_release_preview_has_no_write_token_and_runs_from_main(self):
        preview = jobs((WORKFLOWS / "release.yml").read_text())["preview"]
        self.assertNotIn("contents: write", preview)
        self.assertRegex(preview, r"github\.ref == 'refs/heads/main'")
        self.assertIn('git rev-parse --verify --quiet "$BASE^{commit}"', preview)

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
