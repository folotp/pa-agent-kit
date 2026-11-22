"""Plan releases in disposable repositories: no network, no real tags."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest import mock
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "release_plugins", Path(__file__).resolve().parents[1] / "scripts" / "release-plugins.py")
rp = importlib.util.module_from_spec(SPEC)
# @dataclass resolves its module through sys.modules (required on Python 3.14).
sys.modules[SPEC.name] = rp
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

    def bump_beta(self):
        self.write("beta", "2.1.0", legacy=True)
        self.commit("bump beta")

    def test_tag_matching_its_commit_is_a_release(self):
        self.bump_beta()
        self.assertEqual(rp.release_for_tag(self.repo, "beta/v2.1.0", "HEAD").tag, "beta/v2.1.0")

    def test_tag_that_disagrees_with_its_commit_is_refused(self):
        self.bump_beta()
        for tag in ("beta/v2.0.0", "gamma/v1.0.0", "beta/2.1.0", "beta/vx", "a/b/v1.0.0", "/v2.1.0"):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                rp.release_for_tag(self.repo, tag, "HEAD")

    def test_existing_tag_must_point_at_the_head_being_released(self):
        self.bump_beta()
        git(self.repo, "tag", "beta/v2.1.0")
        self.assertEqual(rp.release_for_tag(self.repo, "beta/v2.1.0", "HEAD").tag, "beta/v2.1.0")
        (self.repo / "plugins/beta/notes.txt").write_text("later, same version")
        self.commit("content only after the tag")
        with self.assertRaises(ValueError):
            rp.release_for_tag(self.repo, "beta/v2.1.0", "HEAD")  # same version, different payload
        self.assertEqual(rp.release_for_tag(self.repo, "beta/v2.1.0", "HEAD~1").tag, "beta/v2.1.0")

    def run_draft(self, state):
        """Run draft_release with git real and gh faked; `state` is what the releases list returns."""
        self.bump_beta()
        calls = []
        real_run = subprocess.run

        def fake_run(cmd, **kwargs):
            if cmd[0] == "git":
                return real_run(cmd, **kwargs)
            calls.append(cmd)
            if cmd == rp.RELEASE_LIST:
                releases = [] if state is None else [{"tag_name": "beta/v2.1.0", "draft": state == "draft"}]
                return mock.Mock(returncode=0, stdout=json.dumps([releases]))
            if cmd[:3] == ["gh", "release", "upload"]:
                with zipfile.ZipFile(cmd[5]) as archive:  # assets exist when uploaded
                    self.assertIn(".claude-plugin/plugin.json", archive.namelist())
                self.assertEqual(sorted(Path(a).name for a in cmd[5:]), ["beta-v2.1.0.plugin"])
            return mock.Mock(returncode=0)

        release = rp.release_for_tag(self.repo, "beta/v2.1.0", "HEAD")
        sha = git(self.repo, "rev-parse", "HEAD")
        with mock.patch.object(rp.subprocess, "run", side_effect=fake_run):
            try:
                rp.draft_release(self.repo, release, sha)
            finally:
                self.calls = calls

    def test_new_draft_is_created_then_gets_its_zip_and_no_tag_is_made(self):
        self.run_draft(None)
        verbs = [c[2] for c in self.calls if c[:2] == ["gh", "release"]]
        self.assertEqual(self.calls[0], rp.RELEASE_LIST)
        self.assertEqual(verbs, ["create", "upload"])
        self.assertIn("--draft", next(c for c in self.calls if c[2:3] == ["create"]))
        self.assertNotIn("--draft=false", [a for c in self.calls for a in c])
        self.assertEqual(git(self.repo, "tag", "--list"), "")  # the script never tags

    def test_existing_draft_is_reused_and_its_assets_replaced(self):
        self.run_draft("draft")
        self.assertEqual([c[2] for c in self.calls if c[:2] == ["gh", "release"]], ["upload"])
        self.assertIn("--clobber", next(c for c in self.calls if c[2:3] == ["upload"]))

    def test_list_error_does_not_create_another_draft(self):
        with mock.patch.object(rp.subprocess, "run", side_effect=subprocess.CalledProcessError(1, rp.RELEASE_LIST)) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                rp.release_state(self.repo, "beta/v2.1.0")
            self.assertEqual(run.call_count, 1)

    def test_published_release_is_never_touched(self):
        with self.assertRaises(RuntimeError):
            self.run_draft("published")
        self.assertEqual(self.calls, [rp.RELEASE_LIST])


if __name__ == "__main__":
    unittest.main()
