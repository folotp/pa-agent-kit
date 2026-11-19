"""Tests of the release gate (harness/gate): one test, at least, per refusal case.

Most tests source the gate in bash and call one check against a disposable git fixture (a bare
`origin` and a clone). GitHub is replaced by a `gh` shell function that answers from files, so the
tests cover the gate's decisions, not gh's `--jq` filters (unchanged from the two live gates).
The settings, the clean re-run and the release command are tested through the real script.
Processes start in a new session (no controlling terminal); the confirmation tests give them a
pseudo-terminal. Nothing touches the repository or the network.
"""

import os
import pty
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GATE = ROOT / "harness" / "gate"
SYSTEM_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
MISE_LOCATIONS = ("/opt/homebrew/bin/mise", "/usr/local/bin/mise", os.path.expanduser("~/.local/bin/mise"))

# Replaces gh: `gh api [flags] <path> …` prints the file of that path in $FIX (with --paginate also
# its later pages, <file>.2, <file>.3 …), or fails when there is none; GH_SLEEP makes it hang.
PRELUDE = r"""
set -euo pipefail
source "$GATE"
gh() {
  [ "$1" = api ] || return 1
  shift
  local p="" pg="" n=2 f
  while [ $# -gt 0 ]; do
    case "$1" in --paginate) pg=1 ;; --jq) shift ;; -*) ;; *) [ -n "$p" ] || p="$1" ;; esac
    shift
  done
  f="$FIX/$(printf '%s' "$p" | tr '/?&=' '____')"
  [ -f "$f" ] || return 1
  cat "$f"
  while [ -n "$pg" ] && [ -f "$f.$n" ]; do cat "$f.$n"; n=$((n + 1)); done
  [ -z "${GH_SLEEP:-}" ] || sleep "$GH_SLEEP"
}
conf_repo=o/r conf_merger=pa conf_verb=deploy conf_ci=check-runs conf_checks_app=github-actions
conf_required=ci conf_guarded=guarded conf_loaded='*.auto.tfvars'
"""

# The harness.toml [gate] table that PRELUDE's conf_* values stand for.
SOURCED_GATE = """[gate]
repo = "o/r"
merger = "pa"
verb = "deploy"
ci = "check-runs"
checks_app = "github-actions"
required = ["ci"]
guarded = ["guarded"]
loaded = ["*.auto.tfvars"]
"""


def base_env(**extra):
    env = {
        "HOME": os.environ["HOME"],
        "PATH": SYSTEM_PATH,
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GATE": str(GATE),
    }
    env.update(extra)
    return env


def git(cwd, *args):
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-C", str(cwd), *args],
        env=base_env(), check=True, capture_output=True, text=True,
    ).stdout.strip()


def fix_name(path):
    return path.translate(str.maketrans("/?&=", "____"))


class GitFixture:
    """A bare origin with one commit on main, and a clean clone of it (`work`)."""

    def __init__(self, test):
        self.dir = Path(tempfile.mkdtemp(prefix="gate-test."))
        test.addCleanup(shutil.rmtree, self.dir, True)
        self.fix = self.dir / "gh"
        self.fix.mkdir()
        self.origin = self.dir / "origin.git"
        self.work = self.dir / "work"
        git(self.dir, "init", "-q", "--bare", "-b", "main", str(self.origin))
        git(self.dir, "clone", "-q", str(self.origin), str(self.work))
        git(self.work, "checkout", "-q", "-b", "main")
        (self.work / ".gitignore").write_text("mise.local.toml\n.tool-versions\n.config/\n*.auto.tfvars\n")
        (self.work / "guarded").write_text("v1\n")
        (self.work / "a.txt").write_text("a\n")
        self.commit("first")

    def commit(self, message):
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "-m", message)
        git(self.work, "push", "-q", "origin", "HEAD:main")
        git(self.work, "fetch", "-q", "origin")
        return self.sha

    @property
    def sha(self):
        return git(self.work, "rev-parse", "HEAD")

    def gh(self, path, text):
        (self.fix / fix_name(path)).write_text(text)

    def github_ok(self, sha=None, merger="pa"):
        """GitHub answers for a commit that passes every check."""
        sha = sha or self.sha
        self.gh("repos/o/r/commits/main", sha + "\n")
        self.gh(f"repos/o/r/commits/{sha}/check-runs?per_page=100", "ci\tgithub-actions\tcompleted\tsuccess\n")
        self.gh(f"repos/o/r/commits/{sha}/pulls?per_page=100", "7\n")
        self.gh("repos/o/r/pulls/7", merger + "\n")

    def run(self, script, **env):
        return subprocess.run(
            ["bash", "-c", PRELUDE + script],
            cwd=self.work, env=base_env(FIX=str(self.fix), **env),
            capture_output=True, text=True, timeout=60, start_new_session=True,
        )

    def run_tty(self, script, answer):
        """Runs the script on a pseudo-terminal, answers the first prompt; returns (rc, output)."""
        pid, fd = pty.fork()
        if pid == 0:
            os.chdir(self.work)
            os.execve("/bin/bash", ["bash", "-c", PRELUDE + script], base_env(FIX=str(self.fix)))
        out, answered = b"", False
        while True:
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            out += chunk
            if not answered and b"(type yes)" in out:
                os.write(fd, answer + b"\n")
                answered = True
        _, status = os.waitpid(pid, 0)
        os.close(fd)
        return os.waitstatus_to_exitcode(status), out.decode(errors="replace")


class GateTestCase(unittest.TestCase):
    def setUp(self):
        self.f = GitFixture(self)

    def assertRefused(self, result, message):
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(message, result.stderr)

    def assertPassed(self, result, message=""):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(message, result.stdout)


class CleanTreeTest(GateTestCase):
    def test_clean_tree_passes(self):
        self.assertPassed(self.f.run("gate_clean_tree"), "gate: tree clean")

    def test_hidden_index_entries_are_refused(self):
        for flag in ("--assume-unchanged", "--skip-worktree"):
            with self.subTest(flag):
                git(self.f.work, "update-index", flag, "a.txt")
                self.assertRefused(self.f.run("gate_clean_tree"), "index entry hides local changes")
                git(self.f.work, "update-index", flag.replace("--", "--no-"), "a.txt")

    def test_failing_index_listing_is_refused(self):
        """Codex C11: git's own failure is a refusal, not an empty list."""
        script = 'git() { if [ "$1 $2" = "ls-files -v" ]; then return 128; fi; command git "$@"; }; gate_clean_tree'
        self.assertRefused(self.f.run(script), "git ls-files -v failed")

    def test_modified_and_untracked_files_are_refused(self):
        (self.f.work / "a.txt").write_text("changed\n")
        self.assertRefused(self.f.run("gate_clean_tree"), "working tree not clean")
        git(self.f.work, "checkout", "-q", "a.txt")
        (self.f.work / "new.txt").write_text("x\n")
        self.assertRefused(self.f.run("gate_clean_tree"), "working tree not clean")

    def test_ignored_files_that_mise_loads_are_refused(self):
        for name in ("mise.local.toml", ".tool-versions", ".config/mise/config.toml"):
            with self.subTest(name):
                path = self.f.work / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("")
                self.assertRefused(self.f.run("gate_clean_tree"), "ignored file that mise would load")
                shutil.rmtree(self.f.work / ".config", True) if name.startswith(".config") else path.unlink()

    def test_ignored_files_that_the_release_loads_are_refused(self):
        (self.f.work / "zone.auto.tfvars").write_text("")
        self.assertRefused(self.f.run("gate_clean_tree"), "ignored file that the release would load: zone.auto.tfvars")


class TipTest(GateTestCase):
    def test_no_github_token_is_refused(self):
        self.assertRefused(self.f.run("need_gh_token"), "no GitHub token")

    def test_tip_of_main_passes(self):
        self.f.github_ok()
        self.assertPassed(self.f.run("gate_tip"), "is the tip of main")

    def test_unreachable_origin_is_refused(self):
        git(self.f.work, "remote", "set-url", "origin", str(self.f.dir / "missing.git"))
        self.assertRefused(self.f.run("gate_tip"), "cannot fetch origin main")

    def test_head_behind_origin_main_is_refused(self):
        old = self.f.sha
        (self.f.work / "a.txt").write_text("b\n")
        self.f.commit("second")
        git(self.f.work, "checkout", "-q", "--detach", old)
        self.assertRefused(self.f.run("gate_tip"), "is not the tip of origin/main")

    def test_origin_main_differing_from_github_is_refused(self):
        self.f.gh("repos/o/r/commits/main", "0" * 40 + "\n")
        self.assertRefused(self.f.run("gate_tip"), "is not main of o/r on GitHub")

    def test_unreadable_github_main_is_refused(self):
        self.assertRefused(self.f.run("gate_tip"), "cannot read main of o/r from GitHub")


class CiTest(GateTestCase):
    def ci(self, runs, mode="check-runs", required="ci"):
        sha = self.f.sha
        if mode == "check-runs":
            path, app = f"repos/o/r/commits/{sha}/check-runs?per_page=100", "github-actions"
        else:
            path, app = f"repos/o/r/actions/runs?head_sha={sha}&event=push&per_page=100", ""
        if runs is not None:
            self.f.gh(path, runs)
        return self.f.run(f"conf_ci={mode} conf_checks_app={app} conf_required='{required}'; gate_ci {sha}")

    def test_green_runs_pass_in_both_modes(self):
        self.assertPassed(self.ci("ci\tgithub-actions\tcompleted\tsuccess\nlint\tother\tcompleted\tskipped\n"), "CI green")
        wf = ".github/workflows/v.yml"
        self.assertPassed(self.ci(f"{wf}\t\tcompleted\tsuccess\n", "workflow-runs", wf), "CI green")

    def test_unreadable_runs_are_refused(self):
        self.assertRefused(self.ci(None), "cannot read the check runs")
        self.assertRefused(self.ci(None, "workflow-runs"), "cannot read the workflow runs")

    def test_no_run_is_refused(self):
        self.assertRefused(self.ci(""), "no CI run on")

    def test_running_check_is_refused(self):
        self.assertRefused(self.ci("ci\tgithub-actions\tin_progress\tnone\n"), "CI still running")

    def test_failed_check_is_refused(self):
        runs = "ci\tgithub-actions\tcompleted\tsuccess\nlint\tgithub-actions\tcompleted\tfailure\n"
        self.assertRefused(self.ci(runs), "CI not green on")

    def test_missing_required_check_is_refused(self):
        self.assertRefused(self.ci("lint\tgithub-actions\tcompleted\tsuccess\n"), "no green 'ci' run")

    def test_required_check_from_another_app_is_refused(self):
        self.assertRefused(self.ci("ci\tsome-app\tcompleted\tsuccess\n"), "no green 'ci' run from github-actions")

    def test_failure_on_a_later_page_is_refused(self):
        """Codex C10: the gate follows every page, so a failure past the first 100 runs is seen."""
        path = f"repos/o/r/commits/{self.f.sha}/check-runs?per_page=100"
        self.f.gh(path + ".2", "late\tgithub-actions\tcompleted\tfailure\n")
        self.assertRefused(self.ci("ci\tgithub-actions\tcompleted\tsuccess\n"), "CI not green on")

    def test_github_read_that_hangs_is_refused_at_the_deadline(self):
        """Codex C23: a hung read ends in a refusal, not a stuck gate."""
        self.f.github_ok()
        start = time.monotonic()
        result = self.f.run(f"gate_deadline=1; gate_merged_by {self.f.sha}", GH_SLEEP="20")
        self.assertRefused(result, "cannot read the PRs")
        self.assertLess(time.monotonic() - start, 10)


class MergedByTest(GateTestCase):
    def test_merged_by_pa_passes(self):
        self.f.github_ok()
        self.assertPassed(self.f.run(f"gate_merged_by {self.f.sha}"), "merged by pa")

    def test_unreadable_pulls_are_refused(self):
        self.assertRefused(self.f.run(f"gate_merged_by {self.f.sha}"), "cannot read the PRs")

    def test_commit_without_pr_is_refused(self):
        self.f.gh(f"repos/o/r/commits/{self.f.sha}/pulls?per_page=100", "")
        self.assertRefused(self.f.run(f"gate_merged_by {self.f.sha}"), "is not the merge commit of a PR")

    def test_several_prs_are_refused(self):
        self.f.gh(f"repos/o/r/commits/{self.f.sha}/pulls?per_page=100", "7\n8\n")
        self.assertRefused(self.f.run(f"gate_merged_by {self.f.sha}"), "merge commit of several PRs")

    def test_merged_by_someone_else_is_refused(self):
        self.f.github_ok(merger="folotp-claude[bot]")
        self.assertRefused(self.f.run(f"gate_merged_by {self.f.sha}"), "merged by 'folotp-claude[bot]', not by 'pa'")

    def test_unreadable_pr_is_refused(self):
        self.f.gh(f"repos/o/r/commits/{self.f.sha}/pulls?per_page=100", "7\n")
        self.assertRefused(self.f.run(f"gate_merged_by {self.f.sha}"), "cannot read PR #7")


class RecordTest(GateTestCase):
    def write_last(self, text):
        record = self.f.work / ".git" / "dev-deploy"
        record.mkdir(exist_ok=True)
        (record / "last").write_text(text)

    def change(self, message, pr=None, merger="pa"):
        """One more commit on main; with `pr`, GitHub calls it the merge commit of that PR."""
        (self.f.work / "a.txt").write_text(message + "\n")
        sha = self.f.commit(message)
        self.f.gh(f"repos/o/r/commits/{sha}/pulls?per_page=100", f"{pr}\n" if pr else "")
        if pr:
            self.f.gh(f"repos/o/r/pulls/{pr}", merger + "\n")
        return sha

    def test_bad_record_is_refused(self):
        self.write_last("not-a-sha\n")
        result = self.f.run(f"gate_since_last {self.f.sha}")
        self.assertEqual(result.returncode, 1)
        self.assertIn("bad record", result.stderr)

    def test_no_record_is_refused(self):
        self.assertRefused(self.f.run(f"gate_since_last {self.f.sha}"), "no last release on record")

    def test_record_not_in_this_clone_is_refused(self):
        self.write_last("1" * 40 + "\n")
        self.assertRefused(self.f.run(f"gate_since_last {self.f.sha}"), "is not in this clone")

    def test_merges_by_the_merger_pass(self):
        self.write_last(self.f.sha + "\n")
        self.change("b", pr=7)
        tip = self.change("c", pr=8)
        self.assertPassed(self.f.run(f"gate_since_last {tip}"), "2 change(s) to main since the last release")

    def test_rerelease_of_the_last_commit_passes(self):
        self.write_last(self.f.sha + "\n")
        self.assertPassed(self.f.run(f"gate_since_last {self.f.sha}"), "0 change(s)")

    def test_going_back_is_refused(self):
        old = self.f.sha
        self.write_last(self.change("b", pr=7) + "\n")
        self.assertRefused(self.f.run(f"gate_since_last {old}"), "does not descend from the last released commit")

    def test_direct_push_between_two_merges_is_refused(self):
        """K21: a bot pushes to main directly; PA's next, unrelated merge puts it in the tip's history."""
        self.write_last(self.change("b", pr=7) + "\n")
        pushed = self.change("direct push")
        tip = self.change("c", pr=8)
        result = self.f.run(f"gate_since_last {tip}")
        self.assertRefused(result, f"{pushed[:12]} is not the merge commit of a PR into main")

    def test_merge_by_someone_else_in_between_is_refused(self):
        self.write_last(self.f.sha + "\n")
        self.change("b", pr=7, merger="folotp-claude[bot]")
        tip = self.change("c", pr=8)
        self.assertRefused(self.f.run(f"gate_since_last {tip}"), "PR #7 was merged by 'folotp-claude[bot]'")


class BaselineTest(GateTestCase):
    """PA's choice (session 24c): the baseline stays in the clone; a lock serialises releases;
    only `./dev gate --baseline <sha>`, confirmed on the terminal, sets it outside a release."""

    def setUp(self):
        super().setUp()
        self.record = self.f.work / ".git" / "dev-deploy"

    def lock_to(self, target):
        self.record.mkdir(parents=True, exist_ok=True)
        (self.record / "lock").symlink_to(target)

    def test_lock_carries_its_owner_from_the_moment_it_exists(self):
        """Codex review of #102: no window in which a live lock has no PID to check."""
        result = self.f.run('take_lock; [ "$(readlink "$record_dir/lock")" = "$$" ] && echo OWNED')
        self.assertPassed(result, "OWNED")
        self.assertFalse(os.path.lexists(self.record / "lock"), "released on exit")

    def test_lock_of_a_running_process_is_refused_and_kept(self):
        self.lock_to(str(os.getpid()))
        self.assertRefused(self.f.run("take_lock"), f"another release of this clone is running (pid {os.getpid()})")
        self.assertEqual(os.readlink(self.record / "lock"), str(os.getpid()), "a refused run leaves the owner's lock")

    def test_lock_of_a_gone_process_is_taken_over_and_released_on_exit(self):
        self.lock_to("999999")
        self.assertPassed(self.f.run('take_lock; [ "$(readlink "$record_dir/lock")" = "$$" ]'), "taking over a lock")
        self.assertFalse(os.path.lexists(self.record / "lock"))

    def test_lock_that_is_not_a_pid_link_is_refused_not_removed(self):
        (self.record / "lock").mkdir(parents=True)
        self.assertRefused(self.f.run("take_lock"), "is not a lock of this gate")
        self.assertTrue((self.record / "lock").is_dir())

    def test_a_run_never_removes_a_lock_it_does_not_own(self):
        self.lock_to(str(os.getpid()))
        self.assertPassed(self.f.run("set_record_dir; lock_held=1; release_lock"))
        self.assertEqual(os.readlink(self.record / "lock"), str(os.getpid()))

    def test_last_changed_during_the_run_is_not_overwritten(self):
        self.record.mkdir()
        (self.record / "last").write_text(self.f.sha + "\n")
        result = self.f.run(f"read_last; echo {'1' * 40} > \"$record_dir/last\"; record {'2' * 40} ok")
        self.assertRefused(result, "changed during this run")
        self.assertEqual((self.record / "last").read_text().strip(), "1" * 40)

    def baseline(self, sha, answer):
        return self.f.run_tty(f"load_conf() {{ :; }}; set_baseline {sha}", answer)

    def test_baseline_needs_yes_and_records(self):
        rc, out = self.baseline(self.f.sha, b"no")
        self.assertEqual(rc, 1, out)
        self.assertFalse((self.record / "last").exists())
        rc, out = self.baseline(self.f.sha, b"yes")
        self.assertEqual(rc, 0, out)
        self.assertIn("baseline recorded", out)
        self.assertEqual((self.record / "last").read_text().strip(), self.f.sha)
        self.assertIn(f"{self.f.sha} baseline", (self.record / "log").read_text())
        self.assertFalse(os.path.lexists(self.record / "lock"))

    def test_baseline_replaces_a_malformed_record(self):
        """Codex review of #102: the recovery the refusal names must work on that refusal's cause."""
        self.record.mkdir()
        (self.record / "last").write_text("not-a-sha\n")
        self.assertRefused(self.f.run(f"gate_since_last {self.f.sha}"), "--baseline <sha>")
        rc, out = self.baseline(self.f.sha, b"yes")
        self.assertEqual(rc, 0, out)
        self.assertIn("now:  malformed (not?a?sha)", out)
        self.assertEqual((self.record / "last").read_text().strip(), self.f.sha)

    def test_baseline_off_main_is_refused(self):
        git(self.f.work, "checkout", "-q", "-b", "side")
        (self.f.work / "a.txt").write_text("side\n")
        git(self.f.work, "commit", "-qam", "side")
        side = git(self.f.work, "rev-parse", "HEAD")
        self.assertRefused(self.f.run(f"load_conf() {{ :; }}; set_baseline {side}"), "is not on origin/main")

    def test_baseline_without_terminal_is_refused(self):
        self.assertRefused(self.f.run(f"load_conf() {{ :; }}; set_baseline {self.f.sha}"), "no terminal to confirm on")


class GuardedDiffTest(GateTestCase):
    def setUp(self):
        super().setUp()
        # The [gate] table of the last release: the same settings as PRELUDE's conf_* values.
        (self.f.work / "harness.toml").write_text(SOURCED_GATE)
        self.first = self.f.commit("settings")
        record = self.f.work / ".git" / "dev-deploy"
        record.mkdir()
        (record / "last").write_text(self.first + "\n")

    def test_unchanged_guarded_files_need_no_terminal(self):
        (self.f.work / "a.txt").write_text("b\n")
        self.assertPassed(self.f.run(f"gate_guarded_diff {self.f.commit('second')}"), "guarded files and gate settings unchanged")

    def test_changed_guarded_files_without_terminal_are_refused(self):
        (self.f.work / "guarded").write_text("v2\n")
        self.assertRefused(self.f.run(f"gate_guarded_diff {self.f.commit('second')}"), "no terminal to confirm on")

    def test_fixed_paths_are_guarded_whatever_the_settings_say(self):
        for name in ("dev", ".gitignore", "mise.toml", ".github/workflows/ci.yml", ".githooks/pre-push", ".claude/settings.json", "harness/x"):
            with self.subTest(name):
                path = self.f.work / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(name + "\n")
                sha = self.f.commit(name)
                self.assertRefused(self.f.run(f"gate_guarded_diff {sha}"), "no terminal to confirm on")

    def test_path_dropped_from_guarded_is_still_shown(self):
        """The candidate cannot hide a path by removing it from `guarded`: the last release's list counts."""
        (self.f.work / "guarded").write_text("v2\n")
        sha = self.f.commit("second")
        rc, out = self.f.run_tty(f"conf_guarded=other; gate_guarded_diff {sha}", b"no")
        self.assertEqual(rc, 1, out)
        self.assertIn("+v2", out)
        self.assertIn("guarded: 'guarded' -> 'other'", out)

    def test_changed_setting_is_shown_and_needs_yes(self):
        (self.f.work / "a.txt").write_text("b\n")
        sha = self.f.commit("second")
        self.assertRefused(self.f.run(f"conf_merger=someone; gate_guarded_diff {sha}"), "no terminal to confirm on")
        rc, out = self.f.run_tty(f"conf_merger=someone; gate_guarded_diff {sha}; echo CONFIRMED", b"yes")
        self.assertEqual(rc, 0, out)
        self.assertIn("Gate settings changed since the last release", out)
        self.assertIn("merger: 'pa' -> 'someone'", out)
        self.assertIn("CONFIRMED", out)

    def test_last_release_without_gate_table_needs_confirmation(self):
        (self.f.work / ".git" / "dev-deploy" / "last").write_text(git(self.f.work, "rev-parse", "HEAD~1") + "\n")
        rc, out = self.f.run_tty(f"gate_guarded_diff {self.f.sha}", b"no")
        self.assertEqual(rc, 1, out)
        self.assertIn("no readable [gate] table (none): every gate setting is new", out)

    def test_no_record_is_refused(self):
        (self.f.work / ".git" / "dev-deploy" / "last").unlink()
        self.assertRefused(self.f.run(f"gate_guarded_diff {self.f.sha}"), "no last release on record")

    def test_changed_guarded_files_are_shown_and_need_yes(self):
        (self.f.work / "guarded").write_text("v2\n")
        sha = self.f.commit("second")
        rc, out = self.f.run_tty(f"gate_guarded_diff {sha}; echo CONFIRMED", b"no")
        self.assertEqual(rc, 1, out)
        self.assertIn("+v2", out)
        self.assertIn("stopped: not confirmed", out)
        rc, out = self.f.run_tty(f"gate_guarded_diff {sha}; echo CONFIRMED", b"yes")
        self.assertEqual(rc, 0, out)
        self.assertIn("CONFIRMED", out)


class ReleaseTest(GateTestCase):
    """run_release: the record follows the release command's exit code; no token reaches it."""

    def setUp(self):
        super().setUp()
        script = self.f.dir / "release.sh"
        script.write_text('#!/bin/sh\nenv > "$GATE_RECORD_DIR/env.out"\nexit "$RC"\n')
        script.chmod(0o755)
        self.record = self.f.work / ".git" / "dev-deploy"

    def release(self, rc):
        return self.f.run(
            f"root={self.f.dir} conf_release=release.sh; read_last; mkdir -p \"$record_dir\"; "
            f"run_release {self.f.sha} --mode x",
            RC=str(rc), GH_TOKEN="secret-token", GIT_CONFIG_COUNT="1",
            GIT_CONFIG_KEY_0="http.extraHeader", GIT_CONFIG_VALUE_0="secret-header",
        )

    def test_success_is_recorded_and_gets_no_token(self):
        self.assertPassed(self.release(0), "released")
        self.assertEqual((self.record / "last").read_text().strip(), self.f.sha)
        env = (self.record / "env.out").read_text()
        self.assertIn(f"GATE_SHA={self.f.sha}", env)
        self.assertNotIn("secret", env)
        self.assertNotIn("GIT_CONFIG_COUNT", env)
        self.assertNotIn("GIT_CONFIG_KEY_0", env)

    def test_dry_run_records_nothing(self):
        self.assertPassed(self.release(3), "nothing was released or recorded")
        self.assertFalse((self.record / "last").exists())
        self.assertFalse((self.record / "log").exists())

    def test_failure_is_logged_not_recorded(self):
        self.assertRefused(self.release(5), "the release failed (exit 5)")
        self.assertFalse((self.record / "last").exists())
        self.assertIn("failed-exit-5", (self.record / "log").read_text())


GOOD_GATE = """
tools = ["gh"]
[gate]
repo = "o/r"
merger = "pa"
verb = "deploy"
release = "release.sh"
ci = "workflow-runs"
required = [".github/workflows/ci.yml"]
guarded = [".github", "harness"]
"""


class ScriptFixture:
    """A copy of the gate, its parser and dev, with its own harness.toml and release command."""

    def __init__(self, test, toml):
        self.dir = Path(tempfile.mkdtemp(prefix="gate-script."))
        test.addCleanup(shutil.rmtree, self.dir, True)
        (self.dir / "harness").mkdir()
        for name in ("gate", "conf.awk", "dev", "gh-token.sh"):
            shutil.copy2(ROOT / "harness" / name, self.dir / "harness" / name)
        (self.dir / "harness.toml").write_text('profile = "live-config"\n' + toml)
        release = self.dir / "release.sh"
        release.write_text("#!/bin/sh\nexit 0\n")
        release.chmod(0o755)
        git(self.dir, "init", "-q", "-b", "main")
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-q", "-m", "fixture")

    def run(self, *args, **extra):
        """Runs the gate with only home, a system PATH, the temp directory and `extra`."""
        env = {"HOME": os.environ["HOME"], "PATH": SYSTEM_PATH, "TMPDIR": os.environ.get("TMPDIR", "/tmp")}
        env.update(extra)
        return subprocess.run(
            [str(self.dir / "harness" / "gate"), *args], cwd=self.dir, env=env,
            capture_output=True, text=True, timeout=120, start_new_session=True,
        )


class SettingsTest(unittest.TestCase):
    def test_good_settings_pass(self):
        result = ScriptFixture(self, GOOD_GATE).run("tree")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_bad_settings_are_refused(self):
        cases = {
            "no [gate] table": 'tools = ["gh"]\n',
            "bad repo": GOOD_GATE.replace('"o/r"', '"o/r/x"'),
            "bad merger": GOOD_GATE.replace('"pa"', '"p a"'),
            "verb is apply or deploy": GOOD_GATE.replace('"deploy"', '"release"'),
            "is not an executable file": GOOD_GATE.replace('"release.sh"', '"../release.sh"'),
            "ci is check-runs or workflow-runs": GOOD_GATE.replace('"workflow-runs"', '"statuses"'),
            "check-runs needs checks_app": GOOD_GATE.replace('"workflow-runs"', '"check-runs"'),
            "checks_app is for check-runs only": GOOD_GATE + 'checks_app = "github-actions"\n',
            "required lists at least one check": GOOD_GATE.replace('[".github/workflows/ci.yml"]', "[]"),
            "blank array item, or whitespace in one: required": GOOD_GATE.replace('[".github/workflows/ci.yml"]', '[" "]'),
            "key given twice: merger": GOOD_GATE + 'merger = "someone"\n',
            "bad keep_env": GOOD_GATE + 'keep_env = ["lower"]\n',
            "bad loaded": GOOD_GATE + 'loaded = ["a;b"]\n',
            "tools must include gh": GOOD_GATE.replace('["gh"]', '["git"]'),
            "unknown gate key": GOOD_GATE + 'mergers = "pa"\n',
        }
        for message, toml in cases.items():
            with self.subTest(message):
                result = ScriptFixture(self, toml).run("tree")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(message, result.stderr)

    def test_release_command_must_be_executable(self):
        fixture = ScriptFixture(self, GOOD_GATE)
        (fixture.dir / "release.sh").chmod(0o644)
        self.assertIn("is not an executable file", fixture.run("tree").stderr)

    def test_release_command_must_be_a_tracked_regular_file(self):
        """Codex C12: an untracked file, or a symbolic link, is not what the checks covered."""
        fixture = ScriptFixture(self, GOOD_GATE.replace('"release.sh"', '"other.sh"'))
        (fixture.dir / "other.sh").write_text("#!/bin/sh\n")
        (fixture.dir / "other.sh").chmod(0o755)
        self.assertIn("not a tracked regular executable file", fixture.run("tree").stderr)
        (fixture.dir / "other.sh").unlink()
        (fixture.dir / "other.sh").symlink_to("release.sh")
        git(fixture.dir, "add", "other.sh")
        git(fixture.dir, "commit", "-q", "-m", "link")
        self.assertIn("not a tracked regular executable file", fixture.run("tree").stderr)

    def test_guarded_may_be_empty_since_the_fixed_set_is_always_guarded(self):
        result = ScriptFixture(self, GOOD_GATE.replace('[".github", "harness"]', "[]")).run("tree")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_usage(self):
        result = ScriptFixture(self, GOOD_GATE).run("frobnicate")
        self.assertEqual(result.returncode, 1)
        self.assertIn("usage: ./dev gate", result.stderr)


@unittest.skipUnless(any(os.access(p, os.X_OK) for p in MISE_LOCATIONS), "mise not in a fixed location")
class CleanReRunTest(unittest.TestCase):
    """The strict re-run of a release, through the real mise."""

    def test_wrong_verb_is_refused(self):
        result = ScriptFixture(self, GOOD_GATE).run("release", "apply")
        self.assertEqual(result.returncode, 1)
        self.assertIn("releases with ./dev deploy, not ./dev apply", result.stderr)

    def test_inherited_variables_are_dropped(self):
        """Reaching the token check means the second stage found no foreign variable."""
        result = ScriptFixture(self, GOOD_GATE).run("release", "deploy", SSL_CERT_FILE="/tmp/x", GIT_SSH_COMMAND="x")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("no GitHub token", result.stderr)

    def test_hand_typed_second_stage_is_refused(self):
        result = ScriptFixture(self, GOOD_GATE).run("--stage2", "deploy", GIT_SSH_COMMAND="x")
        self.assertEqual(result.returncode, 1)
        self.assertIn("GIT_SSH_COMMAND is set after the clean re-run", result.stderr)

    def test_variable_named_in_keep_env_is_kept(self):
        fixture = ScriptFixture(self, GOOD_GATE + 'keep_env = ["READ_TOKEN"]\n')
        result = fixture.run("--stage2", "deploy", READ_TOKEN="x")
        self.assertIn("no GitHub token", result.stderr)


# --- The normal release entry point, end to end (Codex C22) -------------------------------------

# Stands in for gh as a real executable, since the strict re-run drops shell functions: `gh api
# [flags] <path> …` prints the file of that path in $GATE_TEST_FIX (with --paginate also its later
# pages, <file>.2, <file>.3 …) and logs the call in $GATE_TEST_FIX/order. Filters are ignored: the
# files hold what the filter would print.
FAKE_GH = r"""#!/bin/sh
[ "$1" = api ] || exit 1
shift
paginate="" path=""
while [ $# -gt 0 ]; do
  case "$1" in
    --paginate) paginate=1 ;;
    --jq | -q) shift ;;
    -*) ;;
    *) [ -n "$path" ] || path="$1" ;;
  esac
  shift
done
echo "gh $path" >>"$GATE_TEST_FIX/order"
f="$GATE_TEST_FIX/$(printf '%s' "$path" | tr '/?&=' '____')"
[ -f "$f" ] || exit 1
cat "$f"
n=2
while [ -n "$paginate" ] && [ -f "$f.$n" ]; do cat "$f.$n"; n=$((n + 1)); done
"""

RELEASE_TOML = """profile = "live-config"
tools = ["gh"]
check = "sh check.sh"
[gate]
repo = "o/r"
merger = "pa"
verb = "deploy"
release = "release.sh"
ci = "check-runs"
checks_app = "github-actions"
required = ["ci"]
guarded = ["guarded"]
keep_env = ["MISE_DATA_DIR", "GATE_TEST_FIX"]
"""


def git_auth_env(token="fake-token"):
    """The GIT_CONFIG_* entries and GH_TOKEN exactly as gh-token.sh exports them."""
    out = subprocess.run(
        ["bash", "-c", f'source "{ROOT}/harness/gh-token.sh"; export_git_auth "$1"; env -0', "-", token],
        env={"HOME": os.environ["HOME"], "PATH": SYSTEM_PATH}, capture_output=True, check=True,
    ).stdout.decode()
    pairs = (item.split("=", 1) for item in out.split("\0") if "=" in item)
    return {k: v for k, v in pairs if k == "GH_TOKEN" or k.startswith("GIT_CONFIG_")}


class ReleaseFixture:
    """A consumer with the real core, a bare origin, a harmless release command and check, and a
    fake gh that mise resolves (a fake python install in a private mise data directory, locked, so
    `mise exec --locked` puts it on PATH and `./dev check` finds it under mise)."""

    def __init__(self, test, toml=RELEASE_TOML):
        self.dir = Path(tempfile.mkdtemp(prefix="gate-e2e."))
        test.addCleanup(shutil.rmtree, self.dir, True)
        self.fix, self.data, self.state = self.dir / "gh", self.dir / "mise-data", self.dir / "mise-state"
        self.fix.mkdir()
        fake_bin = self.data / "installs" / "python" / "9.9.9" / "bin"
        fake_bin.mkdir(parents=True)
        (fake_bin / "gh").write_text(FAKE_GH)
        (fake_bin / "gh").chmod(0o755)
        self.origin, self.work = self.dir / "origin.git", self.dir / "work"
        git(self.dir, "init", "-q", "--bare", "-b", "main", str(self.origin))
        git(self.dir, "clone", "-q", str(self.origin), str(self.work))
        git(self.work, "checkout", "-q", "-b", "main")
        (self.work / "harness").mkdir()
        for name in ("gate", "conf.awk", "dev", "gh-token.sh", "check-pins", "check-dependabot", "check-bindings"):
            shutil.copy2(ROOT / "harness" / name, self.work / "harness" / name)
        shutil.copytree(ROOT / "harness" / "githooks", self.work / "harness" / "githooks")
        # The guard bindings, as in the workshop, so that `./dev check`'s binding check (24g F5) passes.
        shutil.copytree(ROOT / "harness" / "bindings", self.work / "harness" / "bindings")
        for name in (".claude/settings.json", ".codex/hooks.json", ".agents/hooks.json"):
            (self.work / name).parent.mkdir(exist_ok=True)
            shutil.copy2(ROOT / name, self.work / name)
        shutil.copy2(ROOT / "dev", self.work / "dev")
        git(self.work, "config", "core.hooksPath", "harness/githooks")  # as `./dev setup` leaves it
        files = {
            "harness.toml": toml,
            "mise.toml": '[tools]\npython = "9.9.9"\n',
            "mise.lock": 'lockfile_version = 4\n\n[[tools.python]]\nversion = "9.9.9"\nbackend = "core:python"\nspecifiers = ["9.9.9"]\n',
            ".gitignore": "mise.local.toml\n",
            "check.sh": 'echo "check GH_TOKEN=${GH_TOKEN:-unset} GIT_CONFIG_COUNT=${GIT_CONFIG_COUNT:-unset}" >>"$GATE_TEST_FIX/order"\n',
            "release.sh": '#!/bin/sh\necho "release $GATE_SHA GH_TOKEN=${GH_TOKEN:-unset} args=$*" >>"$GATE_TEST_FIX/order"\nexit 0\n',
            "guarded": "v1\n",
            "a.txt": "a\n",
        }
        for name, text in files.items():
            (self.work / name).write_text(text)
        (self.work / "release.sh").chmod(0o755)
        self.first = self.commit("first")
        subprocess.run(
            [next(m for m in MISE_LOCATIONS if os.access(m, os.X_OK)), "trust", str(self.work / "mise.toml")], env={**os.environ, "MISE_STATE_DIR": str(self.state)},
            capture_output=True, check=True,
        )

    def commit(self, message):
        """Stands in for a PR merged on GitHub, so the clone's own hooks do not apply."""
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "--no-verify", "-m", message)
        git(self.work, "push", "-q", "--no-verify", "origin", "HEAD:main")
        git(self.work, "fetch", "-q", "origin")
        return git(self.work, "rev-parse", "HEAD")

    def gh(self, path, text):
        (self.fix / fix_name(path)).write_text(text)

    def github_ok(self, sha, pr=7, merger="pa"):
        """GitHub answers for a commit that is green and the merge commit of PR `pr`, by `merger`."""
        self.gh("repos/o/r/commits/main", sha + "\n")
        self.gh(f"repos/o/r/commits/{sha}/check-runs?per_page=100", "ci\tgithub-actions\tcompleted\tsuccess\n")
        self.gh(f"repos/o/r/commits/{sha}/pulls?per_page=100", f"{pr}\n")
        self.gh(f"repos/o/r/pulls/{pr}", merger + "\n")

    def set_last(self, sha):
        record = self.work / ".git" / "dev-deploy"
        record.mkdir(exist_ok=True)
        (record / "last").write_text(sha + "\n")

    def release(self, *args, **extra):
        env = {
            "HOME": os.environ["HOME"], "PATH": SYSTEM_PATH, "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
            "MISE_STATE_DIR": str(self.state), "MISE_DATA_DIR": str(self.data), "GATE_TEST_FIX": str(self.fix),
            **git_auth_env(), **extra,
        }
        return subprocess.run(
            [str(self.work / "dev"), "deploy", *args], cwd=self.work, env=env,
            capture_output=True, text=True, timeout=120, start_new_session=True,
        )

    def order(self):
        path = self.fix / "order"
        return path.read_text().splitlines() if path.exists() else []


@unittest.skipUnless(any(os.access(p, os.X_OK) for p in MISE_LOCATIONS), "mise not in a fixed location")
class EndToEndTest(unittest.TestCase):
    def setUp(self):
        self.f = ReleaseFixture(self)
        self.f.set_last(self.f.first)
        (self.f.work / "a.txt").write_text("b\n")
        self.sha = self.f.commit("second")
        self.f.github_ok(self.sha)

    def test_release_runs_checks_first_and_repository_code_without_token(self):
        result = self.f.release("--mode", "x")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"released {self.sha[:12]}", result.stdout)
        order = self.f.order()
        first_repo_code = next(i for i, line in enumerate(order) if not line.startswith("gh "))
        self.assertTrue(all(not line.startswith("gh ") for line in order[first_repo_code:]), order)
        self.assertEqual(order[first_repo_code], "check GH_TOKEN=unset GIT_CONFIG_COUNT=unset")
        self.assertEqual(order[-1], f"release {self.sha} GH_TOKEN=unset args=--mode x")
        last = (self.f.work / ".git" / "dev-deploy" / "last").read_text().strip()
        self.assertEqual(last, self.sha)

    def trusted_config(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        mise = next(m for m in MISE_LOCATIONS if os.access(m, os.X_OK))
        subprocess.run([mise, "trust", str(path)], env={**os.environ, "MISE_STATE_DIR": str(self.f.state)},
                       capture_output=True, check=True)

    def test_env_section_in_a_parent_directory_is_refused(self):
        """K10: GH_TOKEN passes stage 2 by name, so a mise [env] above the repository could set it."""
        self.trusted_config(self.f.dir / "mise.toml", '[env]\nGH_TOKEN = "planted"\n')
        result = self.f.release()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("the mise configuration sets variables: GH_TOKEN", result.stderr)
        self.assertEqual(self.f.order(), [])

    def test_env_section_in_the_global_configuration_is_refused(self):
        home = self.f.dir / "home"
        (home / ".config" / "mise").mkdir(parents=True)
        (home / ".config" / "mise" / "config.toml").write_text('[env]\nHTTPS_PROXY = "http://planted.invalid"\n')
        # The gate also looks for mise in ~/.local/bin (where CI installs it): keep it findable.
        (home / ".local" / "bin").mkdir(parents=True)
        (home / ".local" / "bin" / "mise").symlink_to(next(m for m in MISE_LOCATIONS if os.access(m, os.X_OK)))
        result = self.f.release(HOME=str(home))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("the mise configuration sets variables: HTTPS_PROXY", result.stderr)

    def test_path_entry_from_mise_configuration_is_refused(self):
        self.trusted_config(self.f.dir / "mise.toml", '[env]\n_.path = ["/planted/bin"]\n')
        result = self.f.release()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("adds /planted/bin to PATH", result.stderr)

    def test_git_entries_other_than_the_token_scripts_are_refused(self):
        cases = {
            "altered helper": {"GIT_CONFIG_VALUE_0": "osxkeychain"},
            "extra entry": {"GIT_CONFIG_COUNT": "4", "GIT_CONFIG_KEY_3": "http.proxy", "GIT_CONFIG_VALUE_3": "http://planted.invalid"},
        }
        for name, extra in cases.items():
            with self.subTest(name):
                result = self.f.release(**extra)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("not exactly the ones gh-token.sh sets", result.stderr)

    def test_missing_git_entries_are_refused(self):
        env = {k: v for k, v in git_auth_env().items() if k == "GH_TOKEN"}
        result = subprocess.run(
            [str(self.f.work / "dev"), "deploy"], cwd=self.f.work, capture_output=True, text=True, timeout=120,
            start_new_session=True,
            env={"HOME": os.environ["HOME"], "PATH": SYSTEM_PATH, "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
                 "MISE_STATE_DIR": str(self.f.state), "MISE_DATA_DIR": str(self.f.data), "GATE_TEST_FIX": str(self.f.fix), **env},
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("not exactly the ones gh-token.sh sets", result.stderr)

    def test_release_without_baseline_names_the_recovery(self):
        (self.f.work / ".git" / "dev-deploy" / "last").unlink()
        result = self.f.release()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("./dev gate --baseline <sha>", result.stderr)

    def test_baseline_verb_reaches_the_gate_and_needs_a_terminal(self):
        result = subprocess.run(
            [str(self.f.work / "dev"), "gate", "--baseline", self.sha], cwd=self.f.work, capture_output=True,
            text=True, timeout=120, start_new_session=True,
            env={"HOME": os.environ["HOME"], "PATH": SYSTEM_PATH, "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
                 "MISE_STATE_DIR": str(self.f.state), "MISE_DATA_DIR": str(self.f.data)},
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("no terminal to confirm on", result.stderr)

    def test_refused_commit_runs_no_repository_code(self):
        self.f.github_ok(self.sha, merger="folotp-claude[bot]")
        result = self.f.release()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("not by 'pa'", result.stderr)
        self.assertFalse(any(not line.startswith("gh ") for line in self.f.order()), self.f.order())


if __name__ == "__main__":
    unittest.main()
