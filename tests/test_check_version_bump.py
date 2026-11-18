"""The version-bump check (scripts/check-version-bump.py) in disposable repositories."""
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "check_version_bump", Path(__file__).resolve().parents[1] / "scripts" / "check-version-bump.py")
cvb = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = cvb
SPEC.loader.exec_module(cvb)


def git(repo, *args):
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


class VersionBumpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="check-version-bump-")
        self.repo = Path(self.tmp.name)
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.email", "test@example.invalid")
        git(self.repo, "config", "user.name", "Test")
        self.write_manifest("alpha", "1.0.0", root=True)
        self.write_manifest("beta", "2.0.0", root=False)
        self.write("README.md", "top\n")
        self.base = self.commit("base")
        git(self.repo, "switch", "-q", "-c", "feat")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, path, text):
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def write_manifest(self, name, version, root):
        path = f"plugins/{name}/plugin.json" if root else f"plugins/{name}/.claude-plugin/plugin.json"
        self.write(path, json.dumps({"name": name, "version": version}))

    def commit(self, message):
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", message)
        return git(self.repo, "rev-parse", "HEAD")

    def run_check(self, base=None):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cvb.main(["--base", base or self.base, "--repo", str(self.repo)])
        return code, out.getvalue(), err.getvalue()

    def test_plugin_change_without_bump_fails_and_names_the_plugin(self):
        self.write("plugins/beta/skills/x/SKILL.md", "new\n")
        self.commit("change beta")
        code, _, err = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("plugins/beta changed but its version is still 2.0.0", err)
        self.assertNotIn("alpha", err)

    def test_plugin_change_with_bump_passes(self):
        self.write("plugins/beta/skills/x/SKILL.md", "new\n")
        self.write_manifest("beta", "2.1.0", root=False)
        self.commit("change and bump beta")
        self.assertEqual(self.run_check()[0], 0)

    def test_root_manifest_wins_as_in_release_plugins(self):
        # alpha's version lives in its root plugin.json; a second manifest under
        # .claude-plugin/ with another version does not count as a bump.
        self.write("plugins/alpha/.claude-plugin/plugin.json", json.dumps({"name": "alpha", "version": "9.9.9"}))
        self.commit("add a second alpha manifest")
        code, _, err = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("plugins/alpha changed but its version is still 1.0.0", err)

    def test_each_unbumped_plugin_is_named(self):
        self.write("plugins/alpha/docs.md", "x\n")
        self.write("plugins/beta/docs.md", "x\n")
        self.commit("change both")
        code, _, err = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("plugins/alpha", err)
        self.assertIn("plugins/beta", err)

    def test_changes_outside_plugins_pass(self):
        self.write("README.md", "changed\n")
        self.write("scripts/x.py", "print()\n")
        self.commit("outside plugins")
        self.assertEqual(self.run_check()[0], 0)

    def test_new_and_removed_plugins_pass(self):
        self.write_manifest("gamma", "0.1.0", root=False)
        git(self.repo, "rm", "-q", "-r", "plugins/alpha")
        self.commit("add gamma, remove alpha")
        self.assertEqual(self.run_check()[0], 0)

    def test_base_moved_on_after_the_branch_compares_with_the_merge_base(self):
        # A bump on main after the branch point must not hide this branch's unbumped change.
        self.write("plugins/beta/docs.md", "x\n")
        self.commit("change beta on the branch")
        git(self.repo, "switch", "-q", "main")
        self.write_manifest("beta", "2.0.1", root=False)
        main_tip = self.commit("bump beta on main")
        git(self.repo, "switch", "-q", "feat")
        code, _, err = self.run_check(base=main_tip)
        self.assertEqual(code, 1)
        self.assertIn("plugins/beta changed but its version is still 2.0.0", err)

    def test_unreadable_base_is_an_error(self):
        code, _, err = self.run_check(base="no-such-rev")
        self.assertEqual(code, 2)
        self.assertIn("check-version-bump: FAIL", err)


if __name__ == "__main__":
    unittest.main()
