import os
import re
import subprocess
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


def verify_sprint_4_plan():
    path = os.path.join(PROJECT_ROOT, "docs/SPRINT_4_PLAN.md")
    check(os.path.exists(path), "docs/SPRINT_4_PLAN.md exists")
    sprint4 = read_file("docs/SPRINT_4_PLAN.md")

    required = (
        "Sprint 4 focuses on production hardening",
        "nexus-deployment-operator-runbooks-baseline-2026-05-30",
        "Sprint 3 status: complete at Packet 036",
        "Packet 038 -- Environment Validation And Startup Diagnostics",
        "Packet 039 -- Work Packet Lifecycle State Map",
        "Packet 040 -- Linked Operator Context Timeline",
        "Packet 041 -- Preflight Verifier Registry",
        "Packet 042 -- CI Report Artifact Polish",
        "Packet 043 -- Operator Troubleshooting Matrix",
        "Packet 044 -- Discord Setup And Notification Harness",
        "Packet 045 -- Sprint 4 Closure And Next Direction Lock",
        "Explicit Out Of Scope",
    )
    for phrase in required:
        check(phrase in sprint4, "Sprint 4 plan contains {}".format(phrase))

    boundaries = (
        "Auto-Pilot remains locked",
        "Discord remains capture-only",
        "Git Explorer remains read-only",
        "Branch Per Packet remains narrow",
        "Trusted Packet Mode remains restrictive only",
        "Operator Intervention Queue remains manual decision tracking",
        "Operator Review History remains append-only audit visibility",
        "Packet-aware preflight remains checks and reporting only",
        "Execution remains supervised and explicit",
        "no runtime behavior",
    )
    for phrase in boundaries:
        check(phrase.lower() in sprint4.lower(), "Sprint 4 plan preserves boundary: {}".format(phrase))


def verify_existing_docs():
    docs = {
        "docs/SPRINT_PLAN.md": read_file("docs/SPRINT_PLAN.md"),
        "docs/WORKFLOW_LOCK.md": read_file("docs/WORKFLOW_LOCK.md"),
        "docs/CHAT_HANDOFF.md": read_file("docs/CHAT_HANDOFF.md"),
        "docs/PROMPTING_GUIDE.md": read_file("docs/PROMPTING_GUIDE.md"),
    }
    combined = "\n".join(docs.values())

    for phrase in (
        "Sprint 3 is complete",
        "Sprint 4 Direction Lock",
        "docs/SPRINT_4_PLAN.md",
        "nexus-deployment-operator-runbooks-baseline-2026-05-30",
        "nexus-sprint-4-direction-baseline-2026-05-30",
        "Packet 038",
    ):
        check(phrase in combined, "existing docs contain {}".format(phrase))

    handoff = docs["docs/CHAT_HANDOFF.md"]
    check(
        "Previous Packet 036 baseline tag: `nexus-deployment-operator-runbooks-baseline-2026-05-30`"
        in handoff,
        "CHAT_HANDOFF references latest completed Packet 036 baseline",
    )
    check("cat docs/SPRINT_4_PLAN.md" in handoff, "CHAT_HANDOFF startup reads Sprint 4 plan")
    check(
        "Next — Packet 038 — Environment Validation And Startup Diagnostics" in handoff,
        "CHAT_HANDOFF recommends Packet 038 next",
    )

    for phrase in (
        "Auto-Pilot remains locked",
        "Discord remains capture-only",
        "Git Explorer remains read-only",
        "Branch Per Packet remains narrow",
        "Trusted Packet Mode remains restrictive only",
        "execution remains supervised and explicit",
        "does not add runtime behavior",
    ):
        check(phrase.lower() in combined.lower(), "existing docs preserve boundary: {}".format(phrase))


def verify_no_runtime_changes():
    result = subprocess.run(
        ["git", "status", "--short"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    changed = set()
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        changed.add(path)

    allowed = {
        "docs/SPRINT_4_PLAN.md",
        "docs/SPRINT_PLAN.md",
        "docs/WORKFLOW_LOCK.md",
        "docs/CHAT_HANDOFF.md",
        "docs/PROMPTING_GUIDE.md",
        "scripts/verify_factory_packet_037.py",
    }
    unexpected = sorted(changed - allowed)
    check(not unexpected, "Packet 037 changed only direction-lock docs and verifier")


def verify_docs_safe():
    combined = "\n".join(
        read_file(path)
        for path in (
            "docs/SPRINT_4_PLAN.md",
            "docs/SPRINT_PLAN.md",
            "docs/WORKFLOW_LOCK.md",
            "docs/CHAT_HANDOFF.md",
            "docs/PROMPTING_GUIDE.md",
        )
    )

    unsafe_claims = (
        "Auto-Pilot is enabled",
        "Discord can execute",
        "Git Explorer can write",
        "Trusted Packet Mode executes",
        "automatic execution is enabled",
        "git reset --hard",
        "git clean -fd",
        "force push as normal",
    )
    for phrase in unsafe_claims:
        check(phrase not in combined, "docs do not claim unsafe behavior: {}".format(phrase))

    secret_patterns = (
        r"sk-[A-Za-z0-9_-]{8,}",
        r"AIza[0-9A-Za-z_-]{20,}",
        r"authorization\s*[:=]\s*bearer\s+[A-Za-z0-9][A-Za-z0-9._~+/=-]{23,}",
        r"(?:api[_ -]?key|token|secret|password)\s*[:=]\s*[A-Za-z0-9._~+/=-]{24,}",
    )
    for pattern in secret_patterns:
        check(re.search(pattern, combined, flags=re.IGNORECASE) is None, "docs do not expose raw secret pattern {}".format(pattern))


def main():
    verify_sprint_4_plan()
    verify_existing_docs()
    verify_no_runtime_changes()
    verify_docs_safe()
    if FAILURES:
        print("FAIL: Packet 037 verification failed")
        return 1
    print("PASS: Packet 037 verification complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
