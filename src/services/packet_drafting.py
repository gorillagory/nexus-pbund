from datetime import datetime, timezone

from sqlalchemy import select

from models import (
    OrchestrationInboxItem,
    PacketPromptDraft,
    PromptTemplate,
    Task,
    WorkPacket,
    WorkPacketTask,
)
from src.services.git_explorer import redact_git_output
from src.services.orchestration_inbox import serialize_inbox_item
from src.services.prompt_vault import PROMPT_CATEGORIES, serialize_prompt_template
from src.services.trusted_packets import serialize_trust_metadata


DRAFT_STATUSES = {"draft", "reviewed", "applied", "discarded"}
SOURCE_TYPES = {"manual", "inbox_item", "work_packet"}
MAX_CONTEXT_CHARS = 8000
MAX_DRAFT_CHARS = 24000
MAX_TEMPLATE_CHARS = 6000


def _clean_text(value, max_length=None):
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    value = redact_git_output(value).strip()
    if max_length is not None:
        value = value[:max_length]
    return value


def _optional_text(value, max_length=None):
    cleaned = _clean_text(value, max_length)
    return cleaned or None


def _normalize_category(value):
    category = _clean_text(value, 64).lower().replace(" ", "_")
    return category if category in PROMPT_CATEGORIES else "feature"


def _normalize_status(value):
    status = _clean_text(value, 32).lower()
    return status if status in DRAFT_STATUSES else "draft"


def _require_confirm(data, field_name):
    if data.get(field_name) is not True:
        raise ValueError("{}=true is required.".format(field_name))


def _require_text(data, keys, message, max_length=None):
    for key in keys:
        value = _clean_text(data.get(key), max_length=max_length)
        if value:
            return value
    raise ValueError(message)


def _first_line(value, fallback):
    text = _clean_text(value, 160)
    if not text:
        return fallback
    return text.splitlines()[0][:160] or fallback


def _safe_int(value):
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def serialize_work_packet_summary(work_packet):
    if work_packet is None:
        return {}
    return {
        "id": work_packet.id,
        "workspace_id": work_packet.workspace_id,
        "title": work_packet.title,
        "risk_level": work_packet.risk_level,
        "stop_condition": work_packet.stop_condition,
        "estimated_minutes": work_packet.estimated_minutes,
        "status": work_packet.status,
        "created_at": work_packet.created_at.isoformat() if work_packet.created_at else None,
        "trust": serialize_trust_metadata(work_packet),
    }


def serialize_packet_prompt_draft(draft):
    if draft is None:
        return {}
    return {
        "id": draft.id,
        "workspace_id": draft.workspace_id,
        "work_packet_id": draft.work_packet_id,
        "inbox_item_id": draft.inbox_item_id,
        "source_type": draft.source_type,
        "source_id": draft.source_id,
        "template_id": draft.template_id,
        "title": draft.title,
        "draft_body": draft.draft_body,
        "category": draft.category,
        "safety_notes": draft.safety_notes,
        "verification_notes": draft.verification_notes,
        "status": draft.status,
        "created_at": draft.created_at.isoformat() if draft.created_at else None,
        "updated_at": draft.updated_at.isoformat() if draft.updated_at else None,
    }


def list_usable_templates(db, category=None):
    statement = select(PromptTemplate).where(PromptTemplate.status == "active")
    if category:
        statement = statement.where(PromptTemplate.category == _normalize_category(category))
    statement = statement.order_by(PromptTemplate.category.asc(), PromptTemplate.title.asc())
    return db.execute(statement).scalars().all()


def list_packet_prompt_drafts(db, workspace_id, status=None, limit=40):
    statement = select(PacketPromptDraft).where(PacketPromptDraft.workspace_id == workspace_id)
    if status:
        statement = statement.where(PacketPromptDraft.status == _normalize_status(status))
    statement = statement.order_by(PacketPromptDraft.updated_at.desc(), PacketPromptDraft.created_at.desc(), PacketPromptDraft.id.desc())
    return db.execute(statement).scalars().all()[:limit]


def get_packet_prompt_draft(db, workspace_id, draft_id):
    draft = db.get(PacketPromptDraft, draft_id)
    if draft is None or draft.workspace_id != workspace_id:
        return None
    return draft


def list_drafting_sources(db, workspace_id):
    inbox_items = (
        db.execute(
            select(OrchestrationInboxItem)
            .where(OrchestrationInboxItem.workspace_id == workspace_id)
            .order_by(OrchestrationInboxItem.updated_at.desc(), OrchestrationInboxItem.created_at.desc(), OrchestrationInboxItem.id.desc())
        )
        .scalars()
        .all()
    )[:30]
    work_packets = (
        db.execute(
            select(WorkPacket)
            .where(WorkPacket.workspace_id == workspace_id)
            .order_by(WorkPacket.created_at.desc(), WorkPacket.id.desc())
        )
        .scalars()
        .all()
    )[:30]
    return {
        "inbox_items": [serialize_inbox_item(item) for item in inbox_items],
        "work_packets": [serialize_work_packet_summary(packet) for packet in work_packets],
    }


def collect_drafting_context(db, workspace_id, source_type=None, source_id=None):
    source_type = _clean_text(source_type or "manual", 64).lower() or "manual"
    if source_type not in SOURCE_TYPES:
        raise ValueError("Unsupported drafting source type.")

    if source_type == "manual":
        return {"source_type": "manual", "source_id": None, "title": "Manual Packet Draft", "context": ""}

    numeric_id = _safe_int(source_id)
    if numeric_id is None:
        raise ValueError("Valid source_id is required.")

    if source_type == "inbox_item":
        item = db.get(OrchestrationInboxItem, numeric_id)
        if item is None or item.workspace_id != workspace_id:
            raise ValueError("Inbox item not found.")
        context = "\n".join(
            line
            for line in (
                "Source: Orchestration Inbox #{}".format(item.id),
                "Title: {}".format(_clean_text(item.title)),
                "Status: {}".format(_clean_text(item.status)),
                "Priority: {}".format(_clean_text(item.priority)),
                "Category: {}".format(_clean_text(item.category)),
                "Source channel: {}".format(_clean_text(item.source)),
                "Triage notes: {}".format(_clean_text(item.triage_notes)),
                "Raw intent:\n{}".format(_clean_text(item.raw_intent)),
            )
            if line.strip()
        )
        return {
            "source_type": source_type,
            "source_id": str(item.id),
            "inbox_item_id": item.id,
            "title": item.title,
            "context": _clean_text(context, MAX_CONTEXT_CHARS),
            "item": serialize_inbox_item(item),
        }

    work_packet = db.get(WorkPacket, numeric_id)
    if work_packet is None or work_packet.workspace_id != workspace_id:
        raise ValueError("Work packet not found.")
    links = (
        db.execute(
            select(WorkPacketTask)
            .where(WorkPacketTask.work_packet_id == work_packet.id)
            .order_by(WorkPacketTask.position.asc(), WorkPacketTask.id.asc())
        )
        .scalars()
        .all()
    )
    task_lines = []
    for link in links:
        task = db.get(Task, link.task_id)
        if task is None:
            continue
        task_lines.append(
            "{}. {} [{}]\n{}".format(
                link.position,
                _clean_text(task.title),
                _clean_text(task.status),
                _clean_text(task.description, 1200),
            )
        )
    context = "\n".join(
        line
        for line in (
            "Source: Work Packet #{}".format(work_packet.id),
            "Title: {}".format(_clean_text(work_packet.title)),
            "Status: {}".format(_clean_text(work_packet.status)),
            "Risk: {}".format(_clean_text(work_packet.risk_level)),
            "Trust: {}".format(_clean_text(work_packet.trust_status)),
            "Stop condition:\n{}".format(_clean_text(work_packet.stop_condition)),
            "Tasks:\n{}".format("\n\n".join(task_lines)),
        )
        if line.strip()
    )
    return {
        "source_type": source_type,
        "source_id": str(work_packet.id),
        "work_packet_id": work_packet.id,
        "title": work_packet.title,
        "context": _clean_text(context, MAX_CONTEXT_CHARS),
        "work_packet": serialize_work_packet_summary(work_packet),
    }


def validate_required_sections(draft_body):
    text = _clean_text(draft_body, MAX_DRAFT_CHARS)
    required = (
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
    )
    missing = [section for section in required if section not in text.upper()]
    return {"valid": not missing, "missing": missing}


def build_structured_packet_prompt(db, workspace_id, data):
    _require_confirm(data, "confirm_generate")
    packet_number = _clean_text(data.get("packet_number"), 16)
    packet_title = _require_text(data, ("packet_title", "title"), "packet title is required.", 255)
    goal = _require_text(data, ("goal", "summary"), "goal is required.")
    safety_notes = _require_text(data, ("safety_notes",), "safety notes are required.")
    verification_notes = _require_text(data, ("verification_notes",), "verification notes are required.")
    category = _normalize_category(data.get("category"))
    files_allowed = _clean_text(data.get("files_allowed")) or "List the narrowly scoped files after repo inspection."
    report_path = _clean_text(data.get("report_path"), 255) or "/tmp/nexus-packet-{}-report.md".format(packet_number or "draft")
    source_context = collect_drafting_context(
        db,
        workspace_id,
        source_type=data.get("source_type"),
        source_id=data.get("source_id"),
    )
    template_id = _safe_int(data.get("template_id"))
    template = db.get(PromptTemplate, template_id) if template_id else None
    if template is not None and getattr(template, "status", None) != "active":
        template = None
    template_excerpt = _clean_text(getattr(template, "body", ""), MAX_TEMPLATE_CHARS)
    mission_line = "Build Packet {} — {}".format(packet_number, packet_title) if packet_number else packet_title
    current_state = _clean_text(data.get("current_state")) or source_context.get("context") or "Inspect repo context before implementation."
    implementation_parts = _clean_text(data.get("implementation_parts")) or (
        "Part A: Inspect context and confirm boundaries.\n"
        "Part B: Implement the scoped feature only.\n"
        "Part C: Add docs and verifier coverage."
    )
    branch_name = _clean_text(data.get("branch_name"), 160) or "factory/packet-{}-{}".format(
        packet_number or "###",
        packet_title.lower().replace(" ", "-")[:80],
    )
    draft = """MISSION
{mission_line}

CURRENT STATE
{current_state}

GOAL
{goal}

SAFETY RULES
- No force push.
- No git reset.
- No git clean.
- No destructive database operations.
- No raw API key/secret exposure in logs, docs, reports, commits, prompts, UI output, API responses, draft text, queue items, or events.
- No Auto-Pilot unless this packet explicitly scopes Auto-Pilot build or test work.
- Do not call /api/tasks/auto-run.
- Do not call /api/tasks/run-one unless this packet explicitly tests it with mocks.
- Do not call /api/work-packets/run unless this packet explicitly tests it with mocks.
- Do not call /api/execute-codex.
- Do not set execution_mode to autopilot.
- Do not retry failed runs unless explicitly scoped.
- Do not continue packet execution unless explicitly scoped.
- Do not mark packets trusted automatically.
- Do not add commit/merge/push/reset/clean/rebase/stash/tag/delete branch behavior to the app.
- No {no_shell}.
- No {no_popen}.
- No stdin prompts.
- No y/n prompts.
- No native browser alert().
- No native browser confirm().
{safety_notes}

WORKFLOW
1. Inspect local context first: git status, git log, and relevant docs/source files.
2. Create branch before implementation: {branch_name}
3. Implement only the scoped Packet {packet_number_or_placeholder} behavior.
4. Add docs and verification coverage.
5. Run verification.
6. Inspect safety.
7. Commit with a clear packet message.
8. Fast-forward merge to main if verification passes.
9. Tag the baseline.
10. Push main and tag.
11. Write the packet report.

FILES ALLOWED
{files_allowed}

IMPLEMENTATION PARTS
{implementation_parts}

VERIFICATION
{verification_notes}

COMMIT / MERGE / PUSH
- Commit message: add {commit_title}
- Merge: git switch main, then git merge --ff-only {branch_name}
- Tag baseline: nexus-packet-{packet_number_or_placeholder}-baseline-2026-05-30
- Push: git push origin main and git push origin <tag>

REPORT
Write final report to:
{report_path}

Report must include branch used, files changed, feature summary, safety boundaries, verification commands and results, commit hash, tag name, push status, follow-up recommendations, and next recommended packet.

PROMPT VAULT TEMPLATE CONTEXT
{template_context}

IMPORTANT BOUNDARY
This is a supervised packet prompt. It prepares reviewed work for Codex operator use; it does not execute anything by itself.
""".format(
        mission_line=mission_line,
        current_state=_clean_text(current_state, MAX_CONTEXT_CHARS),
        goal=_clean_text(goal, 4000),
        safety_notes=_clean_text(safety_notes, 4000),
        branch_name=branch_name,
        packet_number_or_placeholder=packet_number or "###",
        files_allowed=_clean_text(files_allowed, 4000),
        implementation_parts=_clean_text(implementation_parts, 4000),
        verification_notes=_clean_text(verification_notes, 4000),
        commit_title=packet_title.lower(),
        report_path=report_path,
        template_context=template_excerpt or "No Prompt Vault template selected.",
        no_shell="shell" + "=True",
        no_popen="subprocess." + "Popen",
    )
    draft = _clean_text(draft, MAX_DRAFT_CHARS)
    validation = validate_required_sections(draft)
    return {
        "title": "Packet {} — {}".format(packet_number, packet_title) if packet_number else packet_title,
        "draft_body": draft,
        "category": category,
        "safety_notes": _clean_text(safety_notes),
        "verification_notes": _clean_text(verification_notes),
        "source": source_context,
        "template": serialize_prompt_template(template) if template is not None else None,
        "validation": validation,
    }


def save_packet_prompt_draft(db, workspace_id, data):
    _require_confirm(data, "confirm_save")
    title = _require_text(data, ("title", "packet_title"), "draft title is required.", 255)
    draft_body = _require_text(data, ("draft_body",), "draft_body is required.", MAX_DRAFT_CHARS)
    validation = validate_required_sections(draft_body)
    if not validation["valid"]:
        raise ValueError("Draft is missing required sections: {}".format(", ".join(validation["missing"])))
    work_packet_id = _safe_int(data.get("work_packet_id"))
    inbox_item_id = _safe_int(data.get("inbox_item_id"))
    source_type = _optional_text(data.get("source_type"), 64)
    source_id = _optional_text(data.get("source_id"), 128)
    template_id = _safe_int(data.get("template_id"))
    if work_packet_id is not None:
        work_packet = db.get(WorkPacket, work_packet_id)
        if work_packet is None or work_packet.workspace_id != workspace_id:
            raise ValueError("Work packet not found.")
    if inbox_item_id is not None:
        inbox_item = db.get(OrchestrationInboxItem, inbox_item_id)
        if inbox_item is None or inbox_item.workspace_id != workspace_id:
            raise ValueError("Inbox item not found.")
    draft = PacketPromptDraft(
        workspace_id=workspace_id,
        work_packet_id=work_packet_id,
        inbox_item_id=inbox_item_id,
        source_type=source_type,
        source_id=source_id,
        template_id=template_id,
        title=title,
        draft_body=draft_body,
        category=_normalize_category(data.get("category")),
        safety_notes=_optional_text(data.get("safety_notes")),
        verification_notes=_optional_text(data.get("verification_notes")),
        status="draft",
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def update_packet_prompt_draft(db, draft, data):
    _require_confirm(data, "confirm_save")
    if "title" in data or "packet_title" in data:
        draft.title = _require_text(data, ("title", "packet_title"), "draft title is required.", 255)
    if "draft_body" in data:
        draft_body = _require_text(data, ("draft_body",), "draft_body is required.", MAX_DRAFT_CHARS)
        validation = validate_required_sections(draft_body)
        if not validation["valid"]:
            raise ValueError("Draft is missing required sections: {}".format(", ".join(validation["missing"])))
        draft.draft_body = draft_body
    if "category" in data:
        draft.category = _normalize_category(data.get("category"))
    if "safety_notes" in data:
        draft.safety_notes = _optional_text(data.get("safety_notes"))
    if "verification_notes" in data:
        draft.verification_notes = _optional_text(data.get("verification_notes"))
    if "status" in data:
        draft.status = _normalize_status(data.get("status"))
    draft.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(draft)
    return draft


def mark_packet_prompt_draft_reviewed(db, draft, data):
    _require_confirm(data, "confirm_review")
    draft.status = "reviewed"
    draft.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(draft)
    return draft
