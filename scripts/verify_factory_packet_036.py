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


def verify_runbooks_exist():
    for path in (
        "docs/OPERATOR_RUNBOOK.md",
        "docs/DEPLOYMENT_RUNBOOK.md",
        "docs/RECOVERY_RUNBOOK.md",
    ):
        check(os.path.exists(os.path.join(PROJECT_ROOT, path)), "{} exists".format(path))


def verify_runbook_content():
    operator = read_file("docs/OPERATOR_RUNBOOK.md")
    deployment = read_file("docs/DEPLOYMENT_RUNBOOK.md")
    recovery = read_file("docs/RECOVERY_RUNBOOK.md")
    combined = "\n".join([operator, deployment, recovery])

    required = (
        "Starting The App Locally",
        "git status --short",
        "python3 scripts/nexus_preflight.py --quick",
        "python3 scripts/nexus_preflight.py --packet",
        "Factory Console",
        "Orchestration Inbox",
        "Discord-captured intent",
        "Packet Drafting Assistant",
        "Work Packet Readiness Checklist",
        "Trusted Packet Mode",
        "Operator Intervention Queue",
        "Operator Review History",
        "Git Explorer",
        "Branch Per Packet",
        "Baseline",
        "New Chat Handoff",
        "DISCORD_INGEST_SECRET",
        "DISCORD_SIGNATURE_REQUIRED",
        "python3 scripts/sync_factory_schema.py",
        "Deployment Checklist",
        "Failed Run Inspection",
        "Explicit Approval Required",
        "Secret Handling",
    )
    for phrase in required:
        check(phrase in combined, "runbooks contain {}".format(phrase))

    boundaries = (
        "Auto-Pilot",
        "Discord remains capture-only",
        "Git Explorer is read-only",
        "Branch Per Packet only",
        "No destructive database operations",
        "No raw secret exposure",
        "Do not force push",
        "Do not use `git reset` or `git clean` unless explicitly approved",
        "Retry and continue are not automatic",
    )
    for phrase in boundaries:
        check(phrase in combined, "runbooks preserve boundary: {}".format(phrase))

    unsafe_normal_flow = (
        "git reset --hard",
        "git clean -fd",
        "force push as normal",
        "Discord can execute",
        "start Auto-Pilot",
        "set execution_mode to autopilot",
        "/api/tasks/auto-run",
        "/api/tasks/run-one",
        "/api/work-packets/run",
        "/api/execute-codex",
    )
    for phrase in unsafe_normal_flow:
        check(phrase not in combined, "runbooks do not instruct unsafe flow: {}".format(phrase))

    check("your_gemini_api_key_here" in deployment, "deployment docs use placeholder secrets only")
    secret_patterns = (
        r"sk-[A-Za-z0-9_-]{8,}",
        r"AIza[0-9A-Za-z_-]{20,}",
        r"DISCORD_INGEST_SECRET=[^\\n`]*[A-Za-z0-9]{24,}",
    )
    for pattern in secret_patterns:
        check(re.search(pattern, combined) is None, "runbooks do not expose raw secret pattern {}".format(pattern))


def verify_existing_docs():
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
        "Deployment and Operator Runbooks",
        "Sprint 3 is complete",
        "Sprint 4 Direction Lock",
        "docs/OPERATOR_RUNBOOK.md",
        "docs/DEPLOYMENT_RUNBOOK.md",
        "docs/RECOVERY_RUNBOOK.md",
        "nexus-deployment-operator-runbooks-baseline-2026-05-30",
    ):
        check(phrase in combined, "existing docs contain {}".format(phrase))

    for phrase in (
        "documentation only",
        "does not add runtime behavior",
        "Auto-Pilot remains locked",
        "direct Discord execution",
        "broad Git write controls",
    ):
        check(phrase in combined, "existing docs preserve Packet 036 boundary: {}".format(phrase))


def verify_no_runtime_changes():
    result = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    output = result.stdout if result.returncode == 0 else ""
    changed = {line.strip() for line in output.splitlines() if line.strip()}
    allowed = {
        "docs/OPERATOR_RUNBOOK.md",
        "docs/DEPLOYMENT_RUNBOOK.md",
        "docs/RECOVERY_RUNBOOK.md",
        "docs/SPRINT_PLAN.md",
        "docs/SPRINT_3_PLAN.md",
        "docs/WORKFLOW_LOCK.md",
        "docs/CHAT_HANDOFF.md",
        "docs/PROMPTING_GUIDE.md",
        ".env.example",
        "scripts/verify_factory_packet_036.py",
    }
    unexpected = sorted(changed - allowed)
    check(not unexpected, "Packet 036 changed only docs and verifier files")


def main():
    verify_runbooks_exist()
    verify_runbook_content()
    verify_existing_docs()
    verify_no_runtime_changes()
    if FAILURES:
        print("FAIL: Packet 036 verification failed")
        return 1
    print("PASS: Packet 036 verification complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
