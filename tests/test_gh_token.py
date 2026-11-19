"""Tests of the token script (harness/gh-token.sh) that need no Keychain item and no network.

The script is sourced in bash (it runs `main` only when executed), so each test calls one function
or runs the script with arguments that stop before any key is read. Minting a real token is PA's
read-back (`gh-token.sh claude --read-only --info`), not a unit test. Needs `jq` on the system PATH.
"""

import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "harness" / "gh-token.sh"
SYSTEM_PATH = "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin"


def bash(script, **env):
    return subprocess.run(
        ["bash", "-c", f'source "{SCRIPT}"\n{script}'],
        env={"HOME": os.environ["HOME"], "PATH": SYSTEM_PATH, **env},
        capture_output=True, text=True, timeout=30,
    )


@unittest.skipUnless(shutil.which("jq", path=SYSTEM_PATH), "jq not on the system PATH")
class TokenRequestTest(unittest.TestCase):
    INSTALLATION = json.dumps({"id": 1, "permissions": {"contents": "write", "pull_requests": "write", "metadata": "read"}})

    def request(self, read_only):
        result = bash(f"token_request repo '{self.INSTALLATION}' '{read_only}'")
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_default_request_is_limited_to_the_repository(self):
        self.assertEqual(self.request(""), {"repositories": ["repo"]})

    def test_read_only_request_narrows_every_permission_to_read(self):
        self.assertEqual(
            self.request("1"),
            {"repositories": ["repo"], "permissions": {"contents": "read", "pull_requests": "read", "metadata": "read"}},
        )


class ArgumentsTest(unittest.TestCase):
    def run_script(self, *args):
        return subprocess.run(
            [str(SCRIPT), *args], env={"HOME": os.environ["HOME"], "PATH": SYSTEM_PATH},
            capture_output=True, text=True, timeout=30,
        )

    def test_unknown_option_prints_usage(self):
        result = self.run_script("claude", "--frobnicate")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--read-only", result.stderr)

    def test_printing_a_token_needs_print(self):
        """K24: no mode means usage, before any Keychain read; printing is asked for by name."""
        result = self.run_script("claude")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--print", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_two_modes_are_refused(self):
        self.assertEqual(self.run_script("claude", "--info", "--print").returncode, 2)

    def test_no_command_after_separator_is_refused(self):
        result = self.run_script("claude", "--read-only", "--")
        self.assertEqual(result.returncode, 1)
        self.assertIn("no command after --", result.stderr)


# The Keychain, the JWT and GitHub replaced by functions; every API call is logged in $LOG.
STUBS = r"""
security() { printf -- '-----BEGIN TEST' | openssl base64 -A; }
app_jwt() { printf jwt; }
resolve_repo() { printf o/r; }
api() {
  echo "$1 $2" >>"$LOG"
  case "$1 $2" in
    "GET /repos/"*) echo '{"id":1,"permissions":{"contents":"write"}}' ;;
    "POST "*) echo '{"token":"tok","expires_at":"x","permissions":{},"repository_selection":"selected"}' ;;
    "GET /app") echo '{"slug":"bot"}' ;;
    "GET /users/"*) echo '{"id":5}' ;;
  esac
}
"""


@unittest.skipUnless(shutil.which("jq", path=SYSTEM_PATH), "jq not on the system PATH")
class RevocationTest(unittest.TestCase):
    """K24: a minted token is revoked on any exit of --info and -- CMD, never in --print."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="gh-token-test."))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.log = self.dir / "log"

    def start(self, args):
        return subprocess.Popen(
            ["bash", "-c", f'source "{SCRIPT}"\n{STUBS}\nmain {args}'], cwd=self.dir,
            env={"HOME": os.environ["HOME"], "PATH": SYSTEM_PATH, "LOG": str(self.log)},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_command_exit_status_is_kept_and_token_revoked(self):
        process = self.start("claude -- sh -c 'exit 7'")
        process.communicate(timeout=30)
        self.assertEqual(process.returncode, 7)
        self.assertEqual(self.calls().count("DELETE /installation/token"), 1)

    def test_info_revokes_and_prints_no_token(self):
        process = self.start("claude --info")
        out, _ = process.communicate(timeout=30)
        self.assertEqual(process.returncode, 0)
        self.assertNotIn("tok", out)
        self.assertIn("DELETE /installation/token", self.calls())

    def test_interrupted_command_still_revokes(self):
        process = self.start("claude -- sh -c 'touch started; sleep 2'")
        deadline = time.monotonic() + 20
        while not (self.dir / "started").exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        process.send_signal(signal.SIGTERM)
        process.communicate(timeout=30)
        self.assertEqual(process.returncode, 143)
        self.assertIn("DELETE /installation/token", self.calls())

    def test_print_does_not_revoke(self):
        process = self.start("claude --print")
        out, _ = process.communicate(timeout=30)
        self.assertEqual((process.returncode, out), (0, "tok\n"))
        self.assertNotIn("DELETE /installation/token", self.calls())


class OwnerModeTest(unittest.TestCase):
    """24g C6: `owner -- CMD` with the Keychain item github-owner-token; `pa` is refused by name.
    The Keychain is a stub function: present or not, dialog allowed or denied."""

    CREATE = 'security add-generic-password -U -s github-owner-token -a folotp -T "" -w'

    def owner(self, security, args="owner -- sh -c 'echo ran GH_TOKEN=$GH_TOKEN'"):
        script = f'source "{SCRIPT}"\n{security}\nmain {args}'
        return subprocess.run(["bash", "-c", script], env={"HOME": os.environ["HOME"], "PATH": SYSTEM_PATH},
                              capture_output=True, text=True, timeout=30)

    def test_pa_is_refused_with_one_line_naming_owner(self):
        result = subprocess.run([str(SCRIPT), "pa", "--", "true"], env={"HOME": os.environ["HOME"], "PATH": SYSTEM_PATH},
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr.splitlines(), [
            "gh-token: the pa mode is now owner: run gh-token.sh owner -- CMD (Keychain item github-owner-token, see gh-token.md)"])

    def test_a_missing_item_prints_the_command_that_creates_it(self):
        # Every read fails: the attribute read (no -w) finds no item, as `security` exits 44.
        result = self.owner('security() { return 44; }')
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("ran", result.stdout)
        lines = result.stderr.splitlines()
        self.assertEqual(lines[0], "gh-token: no Keychain item github-owner-token for folotp")
        self.assertEqual(lines[1], "done: nothing ran")
        self.assertTrue(lines[2].startswith("left for PA: create it once in your own terminal") and self.CREATE in lines[2], lines[2])
        self.assertEqual(lines[3], "next: re-run the same command")

    def test_a_denied_dialog_runs_nothing_and_says_so(self):
        # The item exists (attributes readable), but the secret read is denied at the dialog.
        result = self.owner('security() { case " $* " in *" -w "*) return 128 ;; esac; }')
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("ran", result.stdout)
        self.assertIn("the owner token was not released: the Keychain dialog was denied or closed", result.stderr)
        self.assertIn("left for PA: click Allow (never Always Allow) in the dialog for github-owner-token", result.stderr)
        self.assertTrue(result.stderr.endswith("next: re-run the same command\n"), result.stderr)

    def test_a_released_token_reaches_the_command_only(self):
        result = self.owner('security() { case " $* " in *" -w "*) printf owner-tok ;; esac; }')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "ran GH_TOKEN=owner-tok\n")
        self.assertIn("releasing the owner token for one command", result.stderr)
        self.assertNotIn("owner-tok", result.stderr)

    def test_owner_needs_the_separator_and_a_command(self):
        self.assertIn("usage: gh-token.sh owner -- CMD...", self.owner("security() { return 0; }", "owner true").stderr)
        self.assertIn("owner needs a command after --", self.owner("security() { return 0; }", "owner --").stderr)


if __name__ == "__main__":
    unittest.main()
