"""Plan releases in disposable repositories: no network, no real tags."""
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "release_plugins", Path(__file__).resolve().parents[1] / "scripts" / "release-plugins.py")
rp = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rp)


def git(repo, *args):
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


class PlanReleasesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="release-plugins-")
        self.repo = Path(self.tmp.name)
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.email", "test@example.invalid")
        git(self.repo, "config", "user.name", "Test")
        (self.repo / ".claude-plugin").mkdir()
        manifest = {"plugins": [{"name": "alpha", "source": "./plugins/alpha"},
                                {"name": "beta", "source": "./plugins/beta"}]}
        (self.repo / ".claude-plugin/marketplace.json").write_text(json.dumps(manifest))
        self.write("alpha", "1.0.0", legacy=False)
        self.write("beta", "2.0.0", legacy=True)
        self.base = self.commit("base")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, version, legacy):
        path = self.repo / "plugins" / name / (".claude-plugin/plugin.json" if legacy else "plugin.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"name": name, "version": version}))

    def commit(self, message):
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", message)
        return git(self.repo, "rev-parse", "HEAD")

    def test_unchanged_versions_release_nothing(self):
        (self.repo / "plugins/alpha/notes.txt").write_text("x")
        self.commit("content only")
        self.assertEqual(rp.plan_releases(self.repo, self.base, "HEAD"), [])

    def test_bump_releases_only_the_changed_plugin(self):
        self.write("beta", "2.1.0", legacy=True)
        self.commit("bump beta")
        self.assertEqual([r.tag for r in rp.plan_releases(self.repo, self.base, "HEAD")], ["beta/v2.1.0"])

    def test_existing_tag_is_skipped(self):
        self.write("alpha", "1.1.0", legacy=False)
        self.commit("bump alpha")
        git(self.repo, "tag", "alpha/v1.1.0")
        self.assertEqual(rp.plan_releases(self.repo, self.base, "HEAD"), [])

    def test_no_base_releases_nothing(self):
        self.write("alpha", "1.1.0", legacy=False)
        self.commit("bump alpha")
        self.assertEqual(rp.plan_releases(self.repo, None, "HEAD"), [])

    def test_invalid_version_fails(self):
        self.write("alpha", "one", legacy=False)
        self.commit("bad version")
        with self.assertRaises(ValueError):
            rp.plan_releases(self.repo, self.base, "HEAD")


if __name__ == "__main__":
    unittest.main()
