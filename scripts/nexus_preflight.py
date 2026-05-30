import argparse
from datetime import datetime, timezone
import json
import os
import re
import shutil
import subprocess
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_COMMAND_TIMEOUT_SECONDS = 180
MAX_CAPTURE_CHARS = 6000
MAX_REPORT_CHARS = 60000
PACKET_VERIFY_PATTERN = re.compile(r"^verify_factory_packet_((?:\d{3})(?:_\d{3})*)\.py$")
SECRET_TEXT_PATTERN = re.compile(
    r"(?is)(-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----|"
    r"authorization\s*[:=]\s*bearer\s+[A-Za-z0-9._~+/=-]+|"
    r"bearer\s+[A-Za-z0-9._~+/=-]+|"
    r"(?:api[_ -]?key|token|secret|webhook[_ -]?secret|password|passwd|pwd)\s*[:=]\s*[^\s'\"`]+|"
    r"sk-[A-Za-z0-9_-]{8,}|AIza[0-9A-Za-z_-]{20,})"
)

PY_COMPILE_FILES = [
    "engine.py",
    "dashboard.py",
    "models.py",
    "database.py",
    "bundle.py",
    "ai_clients/base.py",
    "ai_clients/factory.py",
    "ai_clients/gemini_client.py",
    "ai_clients/openai_client.py",
    "model_registry.py",
    "task_router.py",
    "chat_session_store.py",
    "src/services/codex_runner.py",
    "src/services/cost_ledger.py",
    "src/services/discord_router.py",
    "src/services/work_packet_parser.py",
    "src/services/factory_events.py",
    "src/services/git_changes.py",
    "src/services/git_explorer.py",
    "src/services/inbox_triage_conversion.py",
    "src/services/orchestration_inbox.py",
    "src/services/operator_interventions.py",
    "src/services/operator_notifications.py",
    "src/services/operator_review_history.py",
    "src/services/packet_branch.py",
    "src/services/packet_drafting.py",
    "src/services/prompt_vault.py",
    "src/services/trusted_packets.py",
    "src/services/work_packet_readiness.py",
]

VERIFY_SCRIPTS = [
    "scripts/verify_watchdog_ignores.py",
    "scripts/verify_factory_packet_002_003_004.py",
    "scripts/verify_factory_packet_005.py",
    "scripts/verify_factory_packet_006.py",
    "scripts/verify_factory_packet_007.py",
    "scripts/verify_factory_packet_008.py",
    "scripts/verify_factory_packet_009.py",
    "scripts/verify_factory_execution_console.py",
    "scripts/verify_factory_schema_sync.py",
    "scripts/verify_factory_packet_011.py",
    "scripts/verify_factory_packet_012.py",
    "scripts/verify_factory_regression_suite.py",
    "scripts/verify_factory_packet_013.py",
]

QUICK_VERIFY_SCRIPTS = [
    "scripts/verify_factory_regression_suite.py",
    "scripts/verify_factory_packet_013.py",
]


def redact_preflight_output(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return SECRET_TEXT_PATTERN.sub("[redacted]", str(value))


def bounded_output(value, limit=MAX_CAPTURE_CHARS):
    text = redact_preflight_output(value)
    if len(text) <= limit:
        return text
    return "{}\n[output truncated to {} characters]".format(text[:limit], limit)


def run_command(command, label, timeout=DEFAULT_COMMAND_TIMEOUT_SECONDS):
    try:
        result = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
        return {
            "label": label,
            "command": list(command),
            "returncode": result.returncode,
            "stdout": result.stdout or "",
            "stderr": result.stderr or "",
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exception:
        stdout = exception.stdout or ""
        stderr = exception.stderr or ""
        timeout_message = "Command timed out after {} seconds.".format(timeout)
        if stderr:
            stderr = "{}\n{}".format(stderr, timeout_message)
        else:
            stderr = timeout_message
        return {
            "label": label,
            "command": list(command),
            "returncode": 124,
            "stdout": stdout,
            "stderr": stderr,
            "timed_out": True,
        }


def print_section(title):
    print("\n== {} ==".format(title))


def print_result(status, label, detail=None):
    line = "{}: {}".format(status, label)
    if detail:
        line = "{} - {}".format(line, detail)
    print(line)


def append_command_result(summary, result):
    summary.setdefault("commands", []).append(
        {
            "label": result.get("label"),
            "command": result.get("command", []),
            "returncode": result.get("returncode"),
            "timed_out": bool(result.get("timed_out")),
            "stdout": bounded_output(result.get("stdout", "")),
            "stderr": bounded_output(result.get("stderr", "")),
        }
    )


def existing_paths(paths):
    return [path for path in paths if os.path.exists(os.path.join(PROJECT_ROOT, path))]


def git_status_short():
    result = run_command(["git", "status", "--short"], "git status --short")
    return result, result["stdout"].strip()


def git_branch_name(summary=None):
    result = run_command(["git", "branch", "--show-current"], "git branch --show-current")
    if summary is not None:
        append_command_result(summary, result)
    return (result.get("stdout") or "").strip() if result["returncode"] == 0 else "unknown"


def normalize_packet_number(value):
    text = str(value or "").strip()
    if not re.fullmatch(r"\d{1,3}", text):
        raise ValueError("Packet must be a numeric value such as 34.")
    number = int(text)
    if number <= 0:
        raise ValueError("Packet must be greater than zero.")
    return number


def discover_packet_verifiers():
    scripts_dir = os.path.join(PROJECT_ROOT, "scripts")
    discovered = {}
    if not os.path.isdir(scripts_dir):
        return discovered
    for file_name in sorted(os.listdir(scripts_dir)):
        match = PACKET_VERIFY_PATTERN.fullmatch(file_name)
        if not match:
            continue
        rel_path = os.path.join("scripts", file_name)
        full_path = os.path.abspath(os.path.join(PROJECT_ROOT, rel_path))
        if not full_path.startswith(os.path.join(PROJECT_ROOT, "scripts") + os.sep):
            continue
        for packet_text in match.group(1).split("_"):
            packet_number = int(packet_text)
            discovered.setdefault(packet_number, []).append(rel_path)
    return discovered


def print_packet_checks():
    print_section("Packet Verifier Scripts")
    discovered = discover_packet_verifiers()
    if not discovered:
        print_result("SKIP", "packet verifiers", "none discovered")
        return
    for packet_number in sorted(discovered):
        paths = ", ".join(discovered[packet_number])
        print("Packet {:03d}: {}".format(packet_number, paths))


def run_packet_verification(summary, packet_number):
    print_section("Packet-Aware Checks")
    discovered = discover_packet_verifiers()
    scripts = discovered.get(packet_number, [])
    summary["packet"] = packet_number
    summary["packet_verifier_paths"] = scripts
    if not scripts:
        label = "packet {:03d} verifier".format(packet_number)
        print_result("FAIL", label, "not found")
        summary["checks"].append({"name": label, "status": "FAIL", "details": "not found"})
        return False

    ok = True
    for script in scripts:
        result = run_command([sys.executable, script], script)
        append_command_result(summary, result)
        if result["returncode"] == 0:
            print_result("PASS", script)
            summary["checks"].append({"name": script, "status": "PASS", "packet": packet_number})
            continue
        ok = False
        print_result("FAIL", script, "exit {}".format(result["returncode"]))
        if result["stdout"].strip():
            print(bounded_output(result["stdout"]).rstrip())
        if result["stderr"].strip():
            print(bounded_output(result["stderr"]).rstrip())
        summary["checks"].append({"name": script, "status": "FAIL", "packet": packet_number})
    return ok


def render_preflight_report(summary):
    lines = [
        "# Nexus Packet-Aware Preflight Report",
        "",
        "## Summary",
        "- Timestamp: `{}`".format(summary.get("timestamp")),
        "- Git branch: `{}`".format(bounded_output(summary.get("git_branch") or "unknown", limit=500)),
        "- Git status: `{}`".format(bounded_output(summary.get("initial_git_status") or "clean", limit=1000)),
        "- Selected packet: `{}`".format(
            "{:03d}".format(summary["packet"]) if summary.get("packet") else "none"
        ),
        "- Packet verifier path: `{}`".format(", ".join(summary.get("packet_verifier_paths") or []) or "none"),
        "- Final result: `{}`".format(summary.get("result")),
        "",
        "## Checks",
    ]
    for check_item in summary.get("checks", []):
        detail = check_item.get("details")
        line = "- `{}` - {}".format(check_item.get("status"), check_item.get("name"))
        if detail:
            line = "{} - {}".format(line, bounded_output(str(detail), limit=500))
        lines.append(line)
    lines.extend(["", "## Commands"])
    for command in summary.get("commands", []):
        command_text = " ".join(command.get("command") or [])
        lines.extend(
            [
                "### {}".format(command.get("label")),
                "- Command: `{}`".format(command_text),
                "- Return code: `{}`".format(command.get("returncode")),
                "- Timed out: `{}`".format(str(bool(command.get("timed_out"))).lower()),
                "",
                "Stdout:",
                "```text",
                bounded_output(command.get("stdout", "")) or "",
                "```",
                "",
                "Stderr:",
                "```text",
                bounded_output(command.get("stderr", "")) or "",
                "```",
                "",
            ]
        )
    lines.append("NEXUS_PACKET_PREFLIGHT_RESULT={}".format(summary.get("result")))
    report = "\n".join(lines)
    if len(report) <= MAX_REPORT_CHARS:
        return report
    footer = "\n\n[report truncated to {} characters]\nNEXUS_PACKET_PREFLIGHT_RESULT={}".format(
        MAX_REPORT_CHARS,
        summary.get("result"),
    )
    return "{}{}".format(report[:MAX_REPORT_CHARS], footer)


def write_preflight_report(summary, report_path):
    full_path = os.path.abspath(os.path.expanduser(report_path))
    if "\x00" in full_path:
        raise ValueError("Report path contains an invalid character.")
    repo_git_dir = os.path.join(PROJECT_ROOT, ".git")
    if full_path == repo_git_dir or full_path.startswith(repo_git_dir + os.sep):
        raise ValueError("Refusing to write a preflight report inside .git.")
    parent = os.path.dirname(full_path)
    if not parent or not os.path.isdir(parent):
        raise ValueError("Report parent directory does not exist: {}".format(parent))
    report = render_preflight_report(summary)
    with open(full_path, "w", encoding="utf-8") as handle:
        handle.write(report)
        handle.write("\n")
    return full_path


def iter_files(paths, suffixes):
    for rel_path in paths:
        full_path = os.path.join(PROJECT_ROOT, rel_path)
        if os.path.isfile(full_path):
            if full_path.endswith(suffixes):
                yield full_path
            continue
        if not os.path.isdir(full_path):
            continue
        for root, dirs, files in os.walk(full_path):
            dirs[:] = [
                directory
                for directory in dirs
                if directory not in {
                    ".git",
                    ".nexus",
                    ".codex",
                    "__pycache__",
                    ".pytest_cache",
                    ".mypy_cache",
                    ".ruff_cache",
                    "node_modules",
                    "venv",
                    ".venv",
                    ".postgres-data",
                }
            ]
            for file_name in files:
                full_file = os.path.join(root, file_name)
                if full_file.endswith(suffixes):
                    yield full_file


def contains_text(file_path, needle):
    try:
        with open(file_path, "r", encoding="utf-8") as handle:
            return needle in handle.read()
    except OSError:
        return False


def run_safety_scans(summary):
    print_section("Safety Scans")
    failed = False
    shell_assignment = "shell" + "=True"
    popen_name = "subprocess." + "Popen"
    raw_key_pattern = re.compile(r"data\.(gemini_api_key|openai_api_key|api_key|discord_ingest_secret)([^_A-Za-z0-9]|$)")

    checks = [
        (
            "no shell true assignment in Python safety surface",
            list(iter_files(["dashboard.py", "engine.py", "src"], (".py",))),
            lambda path: contains_text(path, shell_assignment),
        ),
        (
            "no subprocess popen in dashboard/services",
            list(iter_files(["dashboard.py", "src/services"], (".py",))),
            lambda path: contains_text(path, popen_name),
        ),
        (
            "no raw settings return",
            list(iter_files(["dashboard.py", "engine.py"], (".py",))),
            lambda path: contains_text(path, "return self.engine.settings"),
        ),
        (
            "no frontend raw API key reads",
            list(iter_files(["static/js"], (".js",))),
            lambda path: bool(raw_key_pattern.search(open(path, "r", encoding="utf-8").read())),
        ),
    ]

    for label, files, matcher in checks:
        matches = []
        for file_path in files:
            try:
                if matcher(file_path):
                    matches.append(os.path.relpath(file_path, PROJECT_ROOT))
            except OSError:
                matches.append(os.path.relpath(file_path, PROJECT_ROOT))
        if matches:
            failed = True
            print_result("FAIL", label, ", ".join(matches))
            summary["checks"].append({"name": label, "status": "FAIL", "details": matches})
        else:
            print_result("PASS", label)
            summary["checks"].append({"name": label, "status": "PASS", "details": []})

    return not failed


def run_py_compile(summary):
    print_section("Python Compile")
    files = existing_paths(PY_COMPILE_FILES)
    if not files:
        print_result("SKIP", "py_compile", "no files found")
        summary["checks"].append({"name": "py_compile", "status": "SKIP"})
        return True

    result = run_command([sys.executable, "-m", "py_compile"] + files, "py_compile")
    append_command_result(summary, result)
    if result["returncode"] == 0:
        print_result("PASS", "py_compile", "{} files".format(len(files)))
        summary["checks"].append({"name": "py_compile", "status": "PASS"})
        return True

    print_result("FAIL", "py_compile")
    if result["stdout"].strip():
        print(result["stdout"].rstrip())
    if result["stderr"].strip():
        print(result["stderr"].rstrip())
    summary["checks"].append({"name": "py_compile", "status": "FAIL"})
    return False


def run_verification_scripts(summary, quick=False):
    print_section("Verification Scripts")
    scripts = QUICK_VERIFY_SCRIPTS if quick else VERIFY_SCRIPTS
    ok = True
    for script in scripts:
        if not os.path.exists(os.path.join(PROJECT_ROOT, script)):
            print_result("SKIP", script, "missing")
            summary["checks"].append({"name": script, "status": "SKIP"})
            continue
        result = run_command([sys.executable, script], script)
        append_command_result(summary, result)
        if result["returncode"] == 0:
            print_result("PASS", script)
            summary["checks"].append({"name": script, "status": "PASS"})
            continue
        ok = False
        print_result("FAIL", script, "exit {}".format(result["returncode"]))
        if result["stdout"].strip():
            print(result["stdout"].rstrip())
        if result["stderr"].strip():
            print(result["stderr"].rstrip())
        summary["checks"].append({"name": script, "status": "FAIL"})
    return ok


def run_node_check(summary):
    print_section("Node Syntax")
    app_js = os.path.join(PROJECT_ROOT, "static/js/app.js")
    if not os.path.exists(app_js):
        print_result("SKIP", "node --check static/js/app.js", "missing app.js")
        summary["checks"].append({"name": "node --check static/js/app.js", "status": "SKIP"})
        return True
    if shutil.which("node") is None:
        print_result("SKIP", "node --check static/js/app.js", "node missing")
        summary["checks"].append({"name": "node --check static/js/app.js", "status": "SKIP"})
        return True

    result = run_command(["node", "--check", "static/js/app.js"], "node --check static/js/app.js")
    append_command_result(summary, result)
    if result["returncode"] == 0:
        print_result("PASS", "node --check static/js/app.js")
        summary["checks"].append({"name": "node --check static/js/app.js", "status": "PASS"})
        return True

    print_result("FAIL", "node --check static/js/app.js")
    if result["stdout"].strip():
        print(result["stdout"].rstrip())
    if result["stderr"].strip():
        print(result["stderr"].rstrip())
    summary["checks"].append({"name": "node --check static/js/app.js", "status": "FAIL"})
    return False


def main():
    parser = argparse.ArgumentParser(description="Run local Nexus no-token preflight checks.")
    parser.add_argument("--strict-clean", action="store_true", help="Fail if the repo is dirty before checks.")
    parser.add_argument("--quick", action="store_true", help="Run the fast no-token safety subset.")
    parser.add_argument("--json", action="store_true", help="Print a JSON summary after text output.")
    parser.add_argument("--packet", help="Run packet-aware checks for a numeric packet, such as 34.")
    parser.add_argument("--report", help="Write a bounded packet-aware preflight report to this path.")
    parser.add_argument("--list-packet-checks", action="store_true", help="List discovered packet verifier scripts.")
    args = parser.parse_args()

    if args.list_packet_checks:
        print_packet_checks()
        return 0

    try:
        packet_number = normalize_packet_number(args.packet) if args.packet else None
    except ValueError as exception:
        print_result("FAIL", "packet argument", str(exception))
        return 2

    summary = {
        "result": "PASS",
        "strict_clean": args.strict_clean,
        "quick": args.quick,
        "packet": packet_number,
        "packet_verifier_paths": [],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "commands": [],
        "checks": [],
    }

    print("Nexus Local Preflight")
    initial_result, initial_status = git_status_short()
    append_command_result(summary, initial_result)
    summary["initial_git_status"] = initial_status
    summary["git_branch"] = git_branch_name(summary)
    if initial_result["returncode"] != 0:
        print_result("FAIL", "initial git status", initial_result["stderr"].strip())
        summary["checks"].append({"name": "initial git status", "status": "FAIL"})
        summary["result"] = "FAIL"
    elif initial_status:
        status = "FAIL" if args.strict_clean else "WARN"
        print_result(status, "repo dirty before checks", initial_status.replace("\n", "; "))
        summary["checks"].append({"name": "repo clean before checks", "status": status, "details": initial_status})
        if args.strict_clean:
            summary["result"] = "FAIL"
    else:
        print_result("PASS", "repo clean before checks")
        summary["checks"].append({"name": "repo clean before checks", "status": "PASS"})

    required_results = [
        run_py_compile(summary),
        run_verification_scripts(summary, quick=args.quick),
        run_safety_scans(summary),
        run_node_check(summary),
    ]
    if packet_number is not None:
        required_results.append(run_packet_verification(summary, packet_number))

    final_result, final_status = git_status_short()
    append_command_result(summary, final_result)
    print_section("Final Git Status")
    if final_result["returncode"] != 0:
        print_result("FAIL", "final git status", final_result["stderr"].strip())
        summary["checks"].append({"name": "final git status", "status": "FAIL"})
        required_results.append(False)
    elif final_status != initial_status:
        print_result("FAIL", "git status changed during preflight", final_status.replace("\n", "; "))
        summary["checks"].append(
            {
                "name": "git status unchanged",
                "status": "FAIL",
                "before": initial_status,
                "after": final_status,
            }
        )
        required_results.append(False)
    else:
        detail = "clean" if not final_status else final_status.replace("\n", "; ")
        print_result("PASS", "git status unchanged", detail)
        summary["checks"].append({"name": "git status unchanged", "status": "PASS"})

    if not all(required_results):
        summary["result"] = "FAIL"

    if args.report:
        try:
            report_path = write_preflight_report(summary, args.report)
            print("NEXUS_PREFLIGHT_REPORT={}".format(report_path))
        except (OSError, ValueError) as exception:
            print_result("FAIL", "write preflight report", str(exception))
            summary["checks"].append({"name": "write preflight report", "status": "FAIL", "details": str(exception)})
            summary["result"] = "FAIL"
    print("\nNEXUS_PREFLIGHT_RESULT={}".format(summary["result"]))
    if packet_number is not None:
        print("NEXUS_PACKET_PREFLIGHT_RESULT={}".format(summary["result"]))
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))

    return 0 if summary["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
