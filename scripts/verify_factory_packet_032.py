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
    service = read_file("src/services/operator_review_history.py")
    dashboard = read_file("dashboard.py")
    app = read_file("static/js/app.js")
    template = read_file("templates/index.html")
    style = read_file("static/style.css")
    sync = read_file("scripts/sync_factory_schema.py")

    check("class OperatorReviewEvent" in models, "OperatorReviewEvent model exists")
    for field in (
        "event_type",
        "action",
        "title",
        "summary",
        "details",
        "actor",
        "source_type",
        "source_id",
        "related_type",
        "related_id",
        "severity",
        "status",
        "metadata_json",
    ):
        check(field in models, "OperatorReviewEvent includes {}".format(field))
        check(field in sync, "schema sync includes {}".format(field))
    check('"operator_review_events"' in sync, "schema sync covers operator_review_events")

    for phrase in (
        "REVIEW_EVENT_TYPES",
        "REVIEW_SEVERITIES",
        "create_review_event",
        "list_review_events",
        "serialize_review_event",
        "create_manual_review_note",
        "build_timeline_filters",
        "summarize_review_history",
        "redact_git_output",
        "MAX_TEXT_CHARS",
        "MAX_LIST_LIMIT",
    ):
        check(phrase in service, "review history service contains {}".format(phrase))

    for event_type in (
        "inbox_conversion",
        "readiness_check",
        "trust_decision",
        "intervention_decision",
        "recovery_decision",
        "draft_review",
        "manual_note",
    ):
        check(event_type in service, "review event type constrained: {}".format(event_type))
        check(event_type in dashboard or event_type == "manual_note", "dashboard integration references {}".format(event_type))
    for severity in ("info", "warning", "blocked", "critical"):
        check(severity in service, "review severity constrained: {}".format(severity))

    for route in (
        "/api/operator-review-history",
        "/api/operator-review-history/filters",
        "/api/operator-review-history/summary",
        "/api/operator-review-history/manual-note",
    ):
        check(route in dashboard, "review history route exists: {}".format(route))
    check("confirm_create" in service + app, "manual review note requires confirm_create")
    check("_safe_create_review_event" in dashboard, "dashboard uses safe append-only review event helper")

    route_section = dashboard.split('/api/operator-review-history', 1)[-1]
    route_section = route_section.split('/api/operator-interventions", methods=["POST"]', 1)[0]
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
        check(phrase not in route_section, "review history routes do not call {}".format(phrase))

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
        check(phrase not in route_section + service, "review history code does not expose {}".format(phrase))

    integration_phrases = (
        'event_type="inbox_conversion"',
        'event_type="readiness_check"',
        'event_type="trust_decision"',
        'event_type="intervention_decision"',
        'event_type="draft_review"',
        'event_type="recovery_decision"',
    )
    for phrase in integration_phrases:
        check(phrase in dashboard, "append-only integration present: {}".format(phrase))

    check(re.search(r"^\s*import\s+subprocess|^\s*from\s+subprocess\s+import", service + route_section, re.MULTILINE) is None, "review history code does not import subprocess")
    check("shell=True" not in service + route_section, "review history code avoids shell=True")
    check("subprocess.Popen" not in service + route_section and "Popen(" not in service + route_section, "review history code avoids subprocess.Popen")
    check("mark_packet_trusted(" not in route_section and "revoke_packet_trust(" not in route_section, "review history routes do not trust packets")
    check(re.search(r"\balert\s*\(", app + template) is None, "no native alert() in frontend")
    check(re.search(r"\bconfirm\s*\(", app + template) is None, "no native confirm() in frontend")
    check("NexusCore.confirmAction" in app, "frontend uses async confirmation pattern")
    check("Operator Review History" in app + template, "dashboard contains Operator Review History UI")
    check("operator-review-history-panel" in style + template, "review history panel is styled")


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
        "Operator Review History",
        "audit and visibility only",
        "audit/visibility only",
        "does not execute packets",
        "does not trust packets automatically",
        "does not replace source records",
        "Auto-Pilot remains locked",
        "Packet 033 — Factory Console Consolidation",
        "nexus-operator-review-history-baseline-2026-05-30",
    )
    for phrase in required:
        check(phrase in combined, "docs contain {}".format(phrase))


def verify_service_behavior():
    from models import Base, OperatorIntervention, OperatorReviewEvent, WorkPacket, Workspace
    from src.services.operator_review_history import (
        build_timeline_filters,
        create_manual_review_note,
        create_review_event,
        list_review_events,
        serialize_review_event,
        summarize_review_history,
    )

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    workspace = Workspace(name="Packet 032 Test", local_path=PROJECT_ROOT)
    db.add(workspace)
    db.commit()
    db.refresh(workspace)

    packet = WorkPacket(
        workspace_id=workspace.id,
        title="Packet 032 Operator Review History",
        risk_level="medium",
        stop_condition="Audit visibility only.",
        status="staged",
        trust_status="unreviewed",
    )
    intervention = OperatorIntervention(
        workspace_id=workspace.id,
        title="Review blocker",
        details="Needs operator decision.",
        severity="warning",
        status="open",
    )
    db.add_all([packet, intervention])
    db.commit()
    db.refresh(packet)
    db.refresh(intervention)

    try:
        create_manual_review_note(db, workspace.id, {"title": "No confirm", "summary": "Missing confirmation"})
    except ValueError as exception:
        check("confirm_create" in str(exception), "manual note rejects missing confirmation")
        db.rollback()
    else:
        check(False, "manual note rejects missing confirmation")

    manual = create_manual_review_note(
        db,
        workspace.id,
        {
            "confirm_create": True,
            "title": "Manual review note",
            "summary": "Human reviewed governance state. password=hunter2",
            "severity": "critical",
            "source_type": "manual",
            "source_id": "operator",
            "metadata": {"token": "secret-value"},
        },
    )
    serialized = serialize_review_event(manual)
    check(serialized["event_type"] == "manual_note", "manual note event type is manual_note")
    check(serialized["severity"] == "critical", "manual note severity is constrained")
    check("hunter2" not in str(serialized) and "secret-value" not in str(serialized), "manual note output is redacted")

    trust_event = create_review_event(
        db,
        workspace.id,
        {
            "event_type": "trust_decision",
            "action": "trust",
            "title": "Packet trust reviewed",
            "summary": "Trust decision recorded only.",
            "source_type": "work_packet",
            "source_id": str(packet.id),
            "severity": "info",
        },
    )
    check(trust_event.id is not None, "review event persisted")
    db.refresh(packet)
    check(packet.trust_status == "unreviewed", "review history does not auto-trust packets")

    unknown = create_review_event(
        db,
        workspace.id,
        {
            "event_type": "unsupported",
            "action": "noted",
            "title": "Unsupported type",
            "summary": "Normalizes safely.",
            "severity": "unsupported",
        },
    )
    check(unknown.event_type == "manual_note", "unsupported event type normalizes safely")
    check(unknown.severity == "info", "unsupported severity normalizes safely")

    filtered = list_review_events(db, workspace.id, event_type="trust_decision")
    check(len(filtered) == 1 and filtered[0].id == trust_event.id, "review history filters by event type")
    limited = list_review_events(db, workspace.id, limit=1)
    check(len(limited) == 1, "review history list is bounded by limit")
    summary = summarize_review_history(db, workspace.id)
    check(summary["total_loaded"] >= 3, "review history summary counts events")
    filters = build_timeline_filters()
    check("trust_decision" in filters["event_types"], "timeline filters include event types")
    check(db.execute(select(OperatorReviewEvent)).scalars().first() is not None, "operator review events remain append-only records")


def main():
    verify_static_sources()
    verify_docs()
    verify_service_behavior()
    if FAILURES:
        print("FAIL: Packet 032 verification failed")
        return 1
    print("PASS: Packet 032 verification complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
