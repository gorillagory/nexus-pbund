import os
import re
import subprocess


GIT_TIMEOUT_SECONDS = 5
MAX_OUTPUT_CHARS = 12000
MAX_DIFF_CHARS = 20000
MAX_TAGS = 40
MAX_COMMITS = 20
MAX_CHANGED_FILES = 120
SECRET_TEXT_PATTERN = re.compile(
    r"(?is)(-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----|"
    r"authorization\s*[:=]\s*bearer\s+[A-Za-z0-9._~+/=-]+|"
    r"bearer\s+[A-Za-z0-9._~+/=-]+|"
    r"(?:api[_ -]?key|token|secret|webhook[_ -]?secret|password|passwd|pwd)\s*[:=]\s*[^\s'\"`]+|"
    r"sk-[A-Za-z0-9_-]{8,}|AIza[0-9A-Za-z_-]{20,})"
)


def redact_git_output(value):
    if not value:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return SECRET_TEXT_PATTERN.sub("[redacted]", str(value))


def bounded_output(value, limit=MAX_OUTPUT_CHARS):
    redacted = redact_git_output(value)
    if len(redacted) <= limit:
        return redacted
    return "{}\n[output truncated to {} characters]".format(redacted[:limit], limit)


def _repo_path(repo_dir):
    return os.path.abspath(os.path.expanduser(str(repo_dir)))


def _clamp_limit(value, default, maximum):
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(1, min(number, maximum))


def run_read_only_git(repo_dir, args, timeout=GIT_TIMEOUT_SECONDS, limit=MAX_OUTPUT_CHARS):
    if not isinstance(args, (list, tuple)):
        return {
            "ok": False,
            "returncode": -1,
            "stdout": "",
            "stderr": "Git arguments must be a list.",
        }

    try:
        result = subprocess.run(
            ["git"] + list(args),
            cwd=_repo_path(repo_dir),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": bounded_output(result.stdout or "", limit=limit),
            "stderr": bounded_output(result.stderr or "", limit=limit),
        }
    except (OSError, subprocess.TimeoutExpired) as exception:
        return {
            "ok": False,
            "returncode": -1,
            "stdout": "",
            "stderr": bounded_output(str(exception), limit=limit),
        }


def _lines(result, limit=None):
    values = [line for line in (result.get("stdout") or "").splitlines() if line.strip()]
    return values[:limit] if limit is not None else values


def _parse_changed_files(status_output):
    files = []
    for line in (status_output or "").splitlines():
        if not line.strip():
            continue
        status = line[:2].strip() or line[:1].strip()
        path = line[3:].strip() if len(line) > 3 else ""
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        if path:
            files.append({"status": status, "path": bounded_output(path, limit=500)})
    return files[:MAX_CHANGED_FILES]


def get_branch(repo_dir):
    result = run_read_only_git(repo_dir, ["branch", "--show-current"])
    branch = (result.get("stdout") or "").strip()
    if not branch:
        head = run_read_only_git(repo_dir, ["rev-parse", "--short", "HEAD"])
        branch = "detached@{}".format((head.get("stdout") or "").strip() or "unknown")
    return {"branch": branch, "result": result}


def get_status(repo_dir):
    result = run_read_only_git(repo_dir, ["status", "--short"])
    changed_files = _parse_changed_files(result.get("stdout", ""))
    return {
        "is_dirty": bool(changed_files),
        "changed_file_count": len(changed_files),
        "changed_files": changed_files,
        "status_output": result.get("stdout", ""),
        "status_error": result.get("stderr", ""),
        "ok": result.get("ok", False),
    }


def get_recent_commits(repo_dir, limit=MAX_COMMITS):
    limit = _clamp_limit(limit, MAX_COMMITS, MAX_COMMITS)
    result = run_read_only_git(
        repo_dir,
        ["log", "--oneline", "--decorate", "-{}".format(limit)],
    )
    return {"commits": _lines(result, limit=MAX_COMMITS), "result": result}


def get_recent_baseline_tags(repo_dir, limit=MAX_TAGS):
    limit = _clamp_limit(limit, MAX_TAGS, MAX_TAGS)
    result = run_read_only_git(
        repo_dir,
        ["tag", "--sort=-creatordate", "--list", "nexus-*baseline-*"],
    )
    return {"tags": _lines(result, limit=limit), "result": result}


def get_changes(repo_dir):
    status = get_status(repo_dir)
    diff_stat = run_read_only_git(repo_dir, ["diff", "--stat"])
    name_only = run_read_only_git(repo_dir, ["diff", "--name-only"])
    return {
        **status,
        "diff_stat": diff_stat.get("stdout", ""),
        "diff_stat_error": diff_stat.get("stderr", ""),
        "diff_name_only": _lines(name_only, limit=MAX_CHANGED_FILES),
        "diff_name_only_error": name_only.get("stderr", ""),
    }


def get_diff_preview(repo_dir, limit=MAX_DIFF_CHARS):
    limit = _clamp_limit(limit, 12000, MAX_DIFF_CHARS)
    result = run_read_only_git(repo_dir, ["diff", "--no-ext-diff"], limit=limit)
    preview = result.get("stdout", "")
    return {
        "diff": preview,
        "is_truncated": "[output truncated to " in preview,
        "max_chars": limit,
        "stderr": result.get("stderr", ""),
        "ok": result.get("ok", False),
    }


def get_git_explorer_summary(repo_dir):
    branch = get_branch(repo_dir)
    changes = get_changes(repo_dir)
    commits = get_recent_commits(repo_dir, limit=MAX_COMMITS)
    tags = get_recent_baseline_tags(repo_dir, limit=MAX_TAGS)
    return {
        "branch": branch.get("branch"),
        "is_dirty": changes.get("is_dirty"),
        "changed_file_count": changes.get("changed_file_count"),
        "changed_files": changes.get("changed_files", []),
        "diff_stat": changes.get("diff_stat", ""),
        "diff_stat_error": changes.get("diff_stat_error", ""),
        "recent_commits": commits.get("commits", []),
        "recent_baseline_tags": tags.get("tags", []),
        "is_git_repo": changes.get("ok") or bool(branch.get("branch")),
    }
