"""tag-release.py in disposable repositories: a bare directory stands in for GitHub, no network."""
import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "tag_release", Path(__file__).resolve().parents[1] / "scripts" / "tag-release.py")
tr = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = tr
SPEC.loader.exec_module(tr)


def git(repo, *args):
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


class TagReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="tag-release-")
        root = Path(self.tmp.name)
        self.remote = root / "remote.git"
        self.repo = root / "work"
        git(root, "init", "-q", "--bare", "-b", "main", str(self.remote))
        git(root, "clone", "-q", str(self.remote), str(self.repo))
        git(self.repo, "config", "user.email", "test@example.invalid")
        git(self.repo, "config", "user.name", "Test")
        (self.repo / ".claude-plugin").mkdir()
        manifest = {"plugins": [{"name": "alpha", "source": "./plugins/alpha"},
                                {"name": "beta", "source": "./plugins/beta"}]}
        (self.repo / ".claude-plugin/marketplace.json").write_text(json.dumps(manifest))
        self.write("alpha", "1.0.0")
        self.write("beta", "2.0.0")
        self.commit("base")
        git(self.repo, "push", "-q", "origin", "HEAD:main")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, version):
        path = self.repo / "plugins" / name / ".claude-plugin/plugin.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"name": name, "version": version}))

    def commit(self, message):
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", message)
        return git(self.repo, "rev-parse", "HEAD")

    def merge(self, message):
        """Commit the working tree and publish it as the remote's main."""
        sha = self.commit(message)
        git(self.repo, "push", "-q", "origin", "HEAD:main")
        return sha

    def run_main(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            status = tr.main(list(argv), repo=self.repo)
        return status, out.getvalue()

    def remote_tags(self):
        return git(self.remote, "tag", "--list").split()

    def test_tags_the_bump_commit_on_the_remote_without_a_local_tag(self):
        self.write("alpha", "1.1.0")
        bump = self.merge("bump alpha")
        status, out = self.run_main("alpha")
        self.assertEqual(status, 0, out)
        self.assertEqual(self.remote_tags(), ["alpha/v1.1.0"])
        self.assertEqual(git(self.remote, "rev-parse", "alpha/v1.1.0^{commit}"), bump)
        self.assertEqual(git(self.repo, "tag", "--list", "alpha/v1.1.0"), "", "no local tag is created")

    def test_tags_the_bump_not_main_tip_when_another_plugin_merged_after(self):
        self.write("alpha", "1.1.0")
        bump = self.merge("bump alpha")
        (self.repo / "plugins/beta/notes.txt").write_text("x")
        self.write("beta", "2.1.0")
        self.merge("bump beta")
        status, out = self.run_main("alpha")
        self.assertEqual(status, 0, out)
        self.assertEqual(git(self.remote, "rev-parse", "alpha/v1.1.0^{commit}"), bump)

    def test_dry_run_pushes_nothing(self):
        self.write("alpha", "1.1.0")
        self.merge("bump alpha")
        status, out = self.run_main("alpha", "--dry-run")
        self.assertEqual(status, 0, out)
        self.assertIn("would push alpha/v1.1.0", out)
        self.assertEqual(self.remote_tags(), [])

    def test_refuses_a_tag_that_exists_on_the_remote(self):
        self.write("alpha", "1.1.0")
        self.merge("bump alpha")
        self.assertEqual(self.run_main("alpha")[0], 0)
        status, out = self.run_main("alpha")
        self.assertEqual(status, 1)
        self.assertIn("already exists", out)

    def test_refuses_when_the_latest_change_did_not_bump(self):
        (self.repo / "plugins/alpha/notes.txt").write_text("x")
        self.merge("content without a bump")
        status, out = self.run_main("alpha")
        self.assertEqual(status, 1)
        self.assertIn("did not change its version", out)
        self.assertEqual(self.remote_tags(), [])

    def test_refuses_an_unlisted_plugin(self):
        status, out = self.run_main("gamma")
        self.assertEqual(status, 1)
        self.assertIn("not a plugin of this marketplace", out)

    def test_refuses_a_local_tag_that_points_elsewhere(self):
        self.write("alpha", "1.1.0")
        self.merge("bump alpha")
        git(self.repo, "tag", "alpha/v1.1.0", "HEAD~1")
        status, out = self.run_main("alpha")
        self.assertEqual(status, 1)
        self.assertEqual(self.remote_tags(), [])

    def test_only_unpublished_local_work_is_ignored(self):
        """A bump committed locally but not on the remote's main is not tagged."""
        self.write("alpha", "1.1.0")
        self.commit("bump alpha, not pushed")
        status, out = self.run_main("alpha", "--dry-run")
        self.assertIn("alpha/v1.0.0", out, "the remote's main still says 1.0.0")
        self.assertNotIn("1.1.0", out)


if __name__ == "__main__":
    unittest.main()
