import os
import subprocess


def run_git_command(repo_dir, args, timeout=10):
    if not isinstance(args, (list, tuple)):
        return {
            "ok": False,
            "returncode": -1,
            "stdout": "",
            "stderr": "Git arguments must be a list.",
        }

    try:
        cwd = os.path.abspath(os.path.expanduser(str(repo_dir)))
        result = subprocess.run(
            ["git"] + list(args),
            cwd=cwd,
            shell=False,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout or "",
            "stderr": result.stderr or "",
        }
    except (OSError, subprocess.TimeoutExpired) as exception:
        return {
            "ok": False,
            "returncode": -1,
            "stdout": "",
            "stderr": str(exception),
        }


def get_git_status(repo_dir):
    return run_git_command(repo_dir, ["status", "--short"], timeout=10)


def get_git_diff_stat(repo_dir):
    return run_git_command(repo_dir, ["diff", "--stat"], timeout=10)


def get_changed_files(repo_dir):
    result = get_git_status(repo_dir)
    files = []
    for line in result.get("stdout", "").splitlines():
        if not line.strip():
            continue
        status = line[:2].strip() or line[:1].strip()
        path = line[3:].strip() if len(line) > 3 else ""
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        if path:
            files.append({"status": status, "path": path})
    return files


def summarize_git_changes(repo_dir):
    status = get_git_status(repo_dir)
    diff_stat = get_git_diff_stat(repo_dir)
    changed_files = get_changed_files(repo_dir)
    return {
        "status_output": status.get("stdout", ""),
        "status_error": status.get("stderr", ""),
        "diff_stat": diff_stat.get("stdout", ""),
        "diff_stat_error": diff_stat.get("stderr", ""),
        "changed_files": changed_files,
        "is_dirty": bool(changed_files),
        "is_git_repo": bool(status.get("ok") or "not a git repository" not in status.get("stderr", "").lower()),
    }
