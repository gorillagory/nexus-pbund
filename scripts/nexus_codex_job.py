import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import uuid


PROJECT_ROOT = Path(__file__).resolve().parents[1]
JOB_ROOT = Path("/tmp/nexus-codex-jobs")
MAX_JOB_NAME_LENGTH = 60
MAX_PROMPT_BYTES = 512 * 1024
MAX_STATUS_CHARS = 2000
MAX_TAIL_BYTES = 128 * 1024
MAX_LIST_JOBS = 50
JOB_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,60}$")
SECRET_TEXT_PATTERN = re.compile(
    r"(?is)(-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----|"
    r"authorization\s*[:=]\s*bearer\s+[A-Za-z0-9._~+/=-]+|"
    r"bearer\s+[A-Za-z0-9._~+/=-]+|"
    r"(?:api[_ -]?key|token|secret|webhook[_ -]?secret|password|passwd|pwd)\s*[:=]\s*[^\s'\"`]+|"
    r"sk-[A-Za-z0-9_-]{8,}|AIza[0-9A-Za-z_-]{20,})"
)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def redact_text(value):
    if value is None:
        return ""
    return SECRET_TEXT_PATTERN.sub("[redacted]", str(value))


def bounded_text(value, limit=MAX_STATUS_CHARS):
    text = redact_text(value)
    if len(text) <= limit:
        return text
    return "{}\n[output truncated to {} characters]".format(text[:limit], limit)


def validate_job_name(name):
    if not isinstance(name, str) or not JOB_NAME_PATTERN.fullmatch(name):
        raise ValueError(
            "Job name must use only letters, numbers, dash, or underscore and be at most {} characters.".format(
                MAX_JOB_NAME_LENGTH
            )
        )
    return name


def validate_prompt_file(prompt_file):
    if not isinstance(prompt_file, str) or "\x00" in prompt_file:
        raise ValueError("Prompt file path is invalid.")
    prompt_path = Path(prompt_file).expanduser()
    try:
        prompt_path = prompt_path.resolve(strict=True)
    except OSError as exception:
        raise ValueError("Prompt file does not exist: {}".format(exception)) from exception
    if not prompt_path.is_file():
        raise ValueError("Prompt file must be a regular file.")
    stat_result = prompt_path.stat()
    if stat_result.st_size <= 0:
        raise ValueError("Prompt file must not be empty.")
    if stat_result.st_size > MAX_PROMPT_BYTES:
        raise ValueError("Prompt file is too large for this local job runner.")
    return prompt_path


def ensure_job_root():
    JOB_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(JOB_ROOT, 0o700)
    except OSError:
        pass


def make_job_id(name):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = uuid.uuid4().hex[:8]
    return "{}-{}-{}".format(name, stamp, suffix)


def validate_job_id(job_id):
    if not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", job_id):
        raise ValueError("Job id is invalid.")
    return job_id


def job_dir_for(job_id):
    validate_job_id(job_id)
    root = JOB_ROOT.resolve()
    job_dir = (JOB_ROOT / job_id).resolve()
    if job_dir != root and root in job_dir.parents:
        return job_dir
    raise ValueError("Job id resolves outside the job root.")


def status_path(job_dir):
    return job_dir / "status.json"


def read_status(job_dir):
    path = status_path(job_dir)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_status(job_dir, status):
    status = dict(status)
    status["updated_at"] = utc_now()
    tmp_path = job_dir / "status.json.tmp"
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(status, handle, indent=2, sort_keys=True)
        handle.write("\n")
    tmp_path.replace(status_path(job_dir))


def write_text(path, value):
    path.write_text(str(value), encoding="utf-8")


def read_pid(job_dir):
    try:
        return int((job_dir / "pid").read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def process_exists(pid):
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def proc_cmdline(pid):
    try:
        raw = Path("/proc") / str(pid) / "cmdline"
        return raw.read_bytes().replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
    except OSError:
        return ""


def proc_cwd(pid):
    try:
        return Path("/proc") / str(pid) / "cwd"
    except OSError:
        return None


def verify_managed_process(pid):
    if not process_exists(pid):
        return False, "process is not running"
    cmdline = proc_cmdline(pid)
    if cmdline and "nexus_codex_job.py" not in cmdline:
        return False, "recorded PID is not a nexus_codex_job.py process"
    cwd_link = Path("/proc") / str(pid) / "cwd"
    try:
        cwd = cwd_link.resolve(strict=True)
    except OSError:
        cwd = None
    if cwd is not None and cwd != PROJECT_ROOT:
        return False, "recorded PID cwd does not match project root"
    return True, ""


def create_job(args):
    name = validate_job_name(args.name)
    prompt_path = validate_prompt_file(args.prompt_file)
    ensure_job_root()

    job_id = make_job_id(name)
    job_dir = job_dir_for(job_id)
    job_dir.mkdir(mode=0o700)
    try:
        os.chmod(job_dir, 0o700)
    except OSError:
        pass

    shutil.copyfile(prompt_path, job_dir / "prompt.txt")
    started_at = utc_now()
    write_text(job_dir / "started_at", started_at)
    status = {
        "job_id": job_id,
        "name": name,
        "status": "queued",
        "project_root": str(PROJECT_ROOT),
        "job_dir": str(job_dir),
        "prompt_file": str(job_dir / "prompt.txt"),
        "combined_log": str(job_dir / "combined.log"),
        "runner_log": str(job_dir / "runner.log"),
        "report_expected": bool(args.expect_report),
        "expected_report_path": str(args.expect_report) if args.expect_report else "",
        "started_at": started_at,
        "finished_at": "",
        "returncode": None,
        "pid": None,
    }
    write_status(job_dir, status)

    runner_log = (job_dir / "runner.log").open("ab", buffering=0)
    try:
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "_run-job", "--job-id", job_id],
            cwd=str(PROJECT_ROOT),
            stdin=subprocess.DEVNULL,
            stdout=runner_log,
            stderr=runner_log,
            start_new_session=True,
            close_fds=True,
        )
    finally:
        runner_log.close()

    write_text(job_dir / "pid", process.pid)
    current_status = read_status(job_dir) or status
    current_status["pid"] = process.pid
    if current_status.get("status") in {"queued", "running"}:
        current_status["status"] = "running"
    write_status(job_dir, current_status)
    print("NEXUS_CODEX_JOB_ID={}".format(job_id))
    print("NEXUS_CODEX_JOB_DIR={}".format(job_dir))
    print("NEXUS_CODEX_JOB_LOG={}".format(job_dir / "combined.log"))
    print("NEXUS_CODEX_JOB_STATUS={}".format(job_dir / "status.json"))
    return 0


def run_job(args):
    job_dir = job_dir_for(args.job_id)
    status = read_status(job_dir)
    prompt_path = job_dir / "prompt.txt"
    combined_log_path = job_dir / "combined.log"
    write_text(job_dir / "pid", os.getpid())
    status.update(
        {
            "status": "running",
            "pid": os.getpid(),
            "runner_pid": os.getpid(),
            "started_at": status.get("started_at") or utc_now(),
            "command": ["codex", "exec", "[prompt omitted]"],
        }
    )
    write_status(job_dir, status)

    try:
        prompt = prompt_path.read_text(encoding="utf-8")
        env = os.environ.copy()
        env.update({"CI": "true", "DEBIAN_FRONTEND": "noninteractive", "PYTHONUNBUFFERED": "1"})
        with combined_log_path.open("a", encoding="utf-8") as combined_log:
            combined_log.write("NEXUS_CODEX_JOB_STARTED={}\n".format(utc_now()))
            combined_log.flush()
            result = subprocess.run(
                ["codex", "exec", prompt],
                cwd=str(PROJECT_ROOT),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=combined_log,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
            combined_log.write("\nNEXUS_CODEX_JOB_FINISHED={}\n".format(utc_now()))
            combined_log.flush()
        finished_at = utc_now()
        status.update(
            {
                "status": "succeeded" if result.returncode == 0 else "failed",
                "returncode": result.returncode,
                "finished_at": finished_at,
            }
        )
        write_text(job_dir / "finished_at", finished_at)
        write_status(job_dir, status)
        return result.returncode
    except Exception as exception:
        finished_at = utc_now()
        with combined_log_path.open("a", encoding="utf-8") as combined_log:
            combined_log.write("\nNEXUS_CODEX_JOB_ERROR={}\n".format(bounded_text(str(exception))))
        status.update(
            {
                "status": "error",
                "returncode": 1,
                "finished_at": finished_at,
                "error": bounded_text(str(exception)),
            }
        )
        write_text(job_dir / "finished_at", finished_at)
        write_status(job_dir, status)
        return 1


def refresh_status(job_dir):
    status = read_status(job_dir)
    if status.get("status") == "running":
        pid = status.get("pid") or read_pid(job_dir)
        if not process_exists(pid):
            status["status"] = "lost"
            status["returncode"] = None
            status["finished_at"] = status.get("finished_at") or utc_now()
            status["note"] = "Recorded runner PID is no longer active and no completion status was written."
            write_status(job_dir, status)
    return status


def print_status(status):
    fields = (
        "job_id",
        "name",
        "status",
        "pid",
        "started_at",
        "finished_at",
        "returncode",
        "job_dir",
        "combined_log",
        "report_expected",
        "expected_report_path",
        "note",
        "error",
    )
    for field in fields:
        if field in status and status.get(field) not in (None, ""):
            print("{}: {}".format(field, bounded_text(status.get(field))))


def show_status(args):
    job_dir = job_dir_for(args.job_id)
    if not job_dir.is_dir():
        raise ValueError("Job does not exist: {}".format(args.job_id))
    status = refresh_status(job_dir)
    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
    else:
        print_status(status)
    return 0


def list_jobs(args):
    ensure_job_root()
    job_dirs = [path for path in JOB_ROOT.iterdir() if path.is_dir()]
    job_dirs.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    limited = job_dirs[: args.limit]
    for job_dir in limited:
        status = refresh_status(job_dir)
        line = "{job_id} {status} {started_at} {name} {combined_log}".format(
            job_id=bounded_text(status.get("job_id") or job_dir.name, 120),
            status=bounded_text(status.get("status") or "unknown", 40),
            started_at=bounded_text(status.get("started_at") or "", 80),
            name=bounded_text(status.get("name") or "", 80),
            combined_log=bounded_text(status.get("combined_log") or str(job_dir / "combined.log"), 300),
        )
        print(line.rstrip())
    if len(job_dirs) > len(limited):
        print("[{} additional jobs omitted]".format(len(job_dirs) - len(limited)))
    return 0


def tail_job(args):
    job_dir = job_dir_for(args.job_id)
    log_path = job_dir / "combined.log"
    if not log_path.exists():
        print("No combined log exists yet: {}".format(log_path))
        return 0
    with log_path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - MAX_TAIL_BYTES), os.SEEK_SET)
        text = handle.read().decode("utf-8", errors="replace")
    lines = text.splitlines()[-args.lines :]
    print(bounded_text("\n".join(lines), limit=MAX_TAIL_BYTES))
    return 0


def stop_job(args):
    job_dir = job_dir_for(args.job_id)
    if not job_dir.is_dir():
        raise ValueError("Job does not exist: {}".format(args.job_id))
    status = refresh_status(job_dir)
    pid = status.get("pid") or read_pid(job_dir)
    ok, reason = verify_managed_process(pid)
    if not ok:
        raise ValueError("Refusing to stop job: {}".format(reason))
    os.killpg(pid, signal.SIGTERM)
    status.update({"status": "stopping", "stop_requested_at": utc_now()})
    write_status(job_dir, status)
    print("Stop requested for job {} pid {}".format(args.job_id, pid))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        description="Launch and inspect detached local Codex CLI jobs under /tmp/nexus-codex-jobs."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    start_parser = subparsers.add_parser("start", help="Start a detached Codex job from a prompt file.")
    start_parser.add_argument("--name", required=True, help="Job name: letters, numbers, dash, underscore.")
    start_parser.add_argument("--prompt-file", required=True, help="Prompt file to copy into the job directory.")
    start_parser.add_argument(
        "--expect-report",
        help="Optional report path the prompt is expected to produce; this runner records it only.",
    )
    start_parser.set_defaults(func=create_job)

    status_parser = subparsers.add_parser("status", help="Show bounded status for one job.")
    status_parser.add_argument("--job-id", required=True)
    status_parser.add_argument("--json", action="store_true")
    status_parser.set_defaults(func=show_status)

    tail_parser = subparsers.add_parser("tail", help="Print a redacted bounded tail of the combined job log.")
    tail_parser.add_argument("--job-id", required=True)
    tail_parser.add_argument("--lines", type=int, default=80)
    tail_parser.set_defaults(func=tail_job)

    list_parser = subparsers.add_parser("list", help="List recent jobs.")
    list_parser.add_argument("--limit", type=int, default=MAX_LIST_JOBS)
    list_parser.set_defaults(func=list_jobs)

    stop_parser = subparsers.add_parser("stop", help="Stop only the recorded managed PID for one job.")
    stop_parser.add_argument("--job-id", required=True)
    stop_parser.set_defaults(func=stop_job)

    run_parser = subparsers.add_parser("_run-job", help=argparse.SUPPRESS)
    run_parser.add_argument("--job-id", required=True)
    run_parser.set_defaults(func=run_job)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "lines", 1) <= 0:
        raise ValueError("--lines must be greater than zero.")
    if getattr(args, "limit", 1) <= 0 or getattr(args, "limit", 1) > MAX_LIST_JOBS:
        raise ValueError("--limit must be between 1 and {}.".format(MAX_LIST_JOBS))
    return args.func(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError) as exception:
        print("ERROR: {}".format(bounded_text(str(exception))), file=sys.stderr)
        sys.exit(2)
