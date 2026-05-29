import os
import re
import subprocess

from src.services.git_explorer import bounded_output, get_status, redact_git_output


PACKET_BRANCH_PATTERN = re.compile(r"^factory/packet-[0-9]{3}-[a-z0-9][a-z0-9-]{0,80}$")
PACKET_NUMBER_PATTERN = re.compile(r"^[0-9]{1,3}$")
SLUG_PATTERN = re.compile(r"[^a-z0-9]+")
GIT_TIMEOUT_SECONDS = 5


def _repo_path(repo_dir):
    return os.path.abspath(os.path.expanduser(str(repo_dir)))


def _clean_text(value, max_length=None):
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    value = value.strip()
    if max_length is not None:
        value = value[:max_length]
    return value


def slugify_packet_title(value):
    cleaned = _clean_text(value, 120).lower()
    slug = SLUG_PATTERN.sub("-", cleaned).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug[:80].strip("-") or "packet-work"


def build_packet_branch_name(packet_number, title):
    packet_text = _clean_text(packet_number, 3)
    if not PACKET_NUMBER_PATTERN.match(packet_text):
        raise ValueError("packet_number must be 1 to 3 digits.")
    number = int(packet_text)
    if number <= 0:
        raise ValueError("packet_number must be greater than zero.")
    return "factory/packet-{number:03d}-{slug}".format(
        number=number,
        slug=slugify_packet_title(title),
    )


def validate_packet_branch_name(branch_name):
    branch = _clean_text(branch_name, 140)
    unsafe_fragments = ("..", "@{", "\\", " ", "~", "^", ":", "?", "*", "[")
    if not branch:
        return False, "branch name is required."
    if branch.startswith("-"):
        return False, "branch name must not start with a dash."
    if branch.endswith(".lock"):
        return False, "branch name must not end with .lock."
    if any(fragment in branch for fragment in unsafe_fragments):
        return False, "branch name contains unsafe characters."
    if not PACKET_BRANCH_PATTERN.match(branch):
        return False, "branch name must match factory/packet-###-safe-slug."
    return True, None


def run_git(repo_dir, args, timeout=GIT_TIMEOUT_SECONDS):
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
            "stdout": bounded_output(result.stdout or ""),
            "stderr": bounded_output(result.stderr or ""),
        }
    except (OSError, subprocess.TimeoutExpired) as exception:
        return {
            "ok": False,
            "returncode": -1,
            "stdout": "",
            "stderr": bounded_output(str(exception)),
        }


def current_branch(repo_dir):
    result = run_git(repo_dir, ["branch", "--show-current"])
    return (result.get("stdout") or "").strip(), result


def branch_exists(repo_dir, branch_name):
    result = run_git(repo_dir, ["rev-parse", "--verify", "--quiet", "refs/heads/{}".format(branch_name)])
    return result.get("returncode") == 0


def packet_branch_status(repo_dir, packet_number=None, title=None):
    branch, branch_result = current_branch(repo_dir)
    status = get_status(repo_dir)
    suggested_branch = None
    validation_error = None
    if packet_number not in (None, "") or title not in (None, ""):
        try:
            suggested_branch = build_packet_branch_name(packet_number, title)
            valid, validation_error = validate_packet_branch_name(suggested_branch)
            if not valid:
                suggested_branch = None
        except ValueError as exception:
            validation_error = str(exception)

    return {
        "current_branch": redact_git_output(branch),
        "is_clean": not status.get("is_dirty"),
        "is_dirty": bool(status.get("is_dirty")),
        "changed_file_count": status.get("changed_file_count", 0),
        "changed_files": status.get("changed_files", []),
        "suggested_branch": suggested_branch,
        "validation_error": validation_error,
        "can_prepare": bool(
            suggested_branch
            and not validation_error
            and not status.get("is_dirty")
            and branch == "main"
        ),
        "branch_result": {
            "ok": branch_result.get("ok"),
            "stderr": branch_result.get("stderr", ""),
        },
    }


def prepare_packet_branch(repo_dir, packet_number, title, confirm_prepare=False):
    if confirm_prepare is not True:
        return {
            "ok": False,
            "message": "confirm_prepare=true is required.",
            "branch": None,
        }

    branch_name = build_packet_branch_name(packet_number, title)
    valid, error = validate_packet_branch_name(branch_name)
    if not valid:
        return {"ok": False, "message": error, "branch": None}

    branch, branch_result = current_branch(repo_dir)
    if branch_result.get("ok") is not True:
        return {"ok": False, "message": "current branch could not be read.", "branch": branch_name}
    if branch != "main":
        return {"ok": False, "message": "packet branch preparation must start from main.", "branch": branch_name}

    status = get_status(repo_dir)
    if status.get("is_dirty"):
        return {"ok": False, "message": "worktree must be clean before creating a packet branch.", "branch": branch_name}

    if branch_exists(repo_dir, branch_name):
        return {"ok": False, "message": "target packet branch already exists.", "branch": branch_name}

    result = run_git(repo_dir, ["switch", "-c", branch_name])
    if not result.get("ok"):
        return {
            "ok": False,
            "message": result.get("stderr") or "packet branch could not be created.",
            "branch": branch_name,
            "result": result,
        }

    return {
        "ok": True,
        "message": "packet branch prepared.",
        "branch": branch_name,
        "result": result,
    }
