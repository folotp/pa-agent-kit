"""Tests of the core dispatcher (harness/dev).

They run the real script in subprocesses with a hand-built environment, because the suite itself
runs under `mise exec` (DEV_UNDER_MISE is set and PATH is already pinned). They need mise and the
pinned tools: `./dev setup` first. Fixtures are disposable directories; nothing touches the repo.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MINIMAL_PATH = "/usr/bin:/bin"
MISE_LOCATIONS = ("/opt/homebrew/bin/mise", "/usr/local/bin/mise")


def clean_env(hooks="harness/githooks", **extra):
    """Environment of a hook or scheduled job: minimal PATH, no DEV_UNDER_MISE.

    MISE_* and TMPDIR are passed through so that a sandboxed or relocated mise state still works.
    With `hooks`, git sees core.hooksPath = `hooks` through its environment entries, as after
    `./dev setup`, so these tests do not depend on how the clone running them was set up;
    HooksTest covers the hooks themselves, from a fresh clone.
    """
    env = {"HOME": os.environ["HOME"], "PATH": MINIMAL_PATH}
    for name, value in os.environ.items():
        if name.startswith("MISE_") or name == "TMPDIR":
            env[name] = value
    if hooks:
        env.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="core.hooksPath", GIT_CONFIG_VALUE_0=hooks)
    env.update(extra)
    return env


def run_dev(cwd, *args, env=None):
    return subprocess.run(
        [str(Path(cwd) / "dev"), *args],
        cwd=cwd,
        env=env if env is not None else clean_env(),
        capture_output=True,
        text=True,
        timeout=120,
    )


class FixtureRepo:
    """A copy of the dispatcher with its own harness.toml, in a trusted temporary directory."""

    def __init__(self, test, harness_toml):
        self.dir = Path(tempfile.mkdtemp(prefix="dev-test."))
        test.addCleanup(shutil.rmtree, self.dir, True)
        (self.dir / "harness").mkdir()
        shutil.copy2(ROOT / "dev", self.dir / "dev")
        for name in ("dev", "conf.awk", "gate"):
            shutil.copy2(ROOT / "harness" / name, self.dir / "harness" / name)
        for name in ("mise.toml", "mise.lock"):
            shutil.copy2(ROOT / name, self.dir / name)
        (self.dir / "harness.toml").write_text(harness_toml)
        self.env = clean_env(MISE_TRUSTED_CONFIG_PATHS=str(self.dir))


class DispatcherTest(unittest.TestCase):
    def test_check_under_minimal_path_uses_mise_tools(self):
        """The fail-closed path of report 2.4: a hook's PATH still reaches the pinned tools."""
        result = run_dev(ROOT, "check")
        self.assertEqual(result.returncode, 0, result.stderr)
        for tool in ("python3", "shellcheck", "actionlint"):
            line = next(l for l in result.stdout.splitlines() if l.startswith(tool))
            self.assertIn("/installs/", line)
        # Report 2.4: each tool's resolved version, not only its path (Codex C23).
        versions = dict(l.split()[:2] for l in result.stdout.splitlines() if l.split() and l.split()[0] in ("python3", "shellcheck", "actionlint"))
        mise_toml = (ROOT / "mise.toml").read_text()
        for tool, pinned in (("python3", "python"), ("shellcheck", "shellcheck"), ("actionlint", "actionlint")):
            self.assertIn(f'{pinned} = "{versions[tool]}"', mise_toml)

    def test_check_commands_run_with_pipefail(self):
        """Codex C11: a failure early in a pipeline is not hidden by the last command."""
        fixture = FixtureRepo(self, 'profile = "plugin"\ntools = ["python3"]\ncheck = "false | true"\n[checks]\na = "false | true"\n')
        self.assertIn("check failed: false | true", run_dev(fixture.dir, "check", env=fixture.env).stderr)
        self.assertIn("check failed: false | true", run_dev(fixture.dir, "ci", env=fixture.env).stderr)

    def test_x_runs_the_pinned_python(self):
        result = run_dev(ROOT, "x", "python3", "-c", "import sys; print(sys.version_info[:2])")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "(3, 13)")

    def test_preset_marker_does_not_bypass_verification(self):
        env = clean_env(DEV_UNDER_MISE="1")
        result = run_dev(ROOT, "check", env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertRegex(result.stderr, r"resolved outside mise|not found under mise")

    def test_tool_outside_mise_is_refused(self):
        fixture = FixtureRepo(
            self,
            'profile = "plugin"\ntools = ["python3", "ls"]\n[checks]\nnone = "true"\n',
        )
        result = run_dev(fixture.dir, "check", env=fixture.env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ls resolved outside mise", result.stderr)

    def test_ci_runs_checks_in_order_and_stops_at_the_first_failure(self):
        fixture = FixtureRepo(
            self,
            'profile = "plugin"\ntools = ["python3"]\n[checks]\n'
            'first = "echo one"\nsecond = "exit 3"\nthird = "echo three"\n',
        )
        result = run_dev(fixture.dir, "ci", env=fixture.env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("== first", result.stdout)
        self.assertIn("== second", result.stdout)
        self.assertNotIn("== third", result.stdout)
        self.assertIn("check failed: second", result.stderr)
        self.assertNotIn("ci: OK", result.stdout)

    def test_ci_reports_ok_when_every_check_passes(self):
        fixture = FixtureRepo(
            self,
            'profile = "plugin"\ntools = ["python3"]\n[checks]\nfirst = "true"\n',
        )
        result = run_dev(fixture.dir, "ci", env=fixture.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ci: OK", result.stdout)

    def test_unsupported_harness_toml_is_refused(self):
        cases = {
            "unsupported table": 'profile = "plugin"\ntools = ["python3"]\n[other]\n',
            "unknown key": 'profile = "plugin"\ntools = ["python3"]\nextra = "x"\n',
            "unsupported value": 'profile = "plugin"\ntools = ["python3"]\n[checks]\na = 3\n',
            "unsupported line": 'profile = "plugin"\nnot toml\n',
            "a check is a string": 'profile = "plugin"\ntools = ["python3"]\n[checks]\na = ["x"]\n',
            # Codex C12: nothing that would silently drop or split a check.
            "blank value: a": 'profile = "plugin"\ntools = ["python3"]\n[checks]\na = "  "\n',
            "blank array item, or whitespace in one: tools": 'profile = "plugin"\ntools = ["python3", ""]\n',
            "or whitespace in one: tools": 'profile = "plugin"\ntools = ["python3", "a b"]\n',
            "key given twice: a": 'profile = "plugin"\ntools = ["python3"]\n[checks]\na = "true"\na = "false"\n',
        }
        for message, text in cases.items():
            with self.subTest(message):
                fixture = FixtureRepo(self, text)
                result = run_dev(fixture.dir, "check", env=fixture.env)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)

    def test_missing_profile_and_tools_are_refused(self):
        for text, message in (
            ('tools = ["python3"]\n', "profile is missing"),
            ('profile = "plugin"\n', "tools is empty"),
        ):
            with self.subTest(message):
                fixture = FixtureRepo(self, text)
                result = run_dev(fixture.dir, "check", env=fixture.env)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)

    def test_unknown_verb_prints_usage(self):
        result = run_dev(ROOT, "frobnicate")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("usage: ./dev setup | check | ci | gate [<sha>] | apply|deploy", result.stderr)

    @unittest.skipIf(
        any(os.access(p, os.X_OK) for p in MISE_LOCATIONS),
        "mise is installed in a location the dispatcher searches",
    )
    def test_missing_mise_is_a_one_line_refusal(self):
        home = Path(tempfile.mkdtemp(prefix="dev-home."))
        self.addCleanup(shutil.rmtree, home, True)
        result = run_dev(ROOT, "check", env={"HOME": str(home), "PATH": MINIMAL_PATH})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("mise not found", result.stderr)


class VerbsAndCheckTest(unittest.TestCase):
    """The repository's own verbs ([verbs]) and its offline `check` command (harness.toml)."""

    HEAD = 'profile = "plugin"\ntools = ["python3"]\n'

    def test_verb_runs_under_mise_and_receives_its_arguments_verbatim(self):
        fixture = FixtureRepo(
            self, self.HEAD + '[checks]\nnone = "true"\n[verbs]\nshow = "printf \'<%s>\'"\n'
        )
        result = run_dev(fixture.dir, "show", "a b", "$HOME;x", env=fixture.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "<a b><$HOME;x>")

    def test_verb_exit_status_is_the_commands(self):
        fixture = FixtureRepo(self, self.HEAD + '[verbs]\nfail = "exit 7"\n')
        self.assertEqual(run_dev(fixture.dir, "fail", env=fixture.env).returncode, 7)

    def test_undeclared_verb_prints_usage(self):
        fixture = FixtureRepo(self, self.HEAD + '[verbs]\nshow = "true"\n')
        result = run_dev(fixture.dir, "other", env=fixture.env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("usage: ./dev", result.stderr)

    def test_reserved_verb_names_and_non_strings_are_refused(self):
        for text, message in (
            (self.HEAD + '[verbs]\nci = "true"\n', "verb name is reserved: ci"),
            (self.HEAD + '[verbs]\nx = "true"\n', "verb name is reserved: x"),
            (self.HEAD + '[verbs]\nfoo = ["a"]\n', "a verb is a string"),
        ):
            with self.subTest(message):
                fixture = FixtureRepo(self, text)
                result = run_dev(fixture.dir, "check", env=fixture.env)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)

    def test_check_runs_the_repository_command_and_fails_with_it(self):
        ok = FixtureRepo(self, self.HEAD + 'check = "echo OFFLINE-CHECK-RAN"\n')
        result = run_dev(ok.dir, "check", env=ok.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("OFFLINE-CHECK-RAN", result.stdout)
        bad = FixtureRepo(self, self.HEAD + 'check = "exit 5"\n')
        result = run_dev(bad.dir, "check", env=bad.env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("check failed: exit 5", result.stderr)

    def test_ci_runs_the_check_command_before_the_checks(self):
        fixture = FixtureRepo(
            self, self.HEAD + 'check = "echo OFFLINE-CHECK-RAN"\n[checks]\nfirst = "echo one"\n'
        )
        result = run_dev(fixture.dir, "ci", env=fixture.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(result.stdout.index("OFFLINE-CHECK-RAN"), result.stdout.index("== first"))


class HooksTest(unittest.TestCase):
    """The core's git hooks (finding K14), from a fresh clone: `./dev check` names `./dev setup`
    until it ran; setup sets core.hooksPath; pre-commit runs `./dev check`; pre-push refuses main
    and master, then runs the repository's own `.githooks/pre-push` with the same ref lines."""

    def git(self, cwd, *args, check=True):
        return subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-C", str(cwd), *args],
            env=self.env, capture_output=True, text=True, timeout=120, check=check,
        )

    def setUp(self):
        source = FixtureRepo(self, 'profile = "plugin"\ntools = ["python3"]\ncheck = "echo CHECK-RAN"\n')
        shutil.copytree(ROOT / "harness" / "githooks", source.dir / "harness" / "githooks")
        own = source.dir / ".githooks" / "pre-push"
        own.parent.mkdir()
        own.write_text('#!/bin/sh\ncat >"$(git rev-parse --show-toplevel)/../own-hook.out"\n')
        own.chmod(0o755)
        self.dir = Path(tempfile.mkdtemp(prefix="dev-hooks."))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.clone = self.dir / "clone"
        self.env = clean_env(hooks=False, MISE_TRUSTED_CONFIG_PATHS=f"{source.dir}:{self.clone}")
        self.git(source.dir, "init", "-q", "-b", "main")
        self.git(source.dir, "add", "-A")
        self.git(source.dir, "commit", "-q", "-m", "fixture")
        self.git(self.dir, "clone", "-q", "--bare", str(source.dir), str(self.dir / "origin.git"))
        self.git(self.dir, "clone", "-q", str(self.dir / "origin.git"), str(self.clone))

    def test_fresh_clone_check_names_setup(self):
        result = run_dev(self.clone, "check", env=self.env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("git hooks are not the core's (core.hooksPath is 'unset', not 'harness/githooks'): run ./dev setup", result.stderr)

    def test_setup_installs_the_hooks_and_they_run(self):
        result = run_dev(self.clone, "setup", env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("hooks        harness/githooks", result.stdout)
        self.assertEqual(self.git(self.clone, "config", "--get", "core.hooksPath").stdout.strip(), "harness/githooks")
        (self.clone / "a.txt").write_text("a\n")
        self.git(self.clone, "add", "a.txt")
        commit = self.git(self.clone, "commit", "-m", "change")
        self.assertIn("CHECK-RAN", commit.stdout + commit.stderr)
        for branch in ("main", "master"):
            with self.subTest(branch):
                push = self.git(self.clone, "push", "origin", f"HEAD:refs/heads/{branch}", check=False)
                self.assertNotEqual(push.returncode, 0)
                self.assertIn(f"pre-push: refused: push to {branch}", push.stderr)
        self.assertFalse((self.dir / "own-hook.out").exists())
        push = self.git(self.clone, "push", "origin", "HEAD:refs/heads/feature", check=False)
        self.assertEqual(push.returncode, 0, push.stderr)
        self.assertIn("refs/heads/feature", (self.dir / "own-hook.out").read_text())

    def test_check_refuses_hooks_pointing_elsewhere(self):
        self.git(self.clone, "config", "core.hooksPath", "/elsewhere/hooks")
        result = run_dev(self.clone, "check", env=self.env)
        self.assertIn("core.hooksPath is '/elsewhere/hooks'", result.stderr)


if __name__ == "__main__":
    unittest.main()
