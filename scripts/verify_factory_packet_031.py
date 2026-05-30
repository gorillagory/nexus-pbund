import os
import re
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


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


def verify_static_sources():
    models = read_file("models.py")
    service = read_file("src/services/work_packet_readiness.py")
    dashboard = read_file("dashboard.py")
    app = read_file("static/js/app.js")
    style = read_file("static/style.css")

    for field in (
        "readiness_status",
        "readiness_checked_at",
        "readiness_checked_by",
        "readiness_notes",
        "readiness_score",
        "readiness_missing_items",
    ):
        check(field in models, "WorkPacket includes {}".format(field))

    for phrase in (
        "READINESS_STATUSES",
        '"incomplete"',
        '"ready_for_review"',
        '"ready_for_trust"',
        '"blocked"',
        "collect_work_packet_readiness_context",
        "evaluate_readiness_checklist",
        "evaluate_and_store_readiness",
        "update_readiness_metadata",
        "serialize_readiness",
        "redact_git_output",
        "Branch Per Packet",
    ):
        check(phrase in service, "readiness service contains {}".format(phrase))

    for phrase in (
        "clear_title",
        "clear_goal",
        "safety_rules",
        "files_allowed",
        "verification",
        "report_path",
        "no_autopilot",
        "no_execution_routes",
        "no_destructive_db",
        "no_secret_exposure",
        "no_shell_true",
        "no_popen",
        "no_native_alert_confirm",
        "trust_visible",
        "branch_recommendation",
    ):
        check(phrase in service, "readiness checklist includes {}".format(phrase))

    for route in (
        "/api/work-packets/<int:work_packet_id>/readiness",
        "/api/work-packets/<int:work_packet_id>/readiness/evaluate",
    ):
        check(route in dashboard, "readiness route exists: {}".format(route))
    check("confirm_evaluate" in service + app, "evaluate route/action requires confirm_evaluate")
    check("confirm_update" in service + app, "update route/action requires confirm_update")

    route_section = dashboard.split('/api/work-packets/<int:work_packet_id>/readiness', 1)[-1]
    route_section = route_section.split('/api/work-packets/run', 1)[0]
    for phrase in (
        "/api/tasks/auto-run",
        "/api/tasks/run-one",
        "/api/work-packets/run",
        "/api/execute-codex",
        "execution_mode",
        "autopilot",
        "mark_packet_trusted",
        "revoke_packet_trust",
        "_execute_factory_task",
    ):
        check(phrase not in route_section, "readiness routes do not call {}".format(phrase))

    for phrase in (
        "git add",
        "git commit",
        "git merge",
        "git push",
        "git reset",
        "git clean",
        "git rebase",
        "git stash",
        "git tag",
        "git switch",
        "git checkout",
    ):
        check(phrase not in route_section, "readiness routes do not expose {}".format(phrase))

    check(re.search(r"^\s*import\s+subprocess|^\s*from\s+subprocess\s+import", service + route_section, re.MULTILINE) is None, "readiness code does not import subprocess")
    check("shell=True" not in service + route_section, "readiness code avoids shell=True")
    check("subprocess.Popen" not in service + route_section and "Popen(" not in service + route_section, "readiness code avoids subprocess.Popen")
    check(re.search(r"\balert\s*\(", app) is None, "no native alert() in frontend")
    check(re.search(r"\bconfirm\s*\(", app) is None, "no native confirm() in frontend")
    check("NexusCore.confirmAction" in app, "frontend uses async confirmation pattern")
    check("Work Packet Readiness Checklist" in app, "dashboard contains Work Packet Readiness Checklist UI")
    check("work-packet-readiness-panel" in style, "readiness panel is styled")


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
    required = (
        "Work Packet Readiness Checklist",
        "validation and guidance only",
        "does not execute packets",
        "does not trust packets automatically",
        "does not bypass Trusted Packet Mode",
        "Auto-Pilot remains locked",
        "Packet 032 — Operator Review History",
        "nexus-work-packet-readiness-baseline-2026-05-30",
    )
    for phrase in required:
        check(phrase in combined, "docs contain {}".format(phrase))


def verify_service_behavior():
    from models import Base, PacketPromptDraft, Task, WorkPacket, WorkPacketTask, Workspace
    from src.services.work_packet_readiness import (
        evaluate_and_store_readiness,
        evaluate_readiness_checklist,
        serialize_readiness,
        update_readiness_metadata,
    )

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    workspace = Workspace(name="Packet 031 Test", local_path=PROJECT_ROOT)
    db.add(workspace)
    db.commit()
    db.refresh(workspace)

    packet = WorkPacket(
        workspace_id=workspace.id,
        title="Packet 031 Work Packet Readiness Checklist",
        risk_level="medium",
        stop_condition="Safety: no destructive database operations. Verification: run preflight.",
        status="staged",
        trust_status="unreviewed",
        trust_level="standard",
    )
    db.add(packet)
    db.flush()
    task = Task(
        workspace_id=workspace.id,
        title="Implement readiness checklist",
        description=(
            "MISSION Build readiness checklist.\n"
            "GOAL Validate work packet safety metadata.\n"
            "FILES ALLOWED models.py dashboard.py src/services/work_packet_readiness.py.\n"
            "VERIFICATION python3 scripts/verify_factory_packet_031.py.\n"
            "REPORT /tmp/nexus-packet-031-work-packet-readiness-report.md.\n"
            "No Auto-Pilot. Do not call /api/work-packets/run. No native browser alert(). "
            "No native browser confirm(). Branch Per Packet factory/packet-031-work-packet-readiness-checklist."
        ),
        status="todo",
    )
    db.add(task)
    db.flush()
    db.add(WorkPacketTask(work_packet_id=packet.id, task_id=task.id, position=1, status="staged"))
    draft = PacketPromptDraft(
        workspace_id=workspace.id,
        work_packet_id=packet.id,
        title="Readiness draft",
        draft_body=(
            "MISSION\nPacket 031.\nGOAL\nReadiness. token=secret-value\nSAFETY RULES\n"
            "No Auto-Pilot. Do not call /api/tasks/auto-run. No shell=True. No subprocess.Popen. "
            "No destructive database operations. No raw secret exposure.\n"
            "FILES ALLOWED\nScoped files.\nVERIFICATION\nRun verifier.\nREPORT\n/tmp/report.md"
        ),
        category="feature",
        safety_notes="No automatic trust. No execution.",
        verification_notes="Run Packet 031 verifier.",
        status="reviewed",
    )
    db.add(draft)
    db.commit()
    db.refresh(packet)

    evaluation = evaluate_readiness_checklist(db, packet)
    check(evaluation["score"] >= 90, "complete packet readiness score is high")
    check(evaluation["status"] == "ready_for_review", "untrusted complete packet is ready_for_review")
    check(not evaluation["missing_items"], "complete packet has no missing required items")
    serialized = serialize_readiness(packet, evaluation=evaluation)
    check(serialized["trust"]["trust_status"] == "unreviewed", "readiness serializes trust without changing it")
    check("secret-value" not in str(serialized), "readiness output is redacted")

    try:
        evaluate_and_store_readiness(db, packet, {})
    except ValueError as exception:
        check("confirm_evaluate" in str(exception), "evaluate store rejects missing confirmation")
        db.rollback()
    else:
        check(False, "evaluate store rejects missing confirmation")

    stored = evaluate_and_store_readiness(
        db,
        packet,
        {
            "confirm_evaluate": True,
            "readiness_checked_by": "operator",
            "readiness_notes": "Reviewed. password=hunter2",
        },
    )
    check(stored["readiness_status"] == "ready_for_review", "stored readiness status set")
    check(stored["readiness_score"] >= 90, "stored readiness score set")
    check(stored["trust"]["trust_status"] == "unreviewed", "readiness evaluation does not auto-trust")
    check("hunter2" not in str(stored), "stored readiness notes are redacted")

    try:
        update_readiness_metadata(db, packet, {"readiness_status": "blocked"})
    except ValueError as exception:
        check("confirm_update" in str(exception), "readiness update rejects missing confirmation")
        db.rollback()
    else:
        check(False, "readiness update rejects missing confirmation")

    updated = update_readiness_metadata(
        db,
        packet,
        {
            "confirm_update": True,
            "readiness_status": "blocked",
            "readiness_notes": "Needs clearer scope.",
            "readiness_checked_by": "operator",
        },
    )
    check(updated["readiness_status"] == "blocked", "readiness metadata update stores status")
    check(packet.trust_status == "unreviewed", "readiness update does not change trust")

    sparse = WorkPacket(
        workspace_id=workspace.id,
        title="Bad",
        risk_level="medium",
        stop_condition="",
        status="staged",
    )
    db.add(sparse)
    db.commit()
    sparse_eval = evaluate_readiness_checklist(db, sparse)
    check(sparse_eval["missing_items"], "sparse packet reports missing items")
    check(sparse_eval["status"] in {"blocked", "incomplete"}, "sparse packet is not ready")


def main():
    verify_static_sources()
    verify_docs()
    verify_service_behavior()
    if FAILURES:
        print("FAIL: Packet 031 verification failed")
        return 1
    print("PASS: Packet 031 verification complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
