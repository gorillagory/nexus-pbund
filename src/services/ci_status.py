import json
import os
import re
import subprocess


WORKFLOW_PATH = ".github/workflows/nexus-preflight.yml"
PREFLIGHT_STATUS_PATH = ".nexus/preflight_status.json"
GIT_TIMEOUT_SECONDS = 10


def _run_git(repo_dir, args):
    try:
        result = subprocess.run(
            ["git"] + list(args),
            cwd=os.path.abspath(repo_dir),
            capture_output=True,
            text=True,
            check=False,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    output = (result.stdout or "").strip()
    return output or None


def get_current_branch(repo_dir):
    return _run_git(repo_dir, ["branch", "--show-current"])


def get_current_commit(repo_dir):
    return _run_git(repo_dir, ["rev-parse", "HEAD"])


def get_origin_url(repo_dir):
    return _run_git(repo_dir, ["remote", "get-url", "origin"])


def _sanitize_origin_url(origin_url):
    if not origin_url:
        return None
    sanitized = re.sub(r"(?i)(https?://)([^/@\s]+)@github\.com", r"\1github.com", origin_url)
    sanitized = re.sub(r"(?i)(https?://)([^/@\s]+)@", r"\1", sanitized)
    return sanitized


def parse_github_slug(origin_url):
    sanitized = _sanitize_origin_url(origin_url)
    if not sanitized:
        return None

    patterns = [
        r"^git@github\.com:(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+?)(?:\.git)?$",
        r"^ssh://git@github\.com/(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+?)(?:\.git)?$",
        r"^https?://github\.com/(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+?)(?:\.git)?/?$",
    ]
    for pattern in patterns:
        match = re.match(pattern, sanitized.strip())
        if match:
            return "{}/{}".format(match.group("owner"), match.group("repo"))
    return None


def get_workflow_present(repo_dir):
    return os.path.exists(os.path.join(os.path.abspath(repo_dir), WORKFLOW_PATH))


def get_github_actions_url(repo_dir):
    slug = parse_github_slug(get_origin_url(repo_dir))
    if not slug:
        return None
    return "https://github.com/{}/actions/workflows/nexus-preflight.yml".format(slug)


def get_local_preflight_status(repo_dir):
    status_path = os.path.join(os.path.abspath(repo_dir), PREFLIGHT_STATUS_PATH)
    try:
        with open(status_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    return {
        "status": payload.get("result") or "unknown",
        "returncode": payload.get("returncode"),
        "started_at": payload.get("started_at"),
        "finished_at": payload.get("finished_at"),
        "duration_seconds": payload.get("duration_seconds"),
        "output_excerpt": payload.get("output_excerpt") or "",
        "workflow_status_path": PREFLIGHT_STATUS_PATH,
    }


def summarize_ci_status(repo_dir):
    origin_url = get_origin_url(repo_dir)
    github_slug = parse_github_slug(origin_url)
    commit = get_current_commit(repo_dir)
    return {
        "branch": get_current_branch(repo_dir),
        "commit": commit,
        "commit_short": commit[:7] if commit else None,
        "origin_url_present": bool(origin_url),
        "github_slug": github_slug,
        "workflow_present": get_workflow_present(repo_dir),
        "workflow_path": WORKFLOW_PATH,
        "actions_url": "https://github.com/{}/actions/workflows/nexus-preflight.yml".format(github_slug)
        if github_slug
        else None,
        "local_preflight": get_local_preflight_status(repo_dir),
        "remote_ci": {
            "status": "unknown",
            "reason": "GitHub API integration not configured",
        },
    }
