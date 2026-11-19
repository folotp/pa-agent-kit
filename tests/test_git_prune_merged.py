"""Tests of harness/git-prune-merged.sh (24g row H1), offline.

A scratch repository with a GitHub-looking origin URL and worktrees, and a stub `gh` on PATH that
answers "merged pull requests from BRANCH" from a fixture table. Cases A to K are the eleven of
the script's first home (a live repository's tests/git-prune-merged/), with the protected name
now coming from harness.toml; the rest cover what the core version adds: `protected_branches`
read through conf.awk, --all, and the output rule's three last lines.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "harness" / "git-prune-merged.sh"
CONF_AWK = ROOT / "harness" / "conf.awk"

# The stub prints "<number> <headRefOid>" for each fixture row whose branch is the --head value.
GH_STUB = """#!/usr/bin/env bash
[ -n "${GH_FAIL:-}" ] && { echo "HTTP 401: Bad credentials" >&2; exit 1; }
head=""; while [ $# -gt 0 ]; do [ "$1" = "--head" ] && head="$2"; shift; done
awk -v h="$head" '$1==h{print $2" "$3}' "$GH_FIXTURE"
"""


class PruneTest(unittest.TestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="prune-test."))
        self.addCleanup(shutil.rmtree, self.work, True)
        bin_dir = self.work / "bin"
        bin_dir.mkdir()
        (bin_dir / "gh").write_text(GH_STUB)
        (bin_dir / "gh").chmod(0o755)
        self.fixture = self.work / "fixture"
        self.fixture.write_text("")
        self.env = {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "HOME": str(self.work),
            "GH_FIXTURE": str(self.fixture),
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@example.invalid",
        }
        self.repo = self.work / "repo"
        self.git(self.work, "init", "-q", "-b", "main", str(self.repo))
        (self.repo / "harness.toml").write_text('profile = "plugin"\ntools = ["git"]\nprotected_branches = ["standing"]\n')
        self.git(self.repo, "add", "harness.toml")
        self.git(self.repo, "commit", "-q", "-m", "init")
        self.git(self.repo, "remote", "add", "origin", "https://github.com/example/demo.git")

    def git(self, cwd, *args):
        return subprocess.run(["git", *args], cwd=cwd, env=self.env, check=True,
                              capture_output=True, text=True).stdout.strip()

    def wt(self, name):
        return self.work / ("wt-" + name.replace("/", "-"))

    def new_branch(self, name, worktree=False):
        """Create NAME from main (with a worktree and one commit in it, if asked); return its tip."""
        self.git(self.repo, "branch", name, "main")
        if worktree:
            self.git(self.repo, "worktree", "add", "-q", str(self.wt(name)), name)
            self.git(self.wt(name), "commit", "-q", "--allow-empty", "-m", f"work on {name}")
        else:
            self.git(self.repo, "commit", "-q", "--allow-empty", "-m", "x")  # keep main moving
        return self.git(self.repo, "rev-parse", f"refs/heads/{name}")

    def merged(self, branch, pr, oid):
        with self.fixture.open("a") as f:
            f.write(f"{branch} {pr} {oid}\n")

    def prune(self, *args, cwd=None, **extra_env):
        result = subprocess.run(["bash", str(SCRIPT), *args], cwd=cwd or self.repo,
                                env={**self.env, **extra_env}, capture_output=True, text=True, timeout=60)
        self.out = result.stdout + result.stderr
        self.stdout_lines = result.stdout.splitlines()
        return result.returncode

    def has_branch(self, name):
        return subprocess.run(["git", "rev-parse", "--verify", "-q", f"refs/heads/{name}"], cwd=self.repo,
                              env=self.env, capture_output=True).returncode == 0

    # --- the eleven cases of the script's first home

    def test_a_merged_tip_matches_clean_worktree(self):
        self.merged("fix/a", 101, self.new_branch("fix/a", worktree=True))
        self.assertEqual(self.prune("fix/a"), 0)
        self.assertFalse(self.has_branch("fix/a"))
        self.assertFalse(self.wt("fix/a").exists())

    def test_b_commit_after_the_merge_is_kept(self):
        self.merged("fix/b", 102, self.new_branch("fix/b", worktree=True))
        self.git(self.wt("fix/b"), "commit", "-q", "--allow-empty", "-m", "late work")
        self.assertEqual(self.prune("fix/b"), 1)
        self.assertTrue(self.has_branch("fix/b"))
        self.assertTrue(self.wt("fix/b").exists())
        self.assertIn("not the last commit", self.out)

    def test_c_no_merged_pull_request_is_kept(self):
        self.new_branch("fix/c")
        self.assertEqual(self.prune("fix/c"), 1)
        self.assertTrue(self.has_branch("fix/c"))
        self.assertIn("no merged pull request", self.out)

    def test_d_protected_name_from_harness_toml_is_kept(self):
        self.merged("standing", 104, self.new_branch("standing"))
        self.assertEqual(self.prune("standing"), 1)
        self.assertTrue(self.has_branch("standing"))
        self.assertIn("KEEP standing: protected branch name", self.out)

    def test_e_untracked_file_in_the_worktree_is_kept(self):
        self.merged("fix/e", 105, self.new_branch("fix/e", worktree=True))
        (self.wt("fix/e") / "notes.txt").write_text("scratch\n")
        self.assertEqual(self.prune("fix/e"), 1)
        self.assertTrue(self.has_branch("fix/e"))
        self.assertTrue((self.wt("fix/e") / "notes.txt").exists())
        self.assertIn("uncommitted or untracked", self.out)

    def test_ignored_marker_survives_preview_named_and_bulk_cleanup(self):
        self.merged("feature", 5, self.new_branch("feature", worktree=True))
        wt = self.wt("feature")
        info = Path(self.git(wt, "rev-parse", "--git-common-dir"))
        (wt / info / "info/exclude").write_text("local-note.txt\n")
        marker = wt / "local-note.txt"
        marker.write_text("kept\n")
        for args in [("--dry-run", "feature"), ("feature",), ("--all",)]:
            self.assertEqual(self.prune(*args), 1, self.out)
            self.assertEqual(marker.read_text(), "kept\n")
            self.assertTrue(self.has_branch("feature"))

    def test_unreadable_status_preserves_branch_and_worktree(self):
        self.merged("feature", 5, self.new_branch("feature", worktree=True))
        stub = self.work / "bin/git"
        stub.write_text('#!/bin/sh\ncase " $* " in *" status "*) exit 2 ;; esac\nexec /usr/bin/git "$@"\n')
        stub.chmod(0o755)
        self.assertEqual(self.prune("feature"), 1)
        self.assertIn("cannot read worktree status", self.out)
        self.assertTrue(self.wt("feature").is_dir())
        self.assertTrue(self.has_branch("feature"))

    def test_tip_change_during_pr_lookup_preserves_worktree(self):
        self.merged("feature", 5, self.new_branch("feature", worktree=True))
        stub = self.work / "bin/gh"
        stub.write_text(stub.read_text() + '\ngit -C "$WT" commit --allow-empty -qm later\n')
        self.assertEqual(self.prune("feature", WT=str(self.wt("feature"))), 1)
        self.assertIn("tip changed", self.out)
        self.assertTrue(self.wt("feature").is_dir())
        self.assertTrue(self.has_branch("feature"))

    def test_f_dry_run_deletes_nothing(self):
        self.merged("fix/f", 106, self.new_branch("fix/f", worktree=True))
        self.assertEqual(self.prune("--dry-run", "fix/f"), 0)
        self.assertTrue(self.has_branch("fix/f"))
        self.assertTrue(self.wt("fix/f").exists())
        self.assertIn("would prune fix/f", self.out)
        self.assertEqual(self.stdout_lines[-1], "next: /dev-delete-merged-branches fix/f (without --dry-run)")

    def test_g_one_good_one_bad(self):
        self.merged("fix/g1", 107, self.new_branch("fix/g1"))
        self.new_branch("fix/g2")
        self.assertEqual(self.prune("fix/g1", "fix/g2"), 1)
        self.assertFalse(self.has_branch("fix/g1"))
        self.assertTrue(self.has_branch("fix/g2"))
        self.assertEqual(self.stdout_lines[-3], "done: pruned 1: fix/g1; kept 1: fix/g2")

    def test_h_no_such_local_branch(self):
        self.assertEqual(self.prune("fix/nope"), 1)
        self.assertIn("no such local branch", self.out)

    def test_i_run_from_inside_the_branch_worktree(self):
        self.merged("fix/i", 109, self.new_branch("fix/i", worktree=True))
        self.assertEqual(self.prune("fix/i", cwd=self.wt("fix/i")), 1)
        self.assertTrue(self.has_branch("fix/i"))
        self.assertTrue(self.wt("fix/i").exists())
        self.assertIn("run from another checkout", self.out)

    def test_j_worktree_directory_already_gone(self):
        self.merged("fix/j", 110, self.new_branch("fix/j", worktree=True))
        shutil.rmtree(self.wt("fix/j"))
        self.assertEqual(self.prune("fix/j"), 0)
        self.assertFalse(self.has_branch("fix/j"))
        self.assertNotIn("branch refs/heads/fix/j", self.git(self.repo, "worktree", "list", "--porcelain"))

    def test_k_github_unreachable(self):
        self.merged("fix/k", 111, self.new_branch("fix/k"))
        self.assertEqual(self.prune("fix/k", GH_FAIL="1"), 1)
        self.assertTrue(self.has_branch("fix/k"))
        self.assertIn("could not ask GitHub (HTTP 401: Bad credentials", self.out)

    # --- what the core version adds

    def test_main_and_master_are_protected_without_harness_toml(self):
        self.git(self.repo, "rm", "-q", "harness.toml")
        self.git(self.repo, "commit", "-q", "-m", "no harness.toml")
        self.merged("main", 120, self.git(self.repo, "rev-parse", "main"))
        self.assertEqual(self.prune("main"), 1)
        self.assertIn("KEEP main: protected branch name", self.out)
        # Without harness.toml, a standing branch of another repository is an ordinary name.
        self.merged("standing", 121, self.new_branch("standing"))
        self.assertEqual(self.prune("standing"), 0)

    def test_a_refused_harness_toml_stops_before_anything(self):
        (self.repo / "harness.toml").write_text('profile = "plugin"\nprotected_branches = "standing"\n')
        self.merged("fix/t", 122, self.new_branch("fix/t"))
        self.assertEqual(self.prune("fix/t"), 2)
        self.assertTrue(self.has_branch("fix/t"))
        self.assertIn("unknown key, or wrong type: protected_branches", self.out)
        self.assertIn("done: refused; nothing changed", self.out)

    def test_all_prunes_merged_branches_and_leaves_open_ones_quietly(self):
        self.merged("fix/m", 130, self.new_branch("fix/m", worktree=True))
        self.new_branch("fix/open")
        self.merged("standing", 131, self.new_branch("standing"))
        self.assertEqual(self.prune("--all"), 0)
        self.assertFalse(self.has_branch("fix/m"))
        self.assertTrue(self.has_branch("fix/open"))
        self.assertTrue(self.has_branch("standing"))
        self.assertTrue(self.has_branch("main"))
        self.assertNotIn("KEEP", self.out)
        self.assertEqual(self.stdout_lines[-3:], [
            "done: pruned 1: fix/m; 1 without a merged pull request, left alone",
            "left for PA: nothing",
            "next: /dev-status",
        ])

    def test_all_reports_a_merged_branch_it_must_keep(self):
        self.merged("fix/late", 132, self.new_branch("fix/late", worktree=True))
        self.git(self.wt("fix/late"), "commit", "-q", "--allow-empty", "-m", "late work")
        self.assertEqual(self.prune("--all"), 1)
        self.assertIn("KEEP fix/late:", self.out)
        self.assertEqual(self.stdout_lines[-1], "next: fix what a KEEP line names, then /dev-delete-merged-branches <branch>")

    def test_usage_errors_end_with_the_output_rule(self):
        for args in ((), ("--all", "fix/x"), ("--bogus",)):
            with self.subTest(args=args):
                self.assertEqual(self.prune(*args), 2)
                self.assertIn("done: refused; nothing changed", self.out)
                self.assertIn("next: /dev-delete-merged-branches", self.out)

    def test_not_a_github_origin_is_refused(self):
        self.git(self.repo, "remote", "set-url", "origin", "https://example.invalid/demo.git")
        self.new_branch("fix/o")
        self.assertEqual(self.prune("fix/o"), 2)
        self.assertIn("origin is not a GitHub remote", self.out)


class ProtectedBranchesConfTest(unittest.TestCase):
    """conf.awk accepts `protected_branches` as a top-level array, and only as one."""

    def parse(self, text):
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
            f.write(text)
        self.addCleanup(os.unlink, f.name)
        return subprocess.run(["awk", "-f", str(CONF_AWK), f.name], capture_output=True, text=True)

    def test_an_array_is_accepted(self):
        result = self.parse('profile = "plugin"\nprotected_branches = ["one", "two"]\n')
        self.assertEqual(result.returncode, 0)
        self.assertIn("conf\tprotected_branches\tone two", result.stdout)

    def test_a_string_or_a_table_key_is_refused(self):
        for text in ('protected_branches = "one"\n', '[gate]\nprotected_branches = ["one"]\n'):
            with self.subTest(text=text):
                result = self.parse(text)
                self.assertEqual(result.returncode, 1)
                self.assertIn("protected_branches", result.stderr)


if __name__ == "__main__":
    unittest.main()
