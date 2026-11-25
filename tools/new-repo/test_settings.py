"""Verify requests and read-back against a fake GitHub with realistic REST responses."""

import base64
import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from unittest.mock import patch

import settings

REPO = "example-owner/example-repo"
ROOT = f"repos/{REPO}"


class FakeGitHub:
    def __init__(self):
        upgrade = (403, {"message": "Upgrade to GitHub Pro or make this repository public."})
        self.records = {
            "user": (200, {"login": "example-owner"}),
            ROOT: (200, {
                "private": True, "full_name": REPO, "owner": {"login": "example-owner"},
                "permissions": {"admin": True},
                "allow_merge_commit": True, "allow_squash_merge": True,
                "allow_rebase_merge": False, "allow_auto_merge": False,
                "delete_branch_on_merge": False,
            }),
            f"{ROOT}/actions/workflows/mise-bump.yml": (404, {}),
            f"{ROOT}/actions/permissions": (200, {
                "enabled": True, "allowed_actions": "all", "sha_pinning_required": False,
            }),
            f"{ROOT}/actions/permissions/workflow": (200, {
                "default_workflow_permissions": "write", "can_approve_pull_request_reviews": False,
            }),
            f"{ROOT}/vulnerability-alerts": (404, {}),
            f"{ROOT}/automated-security-fixes": (200, {"enabled": True, "paused": False}),
            f"{ROOT}/immutable-releases": (200, {"enabled": True}),
            f"{ROOT}/branches/main/protection": upgrade,
            f"{ROOT}/rulesets?includes_parents=false&per_page=100": upgrade,
            f"{ROOT}/contents/.github/CODEOWNERS": (200, {
                "content": base64.b64encode(b"* @example-owner\n").decode(), "encoding": "base64",
            }),
        }
        self.calls = []

    def request(self, method, endpoint, payload=None):
        self.calls.append((method, endpoint, payload))
        if method == "GET":
            return deepcopy(self.records[endpoint])
        if endpoint.endswith("/vulnerability-alerts"):
            self.records[endpoint] = (204, None)
        else:
            self.records[endpoint][1].update(payload)
        return 204, None


class SettingsTest(unittest.TestCase):
    def run_cli(self, api, operation, *flags):
        with redirect_stdout(io.StringIO()) as report:
            status = settings.run([operation, REPO, "--profile", "plain", *flags], api=api)
        return status, report.getvalue()

    def test_check_reads_and_reports_private_plan_limits_without_writes(self):
        api = FakeGitHub()
        status, report = self.run_cli(api, "check")
        self.assertEqual(status, 1)
        self.assertTrue(all(call[0] == "GET" for call in api.calls))
        self.assertIn("requires a plan", report)
        self.assertIn("Grouped", report.title())
        self.assertNotIn("Limit issue creation", report)

    def test_apply_reconciles_drift_then_reads_back_and_second_run_writes_nothing(self):
        api = FakeGitHub()
        status, report = self.run_cli(api, "apply", "--yes", "--planned-mise-bump")
        self.assertEqual(status, 0, report)
        writes = [call for call in api.calls if call[0] != "GET"]
        self.assertEqual(writes, [
            ("PATCH", ROOT, {"allow_merge_commit": False, "delete_branch_on_merge": True}),
            ("PUT", f"{ROOT}/actions/permissions",
             {"enabled": True, "allowed_actions": "all", "sha_pinning_required": True}),
            ("PUT", f"{ROOT}/actions/permissions/workflow",
             {"default_workflow_permissions": "read", "can_approve_pull_request_reviews": True}),
            ("PUT", f"{ROOT}/vulnerability-alerts", None),
        ])
        self.assertGreater(api.calls.count(("GET", ROOT, None)), 1)
        api.calls.clear()
        status, _ = self.run_cli(api, "apply", "--yes", "--planned-mise-bump")
        self.assertEqual(status, 0)
        self.assertTrue(all(call[0] == "GET" for call in api.calls))

    def test_apply_without_bump_does_not_set_approval_policy(self):
        api = FakeGitHub()
        self.run_cli(api, "apply", "--yes")
        self.assertIn(
            ("PUT", f"{ROOT}/actions/permissions/workflow",
             {"default_workflow_permissions": "read", "can_approve_pull_request_reviews": False}),
            api.calls,
        )

    def test_dry_run_does_not_call_github(self):
        with patch.object(settings, "GitHub", side_effect=AssertionError("GitHub invoked")):
            status, report = self.run_cli(None, "apply", "--dry-run")
        self.assertEqual(status, 0)
        self.assertIn(f"GET {ROOT}/vulnerability-alerts", report)
        self.assertIn(f"PUT {ROOT}/vulnerability-alerts", report)

    def test_apply_requires_approval_and_the_personal_owner(self):
        api = FakeGitHub()
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.run_cli(api, "apply")
        self.assertEqual(api.calls, [])
        api.records["user"] = (200, {"login": "another-owner"})
        with self.assertRaisesRegex(settings.SettingsError, "personal repository owner"):
            self.run_cli(api, "apply", "--yes")
        self.assertEqual(api.calls, [("GET", "user", None)])

    def test_unexpected_permission_denial_is_an_error_before_any_write(self):
        api = FakeGitHub()
        api.records[f"{ROOT}/branches/main/protection"] = (403, {"message": "Resource not accessible"})
        with self.assertRaisesRegex(settings.SettingsError, "HTTP 403"):
            self.run_cli(api, "apply", "--yes")
        self.assertTrue(all(call[0] == "GET" for call in api.calls))

    def test_public_review_keeps_existing_strictness_and_checks_ruleset_actor(self):
        api = FakeGitHub()
        api.records[ROOT][1].update({
            "private": False, "pull_request_creation_policy": "collaborators_only",
            "security_and_analysis": {
                "secret_scanning": {"status": "enabled"},
                "secret_scanning_push_protection": {"status": "enabled"},
            },
        })
        endpoint = f"{ROOT}/branches/main/protection"
        api.records[endpoint] = (200, {
            "required_status_checks": {"strict": False, "contexts": ["Core checks"]},
            "enforce_admins": {"enabled": False},
            "required_pull_request_reviews": {
                "dismiss_stale_reviews": True, "require_code_owner_reviews": True,
                "required_approving_review_count": 1, "require_last_push_approval": True,
            },
            "required_conversation_resolution": {"enabled": True},
        })
        api.records[f"{ROOT}/rulesets?includes_parents=false&per_page=100"] = (200, [])
        review, _, _ = settings.inspect(api, REPO, settings.load_baseline())
        protection = next(body for _, resource, body in review.changes if resource == endpoint)
        self.assertFalse(protection["required_status_checks"]["strict"])
        self.assertTrue(protection["required_conversation_resolution"])
        self.assertTrue(protection["required_pull_request_reviews"]["require_last_push_approval"])
        ruleset = next(body for method, resource, body in review.changes if method == "POST")
        self.assertEqual(ruleset["bypass_actors"], [
            {"actor_type": "RepositoryRole", "actor_id": 5, "bypass_mode": "always"},
        ])

    def test_contents_drift_does_not_emit_file_contents_or_edit_them(self):
        api = FakeGitHub()
        path = f"{ROOT}/contents/.github/CODEOWNERS"
        api.records[path][1]["content"] = base64.b64encode(b"private-file-text").decode()
        status, report = self.run_cli(api, "apply", "--yes")
        self.assertEqual(status, 1)
        self.assertIn("pull request to correct", report)
        self.assertNotIn("private-file-text", report)
        self.assertTrue(all(method == "GET" for method, target, _ in api.calls if target == path))


if __name__ == "__main__":
    unittest.main()
