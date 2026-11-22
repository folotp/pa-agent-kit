"""Structural checks of the workflows that gate a merge or hold a write token.

Text checks, no YAML parser (stdlib only): they read the job ids at two-space
indentation under `jobs:` and a few literal settings. actionlint (in `./dev ci`)
checks the syntax; these check the repository's own contracts. The aggregate's
pass rule is also run, with jq, on the results GitHub would hand it.
"""
import json
import re
import subprocess
import tempfile
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


class MiseBumpTemplateTest(unittest.TestCase):
    """harness/templates/mise-bump.yml (session 29d): the job that moves the mise pins, because
    Dependabot cannot update mise.toml or mise.lock. The workshop's own .github/workflows copy is
    the template byte for byte; a live repository copies the template as its own workflow. These
    hold the token discipline of specs-bump.yml (K11) and the contracts found by probing mise."""

    ROOT = Path(__file__).resolve().parents[1]
    TEMPLATE = ROOT / "harness" / "templates" / "mise-bump.yml"

    def setUp(self):
        self.text = self.TEMPLATE.read_text()
        self.job = jobs(self.text)["bump"]
        self.steps = self.job.split("      - name: ")

    def test_the_workshop_runs_the_template_unchanged(self):
        self.assertEqual((WORKFLOWS / "mise-bump.yml").read_text(), self.text)

    def test_every_mise_pin_of_the_workshop_is_the_same(self):
        files = [
            WORKFLOWS / "validate.yml",
            WORKFLOWS / "specs-bump.yml",
            WORKFLOWS / "mise-bump.yml",
            self.ROOT / "harness" / "templates" / "ci.yml",
            self.TEMPLATE,
        ]
        for key in ("MISE_VERSION", "MISE_SHA256"):
            pattern = re.compile(rf"^\s+{key}: (\S+)$", re.M)
            values = {path.name: pattern.search(path.read_text()).group(1) for path in files}
            with self.subTest(key):
                self.assertEqual(len(set(values.values())), 1, values)

    def test_the_minimum_mise_version_has_the_flags_the_job_uses(self):
        # `--vulnerable` and `mise audit` arrived in 2026.11.12; 2026.11.9 has neither.
        pinned = re.search(r"MISE_VERSION: v(\S+)", self.job).group(1)
        minimum = re.search(r'^min_version = "([^"]+)"', (self.ROOT / "mise.toml").read_text(), re.M).group(1)
        as_tuple = lambda v: tuple(int(p) for p in v.split("."))
        self.assertGreaterEqual(as_tuple(minimum), (2026, 11, 12))
        self.assertGreaterEqual(as_tuple(pinned), as_tuple(minimum))

    def test_no_permission_at_the_top_and_write_only_on_the_one_job(self):
        self.assertIn("\npermissions: {}\n", self.text)
        self.assertEqual(list(jobs(self.text)), ["bump"])
        self.assertEqual(len(re.findall(r"contents: write", self.text)), 1)
        self.assertIn("    permissions:\n      contents: write", self.job)
        self.assertRegex(self.job, r"\n    timeout-minutes: \d+\n")

    def test_it_never_runs_on_pull_request_target_or_workflow_run(self):
        self.assertNotRegex(self.text, r"(?m)^\s+(pull_request_target|workflow_run):")

    def test_both_kinds_are_scheduled_off_the_other_scheduled_jobs(self):
        crons = re.findall(r'- cron: "([^"]+)"', self.text)
        self.assertEqual(crons, ["23 5 8 * *", "41 7 * * 3"])
        # specs-bump.yml runs Mondays 06:17 UTC; harness-review-due.yml on the 1st.
        self.assertNotIn("17 6 * * 1", crons)
        self.assertIn("options: [version, security]", self.text)

    def test_the_credential_is_never_kept_and_only_the_last_step_names_the_token(self):
        self.assertIn("persist-credentials: false", self.text)
        self.assertNotIn("persist-credentials: true", self.text)
        self.assertEqual([s.split("\n", 1)[0] for s in self.steps if "github.token" in s], ["Open the bump PR"])
        self.assertTrue(self.steps[-1].startswith("Open the bump PR"))
        self.assertNotRegex(self.job, r"run:[^\n]*\$\{\{")

    def test_the_branch_may_carry_the_pins_and_nothing_else_and_is_checked_before_the_push(self):
        last = self.steps[-1]
        self.assertIn('changed="$(git diff --name-only "origin/$DEFAULT_BRANCH...HEAD")"', last)
        self.assertIn(r"^(mise\.toml|mise\.lock|\.mise/locks/.+)$", last)
        self.assertLess(last.index(r"\.mise/locks/.+"), last.index("push origin"))
        self.assertLess(last.index("git commit"), last.index(r"\.mise/locks/.+"))

    def test_one_open_pr_per_kind_and_the_prefixes(self):
        last = self.steps[-1]
        self.assertIn('prefix="mise-bump"', last)
        self.assertIn('prefix="mise-security"', last)
        self.assertLess(last.index("gh pr list --state open"), last.index("git switch -c"))

    def test_the_pins_are_upgraded_before_the_lock_is_installed_again(self):
        names = [s.split("\n", 1)[0] for s in self.steps[1:]]
        self.assertLess(names.index("Install pinned tools"), names.index("Upgrade the pins"))
        self.assertLess(names.index("Upgrade the pins"), names.index("Install from the new lock"))
        self.assertLess(names.index("Install from the new lock"), names.index("Open the bump PR"))
        self.assertIn("run: ./dev setup", self.steps[names.index("Install from the new lock") + 1])

    def test_the_upgrade_uses_what_the_probe_of_mise_found(self):
        upgrade = next(s for s in self.steps if s.startswith("Upgrade the pins"))
        # `--bump` writes versions the locked setting would refuse, for this one command only.
        self.assertIn("export MISE_LOCKED=0", upgrade)
        self.assertLess(upgrade.index("export MISE_LOCKED=0"), upgrade.index("mise upgrade --bump"))
        self.assertIn("unset MISE_LOCKED", upgrade)
        self.assertIn("--minimum-release-age 7d", upgrade)
        self.assertIn("--vulnerable", upgrade)
        # Runtimes stay on their line (python major.minor, node major) instead of crossing it.
        self.assertIn("--exclude python --exclude node", upgrade)
        self.assertIn('lines+=("python@$python_line")', upgrade)
        self.assertIn('lines+=("node@$node_line")', upgrade)
        self.assertIn("--bump --pin", upgrade)
        # A release-age hold lowered a newer pin in mise 2026.11.9: refuse any downgrade.
        self.assertIn("an older version", upgrade)

    def test_the_security_kind_has_no_release_age_hold(self):
        upgrade = next(s for s in self.steps if s.startswith("Upgrade the pins"))
        security = upgrade[upgrade.index('if [ "$KIND" = security ]'):upgrade.index("export MISE_LOCKED=0")]
        self.assertIn("flags=(--vulnerable)", security)
        self.assertNotIn("minimum-release-age", security.split("else")[0])

    def test_nothing_is_downloaded_into_the_checkout(self):
        # The job stages the whole tree (`git add -A`) and then allows three paths: a binary left
        # in the repository root would fail every run before the push (Codex review of PR 107).
        install = next(s for s in self.steps if s.startswith("Install pinned mise"))
        self.assertIn('-o "$RUNNER_TEMP/mise"', install)
        self.assertNotRegex(install, r"curl [^\n]*-o mise\b")
        self.assertIn('install -m 0755 "$RUNNER_TEMP/mise"', install)

    def test_the_mise_binary_is_reported_and_never_edited(self):
        check = next(s for s in self.steps if s.startswith("Check the pinned mise binary"))
        self.assertIn("api.github.com/repos/jdx/mise/releases", check)
        self.assertIn("7 days ago", check)
        self.assertNotIn("github.token", check)
        self.assertNotRegex(self.job, r"(?m)^\s+(sed -i|git add [^\n]*\.github)")

    def test_its_actions_pass_the_pin_check(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / ".github" / "workflows" / "mise-bump.yml"
            target.parent.mkdir(parents=True)
            target.write_text(self.text)
            self.assertEqual(check_pins(root), (0, ""))


CHECK_PINS = Path(__file__).resolve().parents[1] / "harness" / "check-pins"
SHA = "3d3c42e5aac5ba805825da76410c181273ba90b1"
REFUSAL = "is not pinned: use the full commit SHA with a # vX.Y.Z comment"


def check_pins(root):
    """Run the core pin check (harness/check-pins, 24g D1) from `root`; return (exit code, stdout)."""
    result = subprocess.run([str(CHECK_PINS)], cwd=root, capture_output=True, text=True, timeout=30)
    return result.returncode, result.stdout


class CiTemplateTest(unittest.TestCase):
    """harness/templates/ci.yml (24g W6): the consumers' CI skeleton. Never written by the sync;
    actionlint reads it through harness.toml's check, these hold its contracts."""

    TEMPLATE = Path(__file__).resolve().parents[1] / "harness" / "templates" / "ci.yml"

    def setUp(self):
        self.text = self.TEMPLATE.read_text()
        self.job = jobs(self.text)["checks"]

    def test_mise_is_pinned_exactly_as_in_the_workshop(self):
        workshop = jobs((WORKFLOWS / "validate.yml").read_text())["validate"]
        for key in ("MISE_VERSION", "MISE_SHA256"):
            with self.subTest(key):
                pattern = re.compile(rf"^\s+{key}: (\S+)$", re.M)
                self.assertEqual(pattern.search(self.job).group(1), pattern.search(workshop).group(1))

    def test_one_job_with_no_write_permission_and_no_kept_credential(self):
        self.assertEqual(list(jobs(self.text)), ["checks"])
        self.assertIn("\npermissions: {}\n", self.text)
        self.assertIn("    permissions:\n      contents: read\n", self.job)
        self.assertIn("persist-credentials: false", self.job)
        self.assertRegex(self.job, r"\n    timeout-minutes: \d+\n")
        self.assertIn("    name: Core checks\n", self.job)

    def test_it_runs_setup_then_ci(self):
        self.assertLess(self.job.index("run: ./dev setup"), self.job.index("run: ./dev ci"))

    def test_its_actions_pass_the_pin_check(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / ".github" / "workflows" / "ci.yml"
            target.parent.mkdir(parents=True)
            target.write_text(self.text)
            self.assertEqual(check_pins(root), (0, ""))

    def test_it_describes_the_aggregate_pattern(self):
        for needle in ("if: always()", "needs: [", "needs.*.result"):
            self.assertIn(needle, self.text)


class PinnedActionsTest(unittest.TestCase):
    """The core check harness/check-pins, the one implementation of the pin rule: every `uses:`
    names a full commit SHA, because a tag or branch can be moved to other code, and the
    repository setting 'Require actions to be pinned to a full-length commit SHA' fails such a
    job only at run time. `./dev check` runs it; Dependabot (`.github/dependabot.yml`) moves the pins."""

    def unpinned(self, text, path=".github/workflows/w.yml"):
        """The values check-pins refuses in one file holding `text`, in a scratch repository."""
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / path
            target.parent.mkdir(parents=True)
            target.write_text(text)
            code, out = check_pins(root)
        values = [line.split(": ", 1)[1].rsplit(f" {REFUSAL}", 1)[0] for line in out.splitlines()]
        self.assertEqual(code, 1 if values else 0, out)
        for line in out.splitlines():
            self.assertTrue(line.startswith(f"{path}:") and line.endswith(REFUSAL), line)
        return values

    def test_every_workflow_action_of_this_repository_is_pinned(self):
        self.assertEqual(check_pins(WORKFLOWS.parent.parent), (0, ""))

    def test_no_github_directory_passes(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(check_pins(root), (0, ""))

    def test_the_check_tells_a_pin_from_a_movable_reference(self):
        digest = "a" * 64
        self.assertEqual(self.unpinned(f"      - uses: actions/checkout@{SHA} # v7.0.1\n"), [])
        self.assertEqual(self.unpinned(f"        uses: actions/checkout@{SHA}\n"), [])
        self.assertEqual(self.unpinned("      - uses: ./.github/actions/local\n"), [])
        self.assertEqual(self.unpinned(f"      - uses: docker://alpine@sha256:{digest}\n"), [])
        self.assertEqual(self.unpinned("      # - uses: actions/checkout@v4\n"), [])
        self.assertEqual(self.unpinned("      - uses: actions/checkout@v4\n"), ["actions/checkout@v4"])
        self.assertEqual(self.unpinned("      - uses: actions/checkout@main # latest\n"), ["actions/checkout@main"])
        self.assertEqual(self.unpinned("      - uses: docker://alpine:3.20\n"), ["docker://alpine:3.20"])
        self.assertEqual(self.unpinned(f"      - uses: docker://alpine@sha256:{digest[:63]}\n"), [f"docker://alpine@sha256:{digest[:63]}"])
        # A short or truncated SHA can be ambiguous or moved by a new object: refused.
        self.assertEqual(self.unpinned(f"      - uses: actions/checkout@{SHA[:39]}\n"), [f"actions/checkout@{SHA[:39]}"])
        self.assertEqual(self.unpinned(f"      - uses: actions/checkout@{SHA}0\n"), [f"actions/checkout@{SHA}0"])
        self.assertEqual(self.unpinned(f"      - uses: actions/checkout@{SHA.upper()}\n"), [f"actions/checkout@{SHA.upper()}"])
        self.assertEqual(self.unpinned("      - uses:\n"), [""])

    def test_quotes_are_stripped(self):
        self.assertEqual(self.unpinned(f'      - uses: "actions/checkout@{SHA}" # v7.0.1\n'), [])
        self.assertEqual(self.unpinned(f"      - uses: 'actions/checkout@{SHA}'\n"), [])
        self.assertEqual(self.unpinned('      - uses: "actions/checkout@v4"\n'), ["actions/checkout@v4"])

    def test_flow_and_quoted_keys_are_checked(self):
        self.assertEqual(self.unpinned('jobs: {ci: {steps: [{"uses": org/action@main}]}}\n'), ["org/action@main"])

    def test_a_reusable_workflow_at_job_level_is_judged(self):
        text = (
            "jobs:\n"
            f"  pinned:\n    uses: octo/org/.github/workflows/ci.yml@{SHA} # v1.0.0\n"
            "  local:\n    uses: ./.github/workflows/local.yml\n"
            "  moving:\n    uses: octo/org/.github/workflows/ci.yml@main\n"
        )
        self.assertEqual(self.unpinned(text), ["octo/org/.github/workflows/ci.yml@main"])

    def test_a_local_composite_action_is_read(self):
        text = "runs:\n  using: composite\n  steps:\n    - uses: actions/setup-python@v6\n"
        self.assertEqual(self.unpinned(text, ".github/actions/setup/action.yml"), ["actions/setup-python@v6"])
        self.assertEqual(self.unpinned(text, ".github/actions/nested/deep/action.yaml"), ["actions/setup-python@v6"])
        # Only workflows and action files are read.
        self.assertEqual(self.unpinned(text, ".github/actions/setup/README.yml"), [])

    def test_line_numbers_point_at_the_value(self):
        with tempfile.TemporaryDirectory() as root:
            workflow = Path(root) / ".github" / "workflows" / "ci.yaml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(f"jobs:\n  a:\n    steps:\n      - uses: actions/checkout@{SHA}\n      - uses: actions/cache@v4\n")
            code, out = check_pins(root)
        self.assertEqual((code, out), (1, f".github/workflows/ci.yaml:5: actions/cache@v4 {REFUSAL}\n"))


if __name__ == "__main__":
    unittest.main()
