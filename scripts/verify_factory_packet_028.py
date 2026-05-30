import os
import re
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
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


def verify_docs_exist():
    for path in (
        "docs/SPRINT_PLAN.md",
        "docs/SPRINT_3_PLAN.md",
        "docs/WORKFLOW_LOCK.md",
        "docs/CHAT_HANDOFF.md",
    ):
        check(os.path.exists(os.path.join(PROJECT_ROOT, path)), "{} exists".format(path))


def verify_sprint_plan():
    sprint_plan = read_file("docs/SPRINT_PLAN.md")
    required = (
        "Sprint 2 is complete",
        "Sprint 3 Direction",
        "Packet 029 — Inbox Triage Conversion Flow",
        "Packet 030 — Packet Drafting Assistant",
        "Packet 031 — Work Packet Readiness Checklist",
        "Packet 032 — Operator Review History",
        "Packet 033 — Factory Console Consolidation",
        "Packet 034 — Packet-Aware Preflight Expansion",
        "Packet 035 — Discord Capture Hardening",
        "Packet 036 — Deployment And Operator Runbooks",
    )
    for phrase in required:
        check(phrase in sprint_plan, "SPRINT_PLAN contains {}".format(phrase))

    type_markers = ("Type: docs/planning", "Type: workflow", "Type: safety", "Type: UI", "Type: integration")
    sprint_3 = read_file("docs/SPRINT_3_PLAN.md")
    for marker in type_markers:
        check(marker in sprint_3, "SPRINT_3_PLAN contains {}".format(marker))


def verify_safety_boundaries():
    combined = "\n".join(
        read_file(path)
        for path in (
            "docs/SPRINT_PLAN.md",
            "docs/SPRINT_3_PLAN.md",
            "docs/WORKFLOW_LOCK.md",
            "docs/CHAT_HANDOFF.md",
        )
    )
    required_boundaries = (
        "Auto-Pilot remains locked",
        "Discord must not directly start Codex, tasks, packets, or Auto-Pilot",
        "Git Explorer rule: dashboard Git inspection is read-only",
        "Branch Per Packet rule: the app may only prepare a validated",
        "Operator Intervention Queue rule: the queue records human review items",
        "Trusted Packet Mode rule: operators may mark reviewed packets trusted",
        "supervised packet execution is restricted to packets with `trust_status=trusted`",
        "raw ideas are captured first",
        "No Codex execution, no packet run, no task run, no Auto-Pilot",
    )
    for phrase in required_boundaries:
        check(phrase in combined, "docs preserve boundary: {}".format(phrase))

    forbidden_claims = (
        r"Discord (can|may|will) (execute|run|start)",
        r"Git Explorer (can|may|will) (write|commit|merge|push|reset|clean)",
        r"Auto-Pilot (is|should be|will be) (enabled|unlocked)",
        r"automatically (runs|executes) packets",
    )
    for pattern in forbidden_claims:
        check(re.search(pattern, combined, flags=re.IGNORECASE) is None, "docs avoid claim matching {}".format(pattern))


def verify_handoff():
    handoff = read_file("docs/CHAT_HANDOFF.md")
    check("nexus-sprint-3-direction-baseline-2026-05-30" in handoff, "CHAT_HANDOFF references Packet 028 baseline")
    check("Packet 028 — Sprint 3 Direction Lock complete" in handoff, "CHAT_HANDOFF marks Packet 028 complete")
    check("Packet 029 — Inbox Triage Conversion Flow" in handoff, "CHAT_HANDOFF recommends Packet 029")
    check("cat docs/SPRINT_3_PLAN.md" in handoff, "CHAT_HANDOFF startup includes Sprint 3 plan")


def verify_no_runtime_changes_expected():
    changed_runtime_paths = []
    for path in ("dashboard.py", "engine.py", "models.py", "static/js/app.js", "static/js/settings.js", "templates/index.html"):
        # Packet 028 should not require source markers in runtime files.
        content = read_file(path)
        if "Packet 028" in content or "Sprint 3 Direction Lock" in content:
            changed_runtime_paths.append(path)
    check(not changed_runtime_paths, "runtime files do not contain Packet 028 planning markers")


def main():
    verify_docs_exist()
    verify_sprint_plan()
    verify_safety_boundaries()
    verify_handoff()
    verify_no_runtime_changes_expected()
    if FAILURES:
        print("FAIL: Packet 028 verification failed")
        return 1
    print("PASS: Packet 028 verification complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
