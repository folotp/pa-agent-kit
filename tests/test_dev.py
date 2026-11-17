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


def clean_env(**extra):
    """Environment of a hook or scheduled job: minimal PATH, no DEV_UNDER_MISE.

    MISE_* and TMPDIR are passed through so that a sandboxed or relocated mise state still works.
    """
    env = {"HOME": os.environ["HOME"], "PATH": MINIMAL_PATH}
    for name, value in os.environ.items():
        if name.startswith("MISE_") or name == "TMPDIR":
            env[name] = value
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


if __name__ == "__main__":
    unittest.main()
