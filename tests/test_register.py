"""The workaround register (docs/workaround-register.md) stays machine-readable.

Each `### <id>` entry needs the four fields (Reason, Exit condition, Probe, Last result), and the
probe it names must be an executable script under tools/probes/. Without this a register entry could
rot silently, which is the thing the register exists to prevent.
"""

import os
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTER = ROOT / "docs" / "workaround-register.md"
FIELDS = ("Reason", "Exit condition", "Probe", "Last result")


def entries(text):
    """Return {id: body} for every level-3 heading of the register."""
    parts = re.split(r"^### (\S+)\s*$", text, flags=re.M)
    return dict(zip(parts[1::2], parts[2::2]))


class RegisterTest(unittest.TestCase):
    def setUp(self):
        self.entries = entries(REGISTER.read_text(encoding="utf-8"))

    def test_first_three_entries_exist(self):
        for name in ("skills-symlink", "claude-md-stub", "plugin-zips"):
            self.assertIn(name, self.entries)

    def test_every_entry_has_the_four_fields(self):
        for name, body in self.entries.items():
            for field in FIELDS:
                self.assertRegex(body, rf"(?m)^- \*\*{field}:\*\* \S", f"{name}: missing {field}")

    def test_probe_is_an_executable_script(self):
        for name, body in self.entries.items():
            match = re.search(r"^- \*\*Probe:\*\* `(tools/probes/[\w.-]+\.sh)`", body, flags=re.M)
            self.assertIsNotNone(match, f"{name}: Probe must start with a `tools/probes/<name>.sh` path")
            path = ROOT / match.group(1)
            self.assertTrue(path.is_file(), f"{name}: {path} does not exist")
            self.assertTrue(os.access(path, os.X_OK), f"{name}: {path} is not executable")


if __name__ == "__main__":
    unittest.main()
