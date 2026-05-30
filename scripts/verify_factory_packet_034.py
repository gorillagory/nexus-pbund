import os
import re
import subprocess
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

FAILURES = []


def check(condition, message):
    if condition:
        print("PASS: {}".format(message))
        return
    print("FAIL: {}".format(message))
    FAILURES.append(message)


def read_file(relative_path):
    with open(os.path.join(PROJECT_ROOT, relative_path), "r", encoding="utf-8") as handle:
        return handle.read()


def verify_static_preflight():
    preflight = read_file("scripts/nexus_preflight.py")

    for phrase in (
        "--packet",
        "--report",
        "--list-packet-checks",
        "PACKET_VERIFY_PATTERN",
        "discover_packet_verifiers",
        "normalize_packet_number",
        "run_packet_verification",
        "write_preflight_report",
        "render_preflight_report",
        "redact_preflight_output",
        "bounded_output",
        "NEXUS_PACKET_PREFLIGHT_RESULT",
    ):
        check(phrase in preflight, "packet-aware preflight contains {}".format(phrase))

    check("args.quick" in preflight and "QUICK_VERIFY_SCRIPTS" in preflight, "existing --quick behavior remains wired")
    check("subprocess.run(" in preflight, "preflight uses subprocess.run")
    check("timeout=timeout" in preflight, "subprocess calls use timeouts")
    check("command, label, timeout" in preflight, "run_command keeps list command contract")
    check("shell=True" not in preflight, "preflight avoids shell true assignment")
    check("subprocess." + "Popen" not in preflight and "Popen(" not in preflight, "preflight avoids subprocess popen")

    for phrase in (
        "/api/tasks/auto-run",
        "/api/tasks/run-one",
        "/api/work-packets/run",
        "/api/execute-codex",
        "CodexRunner",
        "_execute_factory_task",
        "retry_factory_run",
        "continue_factory_run",
        "mark_packet_trusted",
        "revoke_packet_trust",
        "prepare_packet_branch",
        "set_execution_mode",
    ):
        check(phrase not in preflight, "preflight does not call {}".format(phrase))

    for action, phrase in (
        ("git add", '["git", "add"'),
        ("git commit", '["git", "commit"'),
        ("git merge", '["git", "merge"'),
        ("git push", '["git", "push"'),
        ("git reset", '["git", "reset"'),
        ("git clean", '["git", "clean"'),
        ("git rebase", '["git", "rebase"'),
        ("git stash", '["git", "stash"'),
        ("git tag", '["git", "tag"'),
        ("git switch", '["git", "switch"'),
        ("git checkout", '["git", "checkout"'),
    ):
        check(phrase not in preflight, "preflight does not run {}".format(action))


def verify_preflight_behavior():
    import scripts.nexus_preflight as preflight

    discovered = preflight.discover_packet_verifiers()
    check(34 in discovered, "packet verifier discovery includes Packet 034")
    check("scripts/verify_factory_packet_034.py" in discovered.get(34, []), "Packet 034 verifier path is discovered")
    check(preflight.normalize_packet_number("34") == 34, "numeric packet argument normalizes")

    rejected_values = ("../034", "scripts/verify_factory_packet_034.py", "34.py", "-34", "0", "034/../../x")
    for value in rejected_values:
        try:
            preflight.normalize_packet_number(value)
        except ValueError:
            check(True, "unsafe packet argument rejected: {}".format(value))
        else:
            check(False, "unsafe packet argument rejected: {}".format(value))

    redacted = preflight.redact_preflight_output("token=secret-value password=hunter2")
    check("secret-value" not in redacted and "hunter2" not in redacted, "report redaction removes secret-looking values")
    bounded = preflight.bounded_output("x" * 7000, limit=100)
    check("[output truncated to 100 characters]" in bounded, "report output is bounded")

    summary = {
        "timestamp": "2026-05-30T00:00:00+00:00",
        "git_branch": "main",
        "initial_git_status": "",
        "packet": 34,
        "packet_verifier_paths": ["scripts/verify_factory_packet_034.py"],
        "result": "PASS",
        "checks": [{"name": "sample", "status": "PASS"}],
        "commands": [
            {
                "label": "sample",
                "command": [sys.executable, "scripts/verify_factory_packet_034.py"],
                "returncode": 0,
                "timed_out": False,
                "stdout": "api_key=secret-value",
                "stderr": "",
            }
        ],
    }
    report = preflight.render_preflight_report(summary)
    check("Nexus Packet-Aware Preflight Report" in report, "packet-aware report renders")
    check("secret-value" not in report, "packet-aware report is redacted")
    check(len(report) <= preflight.MAX_REPORT_CHARS + 200, "packet-aware report is bounded")

    list_result = subprocess.run(
        [sys.executable, "scripts/nexus_preflight.py", "--list-packet-checks"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    check(list_result.returncode == 0, "--list-packet-checks exits successfully")
    check("Packet 034" in list_result.stdout, "--list-packet-checks lists Packet 034")

    invalid_result = subprocess.run(
        [sys.executable, "scripts/nexus_preflight.py", "--packet", "../034"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    check(invalid_result.returncode != 0, "arbitrary packet path is rejected by CLI")


def verify_frontend_unchanged_safety():
    app = read_file("static/js/app.js")
    template = read_file("templates/index.html")
    check(re.search(r"\balert\s*\(", app + template) is None, "no native alert() in frontend")
    check(re.search(r"\bconfirm\s*\(", app + template) is None, "no native confirm() in frontend")


def verify_docs():
    combined = "\n".join(
        read_file(path)
        for path in (
            "docs/SPRINT_PLAN.md",
            "docs/SPRINT_3_PLAN.md",
            "docs/WORKFLOW_LOCK.md",
            "docs/CHAT_HANDOFF.md",
            "docs/PROMPTING_GUIDE.md",
        )
    )
    for phrase in (
        "Packet-Aware Preflight Expansion",
        "checks/reporting only",
        "does not execute packets",
        "does not run Codex",
        "does not auto-fix",
        "does not write Git state",
        "does not replace human review, readiness, or trust",
        "Auto-Pilot remains locked",
        "nexus-packet-aware-preflight-baseline-2026-05-30",
        "Packet 035 — Discord Capture Hardening",
    ):
        check(phrase in combined, "docs preserve packet-aware preflight boundary: {}".format(phrase))


def main():
    verify_static_preflight()
    verify_preflight_behavior()
    verify_frontend_unchanged_safety()
    verify_docs()
    if FAILURES:
        print("FAIL: Packet 034 verification failed")
        return 1
    print("PASS: Packet 034 verification complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
