import os
import re
import sys

from sqlalchemy import create_engine, select
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
    service = read_file("src/services/inbox_triage_conversion.py")
    dashboard = read_file("dashboard.py")
    app = read_file("static/js/app.js")
    template = read_file("templates/index.html")

    check("class InboxConversion" in models, "InboxConversion model exists")
    for field in (
        "inbox_item_id",
        "target_type",
        "target_id",
        "conversion_status",
        "conversion_notes",
        "operator_notes",
    ):
        check(field in models, "InboxConversion includes {}".format(field))

    for phrase in (
        "CONVERSION_TARGET_TYPES",
        '"work_packet"',
        '"task"',
        '"document_update"',
        '"discarded"',
        "CONVERSION_STATUSES",
        "convert_inbox_to_work_packet",
        "convert_inbox_to_task",
        "convert_inbox_to_document_update",
        "discard_inbox_with_audit",
        "redact_git_output",
        "trust_status=\"unreviewed\"",
    ):
        check(phrase in service, "conversion service contains {}".format(phrase))

    for route in (
        "/api/orchestration-inbox/items/<int:item_id>/conversion-options",
        "/api/orchestration-inbox/items/<int:item_id>/convert/work-packet",
        "/api/orchestration-inbox/items/<int:item_id>/convert/task",
        "/api/orchestration-inbox/items/<int:item_id>/convert/document-update",
        "/api/orchestration-inbox/items/<int:item_id>/discard-with-audit",
    ):
        check(route in dashboard, "dashboard route exists: {}".format(route))

    check("confirm_convert" in service and "confirm_discard" in service, "conversion service requires explicit confirmation")
    check("discard reason is required" in service, "discard requires reason or note")
    check("db.commit()" in service, "conversion service records audit changes")

    conversion_section = dashboard.split('/api/orchestration-inbox/items/<int:item_id>/conversion-options', 1)[-1]
    conversion_section = conversion_section.split('/api/operator-interventions', 1)[0]
    forbidden_routes = (
        "/api/tasks/auto-run",
        "/api/tasks/run-one",
        "/api/work-packets/run",
        "/api/execute-codex",
        "execution_mode",
        "autopilot",
    )
    for phrase in forbidden_routes:
        check(phrase not in conversion_section, "conversion routes do not call {}".format(phrase))

    forbidden_git_actions = (
        "git add",
        "git commit",
        "git merge",
        "git push",
        "git reset",
        "git clean",
        "git rebase",
        "git stash",
        "git tag",
    )
    combined_conversion = "\n".join((service, conversion_section))
    for phrase in forbidden_git_actions:
        check(phrase not in combined_conversion, "conversion code does not expose {}".format(phrase))

    check("shell=True" not in combined_conversion, "conversion code does not use shell=True")
    check("subprocess.Popen" not in combined_conversion and "Popen(" not in combined_conversion, "conversion code does not use subprocess.Popen")
    check(re.search(r"\balert\s*\(", app) is None, "no native alert() in frontend")
    check(re.search(r"\bconfirm\s*\(", app) is None, "no native confirm() in frontend")
    check("NexusCore.confirmAction" in app, "frontend uses async confirmation pattern")
    check("orchestration-inbox-conversion-panel" in template, "dashboard contains inbox conversion panel")
    check("convertSelectedInboxItemToWorkPacket" in app, "frontend contains work packet conversion action")
    check("discardSelectedInboxItemWithAudit" in app, "frontend contains audited discard action")


def verify_docs():
    combined_docs = "\n".join(
        read_file(path)
        for path in (
            "docs/SPRINT_PLAN.md",
            "docs/SPRINT_3_PLAN.md",
            "docs/WORKFLOW_LOCK.md",
            "docs/CHAT_HANDOFF.md",
        )
    )
    required = (
        "Inbox Triage Conversion Flow",
        "non-executing",
        "Converted work packets remain `trust_status=unreviewed`",
        "Discard keeps the inbox item",
        "Discord must not directly start Codex, tasks, packets, or Auto-Pilot",
        "Auto-Pilot remains locked",
        "Packet 030 — Packet Drafting Assistant",
    )
    for phrase in required:
        check(phrase in combined_docs, "docs contain {}".format(phrase))
    check(
        "nexus-inbox-triage-conversion-baseline-2026-05-30" in combined_docs,
        "CHAT_HANDOFF references Packet 029 baseline",
    )


def verify_service_behavior():
    from models import Base, InboxConversion, OrchestrationInboxItem, Task, WorkPacket, Workspace
    from src.services.inbox_triage_conversion import (
        convert_inbox_to_document_update,
        convert_inbox_to_task,
        convert_inbox_to_work_packet,
        discard_inbox_with_audit,
        summarize_eligible_inbox_item,
    )

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    workspace = Workspace(name="Packet 029 Test", local_path=PROJECT_ROOT)
    db.add(workspace)
    db.commit()
    db.refresh(workspace)

    item = OrchestrationInboxItem(
        workspace_id=workspace.id,
        title="Convert item",
        raw_intent="Create a safe packet. token=secret-value",
        status="captured",
        source="manual",
        priority="normal",
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    try:
        convert_inbox_to_work_packet(db, workspace.id, item, {"packet_title": "No confirm"})
    except ValueError as exception:
        check("confirm_convert" in str(exception), "work packet conversion rejects missing confirmation")
        db.rollback()
    else:
        check(False, "work packet conversion rejects missing confirmation")

    result = convert_inbox_to_work_packet(
        db,
        workspace.id,
        item,
        {
            "confirm_convert": True,
            "packet_title": "Converted Packet",
            "goal": "Build a safe conversion flow",
            "safety_notes": "Do not execute anything.",
            "verification_notes": "Run verifier.",
            "operator_notes": "Reviewed before staging.",
        },
    )
    check(result["work_packet"].status == "staged", "work packet conversion stages packet")
    check(result["work_packet"].trust_status == "unreviewed", "converted work packet remains unreviewed")
    check(result["task"].status == "todo", "work packet conversion creates todo task")
    check(result["item"].status == "staged", "work packet conversion marks inbox item staged")
    check(result["conversion"].target_type == "work_packet", "work packet conversion audit target recorded")
    check("secret-value" not in (result["task"].description or ""), "task description is redacted")

    task_item = OrchestrationInboxItem(
        workspace_id=workspace.id,
        title="Task item",
        raw_intent="Make a manual task",
        status="triaged",
        source="manual",
        priority="normal",
    )
    doc_item = OrchestrationInboxItem(
        workspace_id=workspace.id,
        title="Doc item",
        raw_intent="Needs docs",
        status="captured",
        source="discord",
        priority="normal",
    )
    discard_item = OrchestrationInboxItem(
        workspace_id=workspace.id,
        title="Discard item",
        raw_intent="Ignore this",
        status="captured",
        source="manual",
        priority="normal",
    )
    db.add_all([task_item, doc_item, discard_item])
    db.commit()
    db.refresh(task_item)
    db.refresh(doc_item)
    db.refresh(discard_item)

    task_result = convert_inbox_to_task(
        db,
        workspace.id,
        task_item,
        {
            "confirm_convert": True,
            "title": "Manual todo",
            "summary": "Manual staging only.",
        },
    )
    check(task_result["task"].status == "todo", "task conversion creates todo task")
    check(task_result["conversion"].target_type == "task", "task conversion audit target recorded")

    doc_result = convert_inbox_to_document_update(
        db,
        workspace.id,
        doc_item,
        {
            "confirm_convert": True,
            "document_notes": "Update workflow docs.",
        },
    )
    check(doc_result["item"].status == "triaged", "document update keeps item triaged")
    check(doc_result["conversion"].target_id is None, "document update is audit-only")
    check(doc_result["conversion"].target_type == "document_update", "document update audit target recorded")

    try:
        discard_inbox_with_audit(db, workspace.id, discard_item, {"confirm_discard": True})
    except ValueError as exception:
        check("discard reason" in str(exception), "discard conversion rejects missing reason")
        db.rollback()
    else:
        check(False, "discard conversion rejects missing reason")

    discard_result = discard_inbox_with_audit(
        db,
        workspace.id,
        discard_item,
        {
            "confirm_discard": True,
            "discard_reason": "Not aligned with sprint scope.",
        },
    )
    check(discard_result["item"].status == "discarded", "discard conversion marks item discarded")
    check(discard_result["conversion"].target_type == "discarded", "discard conversion audit target recorded")
    check(db.get(OrchestrationInboxItem, discard_item.id) is not None, "discard keeps inbox item")

    conversion_count = db.execute(select(InboxConversion)).scalars().all()
    check(len(conversion_count) == 4, "four conversion audit records created")
    work_packets = db.execute(select(WorkPacket)).scalars().all()
    trusted_packets = [packet for packet in work_packets if packet.trust_status == "trusted"]
    check(not trusted_packets, "conversion never trusts work packets automatically")
    tasks = db.execute(select(Task)).scalars().all()
    check(all(task.status == "todo" for task in tasks), "all converted tasks are todo/manual")
    summary = summarize_eligible_inbox_item(doc_item)
    check("targets" in summary and summary["targets"], "conversion options summarize targets")


def main():
    verify_static_sources()
    verify_docs()
    verify_service_behavior()
    if FAILURES:
        print("FAIL: Packet 029 verification failed")
        return 1
    print("PASS: Packet 029 verification complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
