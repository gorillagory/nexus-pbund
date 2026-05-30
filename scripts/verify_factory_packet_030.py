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
    service = read_file("src/services/packet_drafting.py")
    dashboard = read_file("dashboard.py")
    app = read_file("static/js/app.js")
    style = read_file("static/style.css")

    check("class PacketPromptDraft" in models, "PacketPromptDraft model exists")
    for field in (
        "work_packet_id",
        "inbox_item_id",
        "source_type",
        "source_id",
        "template_id",
        "draft_body",
        "safety_notes",
        "verification_notes",
        "status",
    ):
        check(field in models, "PacketPromptDraft includes {}".format(field))

    for phrase in (
        "DRAFT_STATUSES",
        '"draft"',
        '"reviewed"',
        "MAX_DRAFT_CHARS",
        "MAX_CONTEXT_CHARS",
        "redact_git_output",
        "build_structured_packet_prompt",
        "save_packet_prompt_draft",
        "mark_packet_prompt_draft_reviewed",
        "validate_required_sections",
        "list_usable_templates",
        "PromptTemplate",
    ):
        check(phrase in service, "packet drafting service contains {}".format(phrase))

    for route in (
        "/api/packet-drafting/status",
        "/api/packet-drafting/templates",
        "/api/packet-drafting/draft",
        "/api/packet-drafting/drafts",
        "/api/packet-drafting/drafts/<int:draft_id>",
        "/api/packet-drafting/drafts/<int:draft_id>/mark-reviewed",
        "/api/packet-drafting/validate",
    ):
        check(route in dashboard, "dashboard route exists: {}".format(route))

    for confirmation in ("confirm_generate", "confirm_save", "confirm_review"):
        check(confirmation in service + app, "state change requires {}".format(confirmation))

    route_section = dashboard.split('/api/packet-drafting/status', 1)[-1]
    route_section = route_section.split('/api/kill-process', 1)[0]
    forbidden_routes = (
        "/api/tasks/auto-run",
        "/api/tasks/run-one",
        "/api/work-packets/run",
        "/api/execute-codex",
        "execution_mode",
        "autopilot",
        "mark_packet_trusted",
        "revoke_packet_trust",
    )
    for phrase in forbidden_routes:
        check(phrase not in route_section, "packet drafting routes do not call {}".format(phrase))

    combined_code = "\n".join((route_section,))
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
        check(phrase not in combined_code, "packet drafting routes do not expose {}".format(phrase))

    check(re.search(r"^\s*import\s+subprocess|^\s*from\s+subprocess\s+import", service + route_section, re.MULTILINE) is None, "packet drafting code does not import subprocess")
    check("shell=True" not in route_section, "packet drafting routes avoid shell=True")
    check("subprocess.Popen" not in route_section and "Popen(" not in route_section, "packet drafting routes avoid subprocess.Popen")
    check(re.search(r"\balert\s*\(", app) is None, "no native alert() in frontend")
    check(re.search(r"\bconfirm\s*\(", app) is None, "no native confirm() in frontend")
    check("NexusCore.confirmAction" in app, "frontend uses async confirmation pattern")
    check("Packet Drafting Assistant" in app, "dashboard contains Packet Drafting Assistant UI")
    check("copyPacketDraft" in app, "frontend can copy draft text")
    check("packet-drafting-panel" in style, "Packet Drafting Assistant panel is styled")


def verify_docs():
    combined_docs = "\n".join(
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
        "Packet Drafting Assistant",
        "draft-only",
        "does not execute generated drafts",
        "does not trust packets automatically",
        "Auto-Pilot remains locked",
        "Packet 031 — Work Packet Readiness Checklist",
        "nexus-packet-drafting-assistant-baseline-2026-05-30",
    )
    for phrase in required:
        check(phrase in combined_docs, "docs contain {}".format(phrase))


def verify_service_behavior():
    from models import Base, OrchestrationInboxItem, PacketPromptDraft, PromptTemplate, Workspace
    from src.services.packet_drafting import (
        build_structured_packet_prompt,
        collect_drafting_context,
        list_drafting_sources,
        mark_packet_prompt_draft_reviewed,
        save_packet_prompt_draft,
        update_packet_prompt_draft,
        validate_required_sections,
    )

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    workspace = Workspace(name="Packet 030 Test", local_path=PROJECT_ROOT)
    template = PromptTemplate(
        title="Feature Packet Template",
        category="feature",
        risk_level="medium",
        description="Draft packet safely.",
        body="MISSION\nTemplate body with token=secret-value\nSAFETY RULES\nNo execution.",
        status="active",
    )
    db.add_all([workspace, template])
    db.commit()
    db.refresh(workspace)
    db.refresh(template)

    inbox_item = OrchestrationInboxItem(
        workspace_id=workspace.id,
        title="Draft from inbox",
        raw_intent="Build a safe feature. password=hunter2",
        source="manual",
        status="triaged",
        priority="normal",
        category="feature",
        triage_notes="Reviewed intent.",
    )
    db.add(inbox_item)
    db.commit()
    db.refresh(inbox_item)

    try:
        build_structured_packet_prompt(db, workspace.id, {"packet_title": "No confirm"})
    except ValueError as exception:
        check("confirm_generate" in str(exception), "draft generation rejects missing confirmation")
        db.rollback()
    else:
        check(False, "draft generation rejects missing confirmation")

    result = build_structured_packet_prompt(
        db,
        workspace.id,
        {
            "confirm_generate": True,
            "source_type": "inbox_item",
            "source_id": inbox_item.id,
            "template_id": template.id,
            "packet_number": "030",
            "packet_title": "Packet Drafting Assistant",
            "category": "feature",
            "goal": "Generate structured packet drafts safely.",
            "safety_notes": "Draft only. Do not execute generated prompts.",
            "verification_notes": "Run Packet 030 verifier and quick preflight.",
            "files_allowed": "models.py, dashboard.py, src/services/packet_drafting.py",
            "branch_name": "factory/packet-030-packet-drafting-assistant",
            "report_path": "/tmp/nexus-packet-030-packet-drafting-assistant-report.md",
        },
    )
    draft_body = result["draft_body"]
    validation = validate_required_sections(draft_body)
    check(validation["valid"], "generated draft contains required sections")
    for phrase in (
        "MISSION",
        "CURRENT STATE",
        "GOAL",
        "SAFETY RULES",
        "WORKFLOW",
        "FILES ALLOWED",
        "IMPLEMENTATION PARTS",
        "VERIFICATION",
        "COMMIT / MERGE / PUSH",
        "REPORT",
        "No Auto-Pilot",
        "No shell=True",
        "No subprocess.Popen",
        "No native browser alert()",
        "No native browser confirm()",
    ):
        check(phrase in draft_body, "generated draft includes {}".format(phrase))
    check("hunter2" not in draft_body and "secret-value" not in draft_body, "generated draft is redacted")
    check(len(draft_body) <= 24000, "generated draft is bounded")

    context = collect_drafting_context(db, workspace.id, "inbox_item", inbox_item.id)
    check("hunter2" not in context["context"], "source context is redacted")
    sources = list_drafting_sources(db, workspace.id)
    check(sources["inbox_items"], "drafting sources include inbox items")

    try:
        save_packet_prompt_draft(db, workspace.id, {"title": "No confirm", "draft_body": draft_body})
    except ValueError as exception:
        check("confirm_save" in str(exception), "saving draft rejects missing confirmation")
        db.rollback()
    else:
        check(False, "saving draft rejects missing confirmation")

    saved = save_packet_prompt_draft(
        db,
        workspace.id,
        {
            "confirm_save": True,
            "source_type": "inbox_item",
            "source_id": str(inbox_item.id),
            "inbox_item_id": inbox_item.id,
            "template_id": template.id,
            "title": result["title"],
            "draft_body": draft_body,
            "category": "feature",
            "safety_notes": "Draft only.",
            "verification_notes": "Run verifier.",
        },
    )
    check(saved.status == "draft", "saved packet draft defaults to draft")
    check(saved.inbox_item_id == inbox_item.id, "saved packet draft links inbox item")

    updated = update_packet_prompt_draft(
        db,
        saved,
        {
            "confirm_save": True,
            "title": "Updated Packet Draft",
            "draft_body": draft_body,
            "category": "feature",
        },
    )
    check(updated.title == "Updated Packet Draft", "packet draft can be updated with confirmation")

    try:
        mark_packet_prompt_draft_reviewed(db, updated, {})
    except ValueError as exception:
        check("confirm_review" in str(exception), "mark reviewed rejects missing confirmation")
        db.rollback()
    else:
        check(False, "mark reviewed rejects missing confirmation")

    reviewed = mark_packet_prompt_draft_reviewed(db, updated, {"confirm_review": True})
    check(reviewed.status == "reviewed", "packet draft can be marked reviewed")
    drafts = db.execute(select(PacketPromptDraft)).scalars().all()
    check(len(drafts) == 1, "one packet prompt draft persisted")


def main():
    verify_static_sources()
    verify_docs()
    verify_service_behavior()
    if FAILURES:
        print("FAIL: Packet 030 verification failed")
        return 1
    print("PASS: Packet 030 verification complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
