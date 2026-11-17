"""Tests of tools/specs/specs.py. No network: resolvers are injected, and `check` runs with sockets cut."""

import contextlib
import importlib.util
import io
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("specs", ROOT / "tools" / "specs" / "specs.py")
specs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(specs)

SHA1 = "a" * 40
SHA1_B = "b" * 40
SHA256 = "c" * 64
WATCH = {
    "schema_version": 1,
    "git": {"repo-one": "https://github.com/example/one.git"},
    "pages": {"page-one": "https://example.org/spec.md"},
}


def good_lock():
    return {
        "schema_version": 1,
        "sources": {
            "repo-one": {"kind": "git", "url": WATCH["git"]["repo-one"], "revision": SHA1},
            "page-one": {"kind": "page", "url": WATCH["pages"]["page-one"], "sha256": SHA256},
        },
    }


class Fixture:
    """A temporary watch list and lock, removed with the test."""

    def __init__(self, test, watch=WATCH, lock=None):
        self.dir = Path(tempfile.mkdtemp(prefix="specs-test."))
        test.addCleanup(lambda: __import__("shutil").rmtree(self.dir, True))
        self.watch = self.dir / "watch.json"
        self.lock = self.dir / "specs.lock"
        self.watch.write_text(json.dumps(watch))
        if lock is not None:
            self.lock.write_text(json.dumps(lock))


def run(function, *args, **kwargs):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = function(*args, **kwargs)
    return code, out.getvalue(), err.getvalue()


class RepositoryFilesTest(unittest.TestCase):
    def test_committed_lock_matches_committed_watch_list_without_network(self):
        """The check every local, PR and main run performs: it must not open a socket."""

        def no_network(*args, **kwargs):
            raise AssertionError("check tried to use the network")

        with mock.patch.object(socket.socket, "connect", no_network), mock.patch.object(
            socket, "getaddrinfo", no_network
        ), mock.patch.object(specs.subprocess, "run", no_network):
            code, out, err = run(specs.check)
        self.assertEqual(code, 0, err)
        self.assertIn("nothing contacted", out)

    def test_watch_list_covers_the_names_of_report_2_7(self):
        names = set(specs.load_watch())
        for expected in (
            "agents-md",
            "agent-skills-spec",
            "claude-skills",
            "claude-plugins",
            "claude-plugin-marketplaces",
            "codex-plugins",
            "codex-rules",
            "codex-hooks",
            "antigravity-rules",
            "antigravity-hooks",
        ):
            self.assertIn(expected, names)


class CheckTest(unittest.TestCase):
    def test_sound_lock_passes(self):
        f = Fixture(self, lock=good_lock())
        self.assertEqual(run(specs.check, f.watch, f.lock)[0], 0)

    def test_missing_lock_fails(self):
        f = Fixture(self)
        code, _, err = run(specs.check, f.watch, f.lock)
        self.assertEqual(code, 1)
        self.assertIn("specs.lock", err)

    def test_each_defect_is_reported(self):
        cases = {}
        lock = good_lock()
        del lock["sources"]["page-one"]
        cases["watched but not in the lock"] = lock
        lock = good_lock()
        lock["sources"]["extra"] = lock["sources"]["page-one"]
        cases["no longer watched"] = lock
        lock = good_lock()
        lock["sources"]["repo-one"]["revision"] = "XYZ"
        cases["not a lowercase hex digest"] = lock
        lock = good_lock()
        lock["sources"]["page-one"]["url"] = "https://example.org/other.md"
        cases["url differs from the watch list"] = lock
        lock = good_lock()
        lock["sources"]["page-one"]["kind"] = "git"
        cases["the watch list says"] = lock
        lock = good_lock()
        lock["sources"]["page-one"]["extra"] = 1
        cases["entry must have exactly"] = lock
        lock = good_lock()
        lock["schema_version"] = 2
        cases["schema_version must be 1"] = lock
        for message, bad in cases.items():
            with self.subTest(message):
                f = Fixture(self, lock=bad)
                code, _, err = run(specs.check, f.watch, f.lock)
                self.assertEqual(code, 1)
                self.assertIn(message, err)

    def test_bad_watch_lists_are_refused(self):
        cases = {
            "http page": {**WATCH, "pages": {"p": "http://example.org/x"}},
            "git over ssh": {**WATCH, "git": {"g": "git@github.com:a/b.git"}},
            "duplicate name": {**WATCH, "pages": {"repo-one": "https://example.org/x"}},
            "bad name": {**WATCH, "pages": {"Bad Name": "https://example.org/x"}},
            "empty": {"schema_version": 1, "git": {}, "pages": {}},
            "extra key": {**WATCH, "more": {}},
        }
        for label, watch in cases.items():
            with self.subTest(label):
                f = Fixture(self, watch=watch, lock=good_lock())
                self.assertEqual(run(specs.check, f.watch, f.lock)[0], 1)


class UpdateTest(unittest.TestCase):
    @staticmethod
    def resolver(revision=SHA1, digest=SHA256):
        return lambda watch: specs.resolve(
            watch, git=lambda url: revision, page=lambda url: digest
        )

    def test_unchanged_upstream_leaves_the_file_untouched(self):
        f = Fixture(self, lock=good_lock())
        before = f.lock.read_text()
        code, out, _ = run(specs.update, f.watch, f.lock, resolver=self.resolver())
        self.assertEqual(code, 0)
        self.assertIn("nothing moved", out)
        self.assertEqual(f.lock.read_text(), before)

    def test_moved_source_is_written_and_named_in_the_summary(self):
        f = Fixture(self, lock=good_lock())
        summary = f.dir / "summary.md"
        code, out, _ = run(
            specs.update, f.watch, f.lock, summary, resolver=self.resolver(revision=SHA1_B)
        )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(f.lock.read_text())["sources"]["repo-one"]["revision"], SHA1_B)
        self.assertIn("**repo-one**: revision `aaaaaaaaaaaa` -> `bbbbbbbbbbbb`", summary.read_text())
        self.assertNotIn("page-one", summary.read_text())
        self.assertEqual(run(specs.check, f.watch, f.lock)[0], 0)

    def test_first_run_adds_every_source(self):
        f = Fixture(self)
        code, out, _ = run(specs.update, f.watch, f.lock, resolver=self.resolver())
        self.assertEqual(code, 0)
        self.assertIn("**repo-one**: added", out)
        self.assertIn("**page-one**: added", out)

    def test_one_failing_source_writes_nothing(self):
        f = Fixture(self, lock=good_lock())
        before = f.lock.read_text()

        def failing(watch):
            def page(url):
                raise specs.SpecsError("cannot fetch " + url)

            return specs.resolve(watch, git=lambda url: SHA1_B, page=page)

        code, _, err = run(specs.update, f.watch, f.lock, resolver=failing)
        self.assertEqual(code, 1)
        self.assertIn("cannot fetch", err)
        self.assertEqual(f.lock.read_text(), before)

    def test_lock_text_is_stable(self):
        text = specs.render(good_lock())
        self.assertEqual(text, specs.render(json.loads(text)))
        self.assertTrue(text.endswith("}\n"))


if __name__ == "__main__":
    unittest.main()
