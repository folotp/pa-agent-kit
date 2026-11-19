"""Tests of harness/harness-sync, the script behind /dev-harness-sync (24g row I5i).

A bare repository stands in for the public workshop (HARNESS_WORKSHOP_URL points at it), holding a
copy of this repository's core and sync script under several harness-vX.Y tags; another bare
repository is the consumer's origin; a stub `gh` records the PR it is asked to open. Nothing
touches this repository or the network.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TAGS = ("harness-v0.1", "harness-v0.2", "harness-v0.9", "harness-v0.10")
GH_STUB = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$GH_LOG"
[ "${GH_FAIL:-0}" = 1 ] && { echo "gh: stub failure" >&2; exit 1; }
echo "https://github.com/example/consumer/pull/7"
"""


class HarnessSyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="harness-sync-test.")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.env = {
            "PATH": f"{self.tmp / 'bin'}:{os.environ['PATH']}",
            "HOME": str(self.tmp / "home"),
            "TMPDIR": str(self.tmp / "t"),
            "GH_LOG": str(self.tmp / "gh.log"),
            "GH_TOKEN": "fixture", "GIT_AUTHOR_NAME": "fixture[bot]", "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        for d in ("bin", "home", "t"):
            (self.tmp / d).mkdir()
        gh = self.tmp / "bin" / "gh"
        gh.write_text(GH_STUB)
        gh.chmod(0o755)

        # The workshop: this repository's core and sync script, one commit per tag, in a bare repository.
        src = self.tmp / "workshop-src"
        shutil.copytree(ROOT / "harness", src / "harness", ignore=shutil.ignore_patterns("__pycache__"))
        (src / "tools" / "sync").mkdir(parents=True)
        shutil.copy2(ROOT / "tools" / "sync" / "sync.py", src / "tools" / "sync" / "sync.py")
        self.git(src, "init", "-q", "-b", "main")
        for tag in TAGS:
            (src / "release").write_text(tag + "\n")
            self.git(src, "add", "-A")
            self.git(src, "commit", "-q", "-m", tag)
            self.git(src, "tag", tag)
        self.git(src, "tag", "harness-vX")  # not a core tag: never chosen as the newest
        self.workshop = self.tmp / "workshop.git"
        self.git(self.tmp, "init", "-q", "--bare", str(self.workshop))
        self.git(src, "push", "-q", str(self.workshop), "main", "--tags")
        self.env["HARNESS_WORKSHOP_URL"] = f"file://{self.workshop}"

        # The consumer: at core harness-v0.1, its main on a bare origin.
        self.origin = self.tmp / "origin.git"
        self.git(self.tmp, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.consumer = self.tmp / "consumer"
        (self.consumer / ".harness").mkdir(parents=True)
        shutil.copy2(ROOT / "harness" / "harness-sync", self.consumer / ".harness" / "harness-sync")
        (self.consumer / ".harness" / "VERSION").write_text("core harness-v0.1\ncommit 0\n")
        (self.consumer / "README.md").write_text("consumer\n")
        self.git(self.consumer, "init", "-q", "-b", "main")
        self.git(self.consumer, "add", "-A")
        self.git(self.consumer, "commit", "-q", "-m", "init")
        self.git(self.consumer, "remote", "add", "origin", str(self.origin))
        self.git(self.consumer, "push", "-q", "origin", "main")

    def git(self, cwd, *args):
        return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                              env=self.env, check=True).stdout

    def run_sync(self, *args, cwd=None, script=None, **extra_env):
        return subprocess.run([str(script or self.consumer / ".harness" / "harness-sync"), *args],
                              cwd=cwd or self.consumer, capture_output=True, text=True,
                              env={**self.env, **extra_env})

    def origin_file(self, branch, path):
        return self.git(self.origin, "show", f"{branch}:{path}")

    def assert_ending(self, result, done_prefix):
        lines = (result.stdout + result.stderr).strip().splitlines()
        self.assertTrue(lines[-3].startswith("done: " + done_prefix), lines[-3:])
        self.assertTrue(lines[-2].startswith("left for PA: "), lines[-3:])
        self.assertTrue(lines[-1].startswith("next: "), lines[-3:])
        return lines[-1]

    def assert_no_leftovers(self):
        self.assertEqual(len(self.git(self.consumer, "worktree", "list").splitlines()), 1)
        self.assertEqual(list((self.tmp / "t").iterdir()), [])

    def test_latest_is_the_highest_number(self):
        result = self.run_sync("--latest")
        self.assertEqual((result.returncode, result.stdout), (0, "harness-v0.10\n"), result.stderr)

    def test_latest_prints_nothing_without_a_workshop(self):
        result = self.run_sync("--latest", HARNESS_WORKSHOP_URL=f"file://{self.tmp}/none.git")
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_syncs_the_newest_tag_from_origin_main_without_touching_the_checkout(self):
        # The checkout is on another branch with an uncommitted file: the sync must not care.
        self.git(self.consumer, "switch", "-q", "-c", "feat/elsewhere")
        (self.consumer / "wip.txt").write_text("work in progress\n")
        main = self.git(self.consumer, "rev-parse", "main").strip()

        result = self.run_sync()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        branch = "harness-sync/harness-v0.10"
        self.assertTrue(self.origin_file(branch, ".harness/VERSION").startswith("core harness-v0.10\n"))
        self.assertEqual(self.origin_file(branch, ".harness/harness-sync"), (ROOT / "harness" / "harness-sync").read_text())
        self.assertEqual(self.git(self.origin, "rev-parse", f"{branch}^").strip(), main)
        self.assertIn(f"pr create --head {branch} --title chore: sync harness core harness-v0.10", (self.tmp / "gh.log").read_text())
        self.assertIn("https://github.com/example/consumer/pull/7", result.stdout)
        self.assertEqual(self.assert_ending(result, "core harness-v0.10 committed"), "next: after PA's merge, /dev-update-local-repo")
        self.assertEqual(self.git(self.consumer, "branch", "--show-current").strip(), "feat/elsewhere")
        self.assertEqual((self.consumer / "wip.txt").read_text(), "work in progress\n")
        self.assertEqual(self.git(self.consumer, "status", "--porcelain").strip(), "?? wip.txt")
        self.assert_no_leftovers()

    def test_a_named_tag(self):
        result = self.run_sync("harness-v0.2")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(self.origin_file("harness-sync/harness-v0.2", ".harness/VERSION").startswith("core harness-v0.2\n"))

    def test_explicitly_keeps_custom_consumer_files_in_the_pr(self):
        custom = {"CLAUDE.md": "@AGENTS.md\nConsumer notes.\n",
                  ".claude/settings.json": '{"hooks": {}}\n'}
        for name, content in custom.items():
            path = self.consumer / name
            path.parent.mkdir(exist_ok=True)
            path.write_text(content)
        self.git(self.consumer, "add", "-A")
        self.git(self.consumer, "commit", "-qm", "custom root files")
        self.git(self.consumer, "push", "-q", "origin", "main")

        refused = self.run_sync("harness-v0.2", "--keep-root", "CLAUDE.md")
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn(".claude/settings.json: the core guard hook", refused.stderr)
        self.assertFalse((self.tmp / "gh.log").exists())

        result = self.run_sync("--keep-root", "CLAUDE.md", "--keep-root", ".claude/settings.json")
        self.assertEqual(result.returncode, 0, result.stderr)
        for name, content in custom.items():
            self.assertEqual(self.origin_file("harness-sync/harness-v0.10", name), content)
            self.assertIn(f"`{name}` DIFFERS", (self.tmp / "gh.log").read_text())
        self.assert_no_leftovers()

    def test_already_at_the_tag_changes_nothing(self):
        result = self.run_sync("harness-v0.1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_ending(result, "nothing changed: already at core harness-v0.1")
        self.assertFalse((self.tmp / "gh.log").exists())
        self.assertEqual(self.git(self.origin, "branch", "--list", "harness-sync/*"), "")

    def test_requires_the_bot_wrapper_before_contacting_the_consumer_origin(self):
        for override in ({"GH_TOKEN": ""}, {"GIT_AUTHOR_NAME": "fixture"}):
            with self.subTest(override=list(override)):
                result = self.run_sync("harness-v0.2", **override)
                self.assertEqual(result.returncode, 1)
                self.assertIn(".harness/gh-token.sh <bot>", self.assert_ending(result, "refused"))
                self.assertFalse((self.consumer / ".git/FETCH_HEAD").exists())

    def test_checks_the_synced_version_on_origin_main(self):
        # A feature branch's VERSION must never suppress the PR main still needs.
        self.git(self.consumer, "switch", "-qc", "feature")
        (self.consumer / ".harness/VERSION").write_text("core harness-v0.2\n")
        result = self.run_sync("harness-v0.2")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PR opened", result.stdout)

    def test_refusals_change_nothing(self):
        cases = [
            (("harness-v7.7",), 1, "could not be fetched"),
            (("v1",), 2, "is not a core tag"),
            (("harness-v0.2", "extra"), 2, "usage:"),
            (("--keep-root",), 2, "usage:"),
            (("--latest", "--keep-root", "dev"), 2, "usage:"),
            (("--bogus",), 2, "usage:"),
        ]
        for args, code, reason in cases:
            with self.subTest(args=args):
                result = self.run_sync(*args)
                self.assertEqual(result.returncode, code, result.stdout + result.stderr)
                self.assertIn(reason, result.stderr)
                self.assert_ending(result, "refused; nothing changed")
                self.assert_no_leftovers()
        self.assertFalse((self.tmp / "gh.log").exists())
        self.assertEqual(self.git(self.origin, "branch", "--list", "harness-sync/*"), "")

    def test_the_workshop_names_dev_sync(self):
        workshop = self.tmp / "ws"
        (workshop / "harness").mkdir(parents=True)
        shutil.copy2(ROOT / "harness" / "harness-sync", workshop / "harness" / "harness-sync")
        self.git(workshop, "init", "-q", "-b", "main")
        result = self.run_sync(cwd=workshop, script=workshop / "harness" / "harness-sync")
        self.assertEqual(result.returncode, 1)
        self.assertIn("./dev sync <tag> <consumer-checkout> --pr", self.assert_ending(result, "refused"))

    def test_outside_a_repository(self):
        outside = self.tmp / "plain"
        outside.mkdir()
        result = self.run_sync(cwd=outside)
        self.assertEqual(result.returncode, 1)
        self.assertIn("not inside a git repository", result.stderr)

    def test_a_failed_pr_is_reported_and_cleaned_up(self):
        result = self.run_sync("harness-v0.2", GH_FAIL="1")
        self.assertEqual(result.returncode, 1)
        self.assertIn("gh pr create failed", result.stderr)
        self.assertEqual(self.assert_ending(result, "the sync to core harness-v0.2 failed"),
                         "next: inspect git show harness-sync/harness-v0.2 and the error above; resume the push or PR from that branch")
        self.assert_no_leftovers()


if __name__ == "__main__":
    unittest.main()
