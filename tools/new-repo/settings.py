#!/usr/bin/env python3
"""Compare or apply the workshop GitHub settings baseline with an owner token."""

import argparse
import base64
import binascii
import json
import os
import re
import subprocess
import sys
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPOSITORY = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+")
# GitHub's base RepositoryRole IDs are the same for personal repositories.
REPOSITORY_ROLES = {"repository_admin": 5}
BOOL_ENDPOINTS = {
    "dependabot_alerts": "vulnerability-alerts",
    "dependabot_security_updates": "automated-security-fixes",
    "immutable_releases": "immutable-releases",
}
MISSING = object()


class SettingsError(Exception):
    pass


class GitHub:
    """Keep request data on stdin and avoid emitting authentication or full API responses."""

    def request(self, method, endpoint, payload=None):
        env = os.environ.copy()
        env.pop("GH_DEBUG", None)
        env["GH_PROMPT_DISABLED"] = "1"
        args = [
            "gh", "api", "--hostname", "github.com", "--include", "--method", method,
            "-H", "Accept: application/vnd.github+json",
            "-H", "X-GitHub-Api-Version: 2026-03-10", endpoint,
        ]
        body = None
        if payload is not None:
            args.extend(["--input", "-"])
            body = json.dumps(payload)
        result = subprocess.run(args, input=body, capture_output=True, text=True, env=env)
        headers, _, response = result.stdout.partition("\n\n")
        match = re.match(r"HTTP/\S+ (\d{3})\b", headers)
        if not match:
            raise SettingsError(f"{method} {endpoint}: no GitHub HTTP response.")
        status = int(match[1])
        if response.strip():
            try:
                document = json.loads(response)
            except json.JSONDecodeError:
                raise SettingsError(f"{method} {endpoint}: GitHub returned invalid JSON.") from None
        else:
            document = None
        return status, document


def expect(api, method, endpoint, accepted, payload=None):
    status, document = api.request(method, endpoint, payload)
    if status not in accepted:
        raise SettingsError(f"{method} {endpoint}: GitHub returned HTTP {status}.")
    return status, document


def load_baseline():
    return json.loads((HERE / "baseline.json").read_text(encoding="utf-8"))


def at(document, path):
    value = document
    for key in path.split("."):
        if not isinstance(value, dict) or key not in value:
            return MISSING
        value = value[key]
    return value


def assign(document, path, value):
    *parents, key = path.split(".")
    for parent in parents:
        document = document.setdefault(parent, {})
    document[key] = value


@dataclass
class Review:
    differences: list = field(default_factory=list)
    manual: list = field(default_factory=list)
    changes: list = field(default_factory=list)

    def compare(self, label, expected, found):
        if found is MISSING:
            raise SettingsError(f"GitHub did not return {label}. Check owner administration access.")
        if found == expected:
            return False
        self.differences.append((label, expected, found))
        return True

    def change(self, method, endpoint, payload=None):
        self.changes.append((method, endpoint, payload))


def grouped_fields(review, endpoint, category, fields, found, applies, method):
    changed = {}
    for path, field in fields.items():
        if not applies(field):
            continue
        value = field["value"]
        if review.compare(f"{category}.{path}", value, at(found, path)):
            assign(changed, path, value)
    if changed:
        if method == "PUT":
            # These endpoints express the whole repository-level policy. Retain the live
            # value of any conditional field that isn't part of this repository's baseline.
            payload = {key: found[key] for key in fields if key in found}
            payload.update(changed)
        else:
            payload = changed
        review.change(method, endpoint, payload)


def plan_unavailable(status, document, private):
    return (
        private and status == 403 and isinstance(document, dict)
        and "upgrade to github" in document.get("message", "").lower()
    )


def review_protection(api, review, root, fields, private, required_check):
    branch = fields["branch"]
    endpoint = f"{root}/branches/{branch}/protection"
    status, current = api.request("GET", endpoint)
    if plan_unavailable(status, current, private):
        review.manual.append(f"Branch protection for {branch} requires a plan that supports private repositories.")
        return
    if status in (404, 409):
        branch_status, _ = expect(api, "GET", f"{root}/branches/{branch}", {200, 404, 409})
        if branch_status != 200:
            review.manual.append(f"Check branch protection after the owner creates {branch}.")
            return
        current = {}
    elif status != 200:
        raise SettingsError(f"GET {endpoint}: GitHub returned HTTP {status}.")

    statuses = current.get("required_status_checks") or {}
    checks = [required_check] if required_check else fields["required_status_checks"]["value"]
    strict = fields.get("strict_status_checks", {}).get("value", statuses.get("strict"))
    reviews = current.get("required_pull_request_reviews") or {}
    policy = fields["required_pull_request_reviews"]["value"]

    def enabled(name):
        return (current.get(name) or {}).get("enabled", False)

    changed = [
        review.compare("branch.required_status_checks", sorted(checks), sorted(statuses.get("contexts", []))),
        review.compare("branch.enforce_admins", fields["enforce_admins"]["value"], enabled("enforce_admins")),
        review.compare("branch.pull_request_reviews", policy, {key: reviews.get(key) for key in policy}),
        review.compare("branch.allow_force_pushes", fields["allow_force_pushes"]["value"], enabled("allow_force_pushes")),
        review.compare("branch.allow_deletions", fields["allow_deletions"]["value"], enabled("allow_deletions")),
    ]
    if "strict_status_checks" in fields:
        changed.append(review.compare("branch.strict_status_checks", strict, statuses.get("strict")))
    if not any(changed):
        return
    if strict is None:
        review.manual.append("Set branch protection in Settings → Branches. The baseline needs a decision on strict status checks before it can create this rule.")
        return

    # The older protection endpoint requires a complete request. Preserve the existing
    # options outside the baseline so that correcting drift does not reset them.
    protection = {
        "required_status_checks": {"contexts": checks, "strict": strict},
        "enforce_admins": fields["enforce_admins"]["value"],
        "required_pull_request_reviews": {**policy},
        "allow_force_pushes": fields["allow_force_pushes"]["value"],
        "allow_deletions": fields["allow_deletions"]["value"],
        "restrictions": None,
    }
    if "checks" in statuses:
        apps = {check["context"]: check.get("app_id") for check in statuses["checks"]}
        protection["required_status_checks"]["checks"] = [
            {"context": context, **({"app_id": apps[context]} if apps.get(context) is not None else {})}
            for context in checks
        ]
        del protection["required_status_checks"]["contexts"]
    for option in ("require_last_push_approval", "dismissal_restrictions", "bypass_pull_request_allowances"):
        if option in reviews:
            value = reviews[option]
            if isinstance(value, dict):
                value = short_actors(value)
            protection["required_pull_request_reviews"][option] = value
    if current.get("restrictions"):
        protection["restrictions"] = short_actors(current["restrictions"])
    for option in (
        "required_linear_history", "block_creations", "required_conversation_resolution",
        "lock_branch", "allow_fork_syncing",
    ):
        if option in current:
            protection[option] = enabled(option)
    review.change("PUT", endpoint, protection)


def short_actors(value):
    return {
        key: [actor[attribute] for actor in value[key]]
        for key, attribute in (("users", "login"), ("teams", "slug"), ("apps", "slug"))
        if key in value
    }


def rules_payload(baseline):
    expected = deepcopy(baseline)
    expected["bypass_actors"] = [
        {"actor_type": "RepositoryRole", "actor_id": REPOSITORY_ROLES[rule["role"]], "bypass_mode": rule["mode"]}
        for rule in baseline["bypass_actors"]
    ]
    return expected


def comparable_rules(value):
    """GitHub's list ordering is immaterial. Ignore server-assigned fields at the top level."""
    return {
        **value,
        "conditions": {"ref_name": {key: sorted(items) for key, items in value["conditions"]["ref_name"].items()}},
        "rules": sorted(value["rules"], key=lambda rule: rule["type"]),
        "bypass_actors": sorted(value["bypass_actors"], key=lambda actor: json.dumps(actor, sort_keys=True)),
    }


def review_rules(api, review, root, spec, private):
    endpoint = f"{root}/rulesets"
    status, listing = api.request("GET", f"{endpoint}?includes_parents=false&per_page=100")
    if plan_unavailable(status, listing, private):
        review.manual.append("The release tag ruleset requires a plan that supports private repositories.")
        return
    if status != 200:
        raise SettingsError(f"GET {endpoint}: GitHub returned HTTP {status}.")
    if len(listing) == 100:
        raise SettingsError("Too many repository rulesets to verify a unique release tag ruleset.")
    expected = rules_payload(spec)
    matches = [rule["id"] for rule in listing if rule.get("name") == expected["name"]]
    if len(matches) > 1:
        raise SettingsError("More than one repository ruleset has the recorded name.")
    if not matches:
        review.compare("release tag ruleset", comparable_rules(expected), None)
        review.change("POST", endpoint, expected)
        return
    resource = f"{endpoint}/{matches[0]}"
    _, rule = expect(api, "GET", resource, {200})
    missing = expected.keys() - rule.keys()
    if missing:
        raise SettingsError(f"Release tag ruleset read-back is missing {', '.join(sorted(missing))}. Check owner access.")
    actual = {key: rule[key] for key in expected}
    if review.compare("release tag ruleset", comparable_rules(expected), comparable_rules(actual)):
        review.change("PUT", resource, expected)


def review_codeowners(api, review, root, file_spec, owner, before_first_push):
    status, document = expect(api, "GET", f"{root}/contents/.github/CODEOWNERS", {200, 404, 409})
    if status in (404, 409) and before_first_push:
        review.manual.append("Verify CODEOWNERS after the owner pushes the initial files.")
        return
    expected = file_spec["value"].format(repository_owner=owner).encode()
    try:
        content = base64.b64decode(document["content"]) if status == 200 and document["encoding"] == "base64" else None
    except (KeyError, binascii.Error):
        raise SettingsError("GitHub returned an invalid CODEOWNERS response.") from None
    if review.compare("CODEOWNERS matches the owner rule", True, content == expected):
        review.manual.append("Submit a regular pull request to correct the repository’s CODEOWNERS file.")


def inspect(api, repo, baseline, planned_bump=False, required_check=None):
    root = f"repos/{repo}"
    _, repository = expect(api, "GET", root, {200})
    if repository.get("full_name", "").casefold() != repo.casefold():
        raise SettingsError("GitHub resolved the request to a different repository.")
    if not repository.get("permissions", {}).get("admin"):
        raise SettingsError("The baseline read-back requires repository administration access.")
    private = repository["private"]
    api_fields = baseline["api"]
    review = Review()
    workflow = f"{root}/actions/workflows/mise-bump.yml"
    bump_status, _ = expect(api, "GET", workflow, {200, 404})
    bump = planned_bump or bump_status == 200

    def applies(item):
        return {
            None: True,
            "public": not private,
            "mise_bump_installed": bump,
        }[item.get("when")]

    grouped_fields(review, root, "repository", api_fields["repository"], repository, applies, "PATCH")
    for category, suffix in (("actions_permissions", "actions/permissions"),
                             ("workflow_permissions", "actions/permissions/workflow")):
        endpoint = f"{root}/{suffix}"
        _, found = expect(api, "GET", endpoint, {200})
        grouped_fields(review, endpoint, category, api_fields[category], found, applies, "PUT")
    for setting, suffix in BOOL_ENDPOINTS.items():
        endpoint = f"{root}/{suffix}"
        success = 204 if setting == "dependabot_alerts" else 200
        status, actual = expect(api, "GET", endpoint, {success, 404})
        expected = api_fields[setting]["value"]
        if setting == "dependabot_alerts":
            actual = status == 204
        elif setting == "immutable_releases":
            actual = at(actual, "enabled") if status == 200 else False
        elif status == 200:
            actual = {key: at(actual, key) for key in expected}
            if MISSING in actual.values():
                raise SettingsError("GitHub returned an incomplete Dependabot security updates status.")
        else:
            actual = None
        if review.compare(setting, expected, actual):
            review.change("PUT", endpoint)
    review_protection(api, review, root, api_fields["branch_protection"], private, required_check)
    review_rules(api, review, root, api_fields["tag_ruleset"]["value"], private)
    review_codeowners(api, review, root, baseline["files"][".github/CODEOWNERS"],
                      repository["owner"]["login"], planned_bump)
    return review, private, bump


def browser_checks(baseline, profile, private=None, bump=True):
    print("Browser checklist")
    checks = baseline["browser_checks"] + baseline["profiles"][profile]["browser_checks"]
    for check in checks:
        when = check.get("when")
        if (when == "public" and private is True) or (when == "mise_bump_installed" and not bump):
            continue
        qualifier = " (public repositories)" if when == "public" and private is None else ""
        print(f"  - {check['page']}{qualifier} — {check['value']}")


def dry_plan(repo, profile, baseline, apply=False, handoff=True):
    root = f"repos/{repo}"
    if apply:
        print("  GET user (verify the repository owner)")
    branch = baseline["api"]["branch_protection"]["branch"]
    checks = (
        (root, "PATCH"),
        (f"{root}/actions/workflows/mise-bump.yml", None),
        (f"{root}/actions/permissions", "PUT"),
        (f"{root}/actions/permissions/workflow", "PUT"),
        *((f"{root}/{suffix}", "PUT") for suffix in BOOL_ENDPOINTS.values()),
        (f"{root}/branches/{branch}/protection", "PUT if available and configured"),
        (f"{root}/contents/.github/CODEOWNERS", None),
    )
    for endpoint, method in checks:
        print(f"  GET {endpoint}")
        if apply and method:
            print(f"    If changed: {method} {endpoint}; then GET to verify")
    print(f"  If protection is absent: GET {root}/branches/{branch}")
    print(f"  GET {root}/rulesets?includes_parents=false&per_page=100")
    print(f"  If the named ruleset exists: GET {root}/rulesets/<id>")
    if apply:
        print(f"    If missing: POST {root}/rulesets; then GET to verify")
        print(f"    If changed: PUT {root}/rulesets/<id>; then GET to verify")
    browser_checks(baseline, profile)
    if handoff:
        print("done: settings plan printed")
        print("left for PA: approve the settings write and release the owner token")
        print("next: /dev-github-settings-fix-drift")


def report(review, private, bump, baseline, profile):
    for key, expected, actual in review.differences:
        print(f"  {key}: expected {json.dumps(expected, sort_keys=True)}, found {json.dumps(actual, sort_keys=True)}")
    for item in review.manual:
        print(f"  Check by hand: {item}")
    browser_checks(baseline, profile, private, bump)
    if review.differences:
        print(f"done: read-back found {len(review.differences)} difference(s)")
        print("left for PA: review the differences and complete the browser checklist")
        print("next: /dev-github-settings-fix-drift")
    else:
        print("done: verifiable settings match the baseline")
        print("left for PA: complete the browser checklist")
        print("next: /dev-repo-create")
    return bool(review.differences)


def run(argv=None, api=None):
    baseline = load_baseline()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("check", "apply"))
    parser.add_argument("repository", help="GitHub repository in owner/name form")
    parser.add_argument("--profile", required=True, choices=baseline["profiles"])
    parser.add_argument("--dry-run", action="store_true", help="print calls without contacting GitHub")
    parser.add_argument("--planned-mise-bump", action="store_true", help="include the bump workflow prepared for first push")
    parser.add_argument("--required-check", help="CI check name if this repository uses a different name than the starter")
    parser.add_argument("--yes", action="store_true", help="confirm the owner approved the settings write")
    args = parser.parse_args(argv)
    if not REPOSITORY.fullmatch(args.repository) or args.repository.split("/")[1] in (".", ".."):
        parser.error("repository must be a GitHub owner/name")
    applying = args.operation == "apply"
    if args.dry_run:
        dry_plan(args.repository, args.profile, baseline, applying)
        return 0
    if applying and not args.yes:
        parser.error("apply requires explicit owner approval (--yes)")
    if api is None:
        if not os.environ.get("GH_TOKEN"):
            raise SettingsError("Run through the owner token command in your own terminal.")
        api = GitHub()
    if applying:
        _, actor = expect(api, "GET", "user", {200})
        if actor.get("login", "").lower() != args.repository.split("/")[0].lower():
            raise SettingsError("Run the settings write as the personal repository owner.")
    review_args = (api, args.repository, baseline, args.planned_mise_bump, args.required_check)
    review, private, bump = inspect(*review_args)
    if applying and review.changes:
        for method, endpoint, payload in review.changes:
            expect(api, method, endpoint, {200, 201, 204}, payload)
        review, private, bump = inspect(*review_args)
    return int(report(review, private, bump, baseline, args.profile))


if __name__ == "__main__":
    try:
        sys.exit(run())
    except (SettingsError, OSError) as error:
        print(f"settings: {error}", file=sys.stderr)
        sys.exit(2)
