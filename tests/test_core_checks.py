"""Tests of the core's repository checks that `./dev check` runs (24g D2, F5).

Each check runs from a disposable repository directory, as `./dev check` runs it from a
repository root. The pin check (D1) is tested in tests/test_workflows.py (`PinnedActionsTest`).
"""

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HARNESS = ROOT / "harness"
SHA = "3d3c42e5aac5ba805825da76410c181273ba90b1"
WORKFLOW = f"jobs:\n  a:\n    steps:\n      - uses: actions/checkout@{SHA} # v7.0.1\n"
REMOTE_ACTION = f"runs:\n  using: composite\n  steps:\n    - uses: actions/setup-python@{SHA} # v6.2.0\n"
LOCAL_ONLY_ACTION = "runs:\n  using: composite\n  steps:\n    - uses: ./.github/actions/other\n    - uses: docker://alpine@sha256:" + "a" * 64 + "\n"


def run_check(name, root):
    """Run harness/<name> from `root`; return (exit code, stdout lines)."""
    result = subprocess.run([str(HARNESS / name)], cwd=root, capture_output=True, text=True, timeout=30)
    return result.returncode, result.stdout.splitlines()


def entry(directories='    directory: /\n', cooldown="    cooldown:\n      default-days: 7\n", interval="monthly"):
    return f"  - package-ecosystem: github-actions\n{directories}    schedule:\n      interval: {interval}\n{cooldown}"


class DependabotCheckTest(unittest.TestCase):
    """harness/check-dependabot, variant (a): a github-actions entry with a cooldown of 7 days or
    more that covers every local action calling a remote action; schedule, groups and prefix free."""

    def repo(self, dependabot=None, actions=None, workflows=True, name="dependabot.yml"):
        """A scratch repository: one pinned workflow, the given Dependabot text, local actions."""
        root = Path(tempfile.mkdtemp(prefix="core-checks."))
        self.addCleanup(shutil.rmtree, root, True)
        github = root / ".github"
        github.mkdir()
        if workflows:
            (github / "workflows").mkdir()
            (github / "workflows" / "ci.yml").write_text(WORKFLOW)
        if dependabot is not None:
            (github / name).write_text(dependabot)
        for path, text in (actions or {}).items():
            target = github / "actions" / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        return root

    def check(self, *args, **kwargs):
        return run_check("check-dependabot", self.repo(*args, **kwargs))

    def assertPasses(self, *args, **kwargs):
        self.assertEqual(self.check(*args, **kwargs), (0, []))

    def assertFindings(self, patterns, *args, **kwargs):
        code, lines = self.check(*args, **kwargs)
        self.assertEqual(code, 1, lines)
        self.assertEqual(len(lines), len(patterns), lines)
        for line, pattern in zip(lines, patterns):
            self.assertRegex(line, pattern)

    def test_the_workshop_file_and_the_template_pass_and_agree(self):
        self.assertEqual(run_check("check-dependabot", ROOT), (0, []))
        self.assertPasses((HARNESS / "templates" / "dependabot.yml").read_text())

        def settings(path):
            return [l for l in path.read_text().splitlines() if l.strip() and not l.lstrip().startswith("#")]
        # One home for the defaults: the template is the workshop's own file plus comments.
        self.assertEqual(settings(HARNESS / "templates" / "dependabot.yml"), settings(ROOT / ".github" / "dependabot.yml"))

    def test_no_workflows_passes(self):
        self.assertPasses(None, workflows=False)

    def test_a_missing_file_fails_with_the_template_to_copy(self):
        self.assertFindings([r"^\.github/dependabot\.yml is missing: copy harness/templates/dependabot\.yml there"], None)

    def test_dependabot_yaml_is_read_too(self):
        self.assertPasses("version: 2\nupdates:\n" + entry(), name="dependabot.yaml")

    def test_no_github_actions_entry_fails(self):
        pip = "  - package-ecosystem: pip\n    directory: /\n    schedule:\n      interval: weekly\n"
        self.assertFindings([r"^\.github/dependabot\.yml: no github-actions entry: add the one of harness/templates/dependabot\.yml"],
                            "version: 2\nupdates:\n" + pip)

    def test_cooldown_is_required_and_at_least_seven_days(self):
        self.assertFindings([r"^\.github/dependabot\.yml:3: the github-actions entry has no cooldown"],
                            "version: 2\nupdates:\n" + entry(cooldown=""))
        self.assertFindings([r":3: the github-actions entry has cooldown default-days 3: use 7 or more$"],
                            "version: 2\nupdates:\n" + entry(cooldown="    cooldown:\n      default-days: 3\n"))
        self.assertPasses("version: 2\nupdates:\n" + entry(cooldown="    cooldown:\n      default-days: 14 # two weeks\n"))

    def test_schedule_group_prefix_and_other_ecosystems_are_the_repositorys(self):
        """ha-config's weekly, ungrouped `ci` entry (its ADR-0009) passes; extra ecosystems are not read."""
        text = (
            '---\nversion: 2\nupdates:\n  - package-ecosystem: "github-actions"\n    directory: "/"\n'
            '    schedule:\n      interval: "weekly"\n    cooldown:\n      default-days: 7\n'
            '    commit-message:\n      prefix: "ci"\n'
            "  - package-ecosystem: pip\n    directory: /\n    schedule:\n      interval: daily\n"
        )
        self.assertPasses(text)

    def test_an_uncovered_local_action_with_a_remote_uses_fails(self):
        self.assertFindings(
            [r"^\.github/actions/setup/action\.yml uses a remote action, but no github-actions entry of "
             r"\.github/dependabot\.yml covers /\.github/actions/setup: list it under that entry's 'directories'"],
            "version: 2\nupdates:\n" + entry(), {"setup/action.yml": REMOTE_ACTION})

    def test_a_local_action_with_only_local_uses_needs_no_coverage(self):
        self.assertPasses("version: 2\nupdates:\n" + entry(), {"wrap/action.yml": LOCAL_ONLY_ACTION})

    def test_covered_local_actions_pass(self):
        actions = {"setup/action.yml": REMOTE_ACTION, "deploy/action.yaml": REMOTE_ACTION}
        for directories in (
            '    directories:\n      - "/"\n      - "/.github/actions/*"\n',
            '    directories:\n    - /\n    - /.github/actions/*/\n',  # sequence at the key's indent
            '    directories: ["/", "/.github/actions/setup", "/.github/actions/deploy"]\n',
            "    directories:\n      - /\n      - /.github/**\n",
            "    directories:\n      - '**/*'\n",
        ):
            with self.subTest(directories):
                self.assertPasses("version: 2\nupdates:\n" + entry(directories=directories), actions)

    def test_a_glob_star_stays_within_one_segment(self):
        actions = {"group/setup/action.yml": REMOTE_ACTION}
        self.assertFindings([r"covers /\.github/actions/group/setup:"],
                            "version: 2\nupdates:\n" + entry(directories='    directories:\n      - "/.github/actions/*"\n'), actions)
        self.assertPasses("version: 2\nupdates:\n" + entry(directories='    directories:\n      - "/.github/actions/*/*"\n'), actions)

    def test_every_github_actions_entry_needs_its_cooldown(self):
        two = "version: 2\nupdates:\n" + entry() + "    target-branch: main\n" + entry(cooldown="") + "    target-branch: next\n"
        self.assertFindings([r":10: the github-actions entry has no cooldown"], two)

    def test_findings_are_all_reported_in_one_run(self):
        code, lines = self.check("version: 2\nupdates:\n" + entry(cooldown=""), {"a/action.yml": REMOTE_ACTION, "b/action.yml": REMOTE_ACTION})
        self.assertEqual(code, 1)
        self.assertEqual([bool(re.search(p, l)) for p, l in zip(("no cooldown", "actions/a/", "actions/b/"), lines)], [True] * 3, lines)


class BindingCheckTest(unittest.TestCase):
    """harness/check-bindings (24g F5): each agent's hook file calls the core guard, in the
    consumer layout (`.harness/guard`) and in the workshop (`harness/guard`)."""

    FILES = (".claude/settings.json", ".codex/hooks.json", ".agents/hooks.json")

    def consumer(self):
        """A synced consumer's layout: the check and the bindings under .harness/, no hook file yet."""
        root = Path(tempfile.mkdtemp(prefix="core-bindings."))
        self.addCleanup(shutil.rmtree, root, True)
        (root / ".harness").mkdir()
        shutil.copy2(HARNESS / "check-bindings", root / ".harness" / "check-bindings")
        shutil.copytree(HARNESS / "bindings", root / ".harness" / "bindings")
        return root

    def place(self, root, name, text=None):
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text if text is not None else (HARNESS / "bindings" / name).read_text())

    def run_in(self, root):
        result = subprocess.run([str(root / ".harness" / "check-bindings")], cwd=root, capture_output=True, text=True, timeout=30)
        return result.returncode, result.stdout.splitlines()

    def test_the_workshop_files_pass(self):
        self.assertEqual(run_check("check-bindings", ROOT), (0, []))

    def test_the_core_bindings_pass_in_a_consumer(self):
        root = self.consumer()
        for name in self.FILES:
            self.place(root, name)
        self.assertEqual(self.run_in(root), (0, []))

    def test_a_missing_file_names_the_binding_to_copy(self):
        root = self.consumer()
        for name in self.FILES[1:]:
            self.place(root, name)
        self.assertEqual(self.run_in(root), (1, [".claude/settings.json is missing: copy .harness/bindings/.claude/settings.json there (the core guard hook)"]))

    def test_an_own_settings_file_without_the_guard_fails_with_the_entry_to_merge(self):
        """The live repositories' case: their own .claude/settings.json, kept by the sync."""
        root = self.consumer()
        for name in self.FILES[1:]:
            self.place(root, name)
        own = {"permissions": {"deny": ["Read(.env)"]}, "hooks": {"PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "own-hook.sh"}]}]}}
        self.place(root, ".claude/settings.json", json.dumps(own))
        code, lines = self.run_in(root)
        self.assertEqual(code, 1)
        self.assertEqual(lines, [".claude/settings.json does not call the core guard: merge the PreToolUse entry of "
                                 ".harness/bindings/.claude/settings.json into it (matcher 'Bash', command "
                                 "'\"$CLAUDE_PROJECT_DIR/.harness/guard\" claude')"])
        # Merged next to the repository's own hook: passes.
        own["hooks"]["PreToolUse"][0]["hooks"].append({"type": "command", "command": "\"$CLAUDE_PROJECT_DIR/.harness/guard\" claude"})
        self.place(root, ".claude/settings.json", json.dumps(own))
        self.assertEqual(self.run_in(root), (0, []))

    def test_the_guard_must_be_a_pre_tool_use_hook_with_the_bindings_matcher(self):
        root = self.consumer()
        for name in self.FILES[:2]:
            self.place(root, name)
        command = "\"$(git rev-parse --show-toplevel)/.harness/guard\" antigravity"
        for wrong in (
            {"x": {"PostToolUse": [{"matcher": "run_command", "hooks": [{"command": command}]}]}},
            {"x": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"command": command}]}]}},
            {"x": {"PreToolUse": [{"matcher": "run_command", "hooks": [{"command": command.replace(".harness/", "harness/")}]}]}},
        ):
            with self.subTest(wrong):
                self.place(root, ".agents/hooks.json", json.dumps(wrong))
                code, lines = self.run_in(root)
                self.assertEqual(code, 1)
                self.assertTrue(lines[0].startswith(".agents/hooks.json does not call the core guard"), lines)
        self.place(root, ".agents/hooks.json", "{not json")
        self.assertEqual(self.run_in(root), (1, [".agents/hooks.json is not valid JSON: fix it, then merge the PreToolUse entry of .harness/bindings/.agents/hooks.json"]))

    def test_every_finding_is_reported_in_one_run(self):
        code, lines = self.run_in(self.consumer())
        self.assertEqual(code, 1)
        self.assertEqual([line.split(" ", 1)[0] for line in lines], list(self.FILES))


if __name__ == "__main__":
    unittest.main()
