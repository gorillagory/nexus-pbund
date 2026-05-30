from datetime import datetime, timezone

from models import InboxConversion, Task, WorkPacket, WorkPacketTask
from src.services.git_explorer import redact_git_output
from src.services.orchestration_inbox import serialize_inbox_item
from src.services.trusted_packets import serialize_trust_metadata


CONVERSION_TARGET_TYPES = {"work_packet", "task", "document_update", "discarded"}
CONVERSION_STATUSES = {"converted", "skipped", "failed"}
ELIGIBLE_INBOX_STATUSES = {"captured", "triaged"}


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


def _require_confirm(data, field_name="confirm_convert"):
    if data.get(field_name) is not True:
        raise ValueError("{}=true is required.".format(field_name))


def _require_note(data, keys, message):
    for key in keys:
        value = _clean_text(data.get(key))
        if value:
            return value
    raise ValueError(message)


def _normalize_target_type(value):
    target_type = _clean_text(value, 32).lower()
    if target_type not in CONVERSION_TARGET_TYPES:
        raise ValueError("Unsupported conversion target type.")
    return target_type


def _normalize_conversion_status(value):
    status = _clean_text(value, 32).lower()
    if status not in CONVERSION_STATUSES:
        raise ValueError("Unsupported conversion status.")
    return status


def _ensure_eligible(item):
    if getattr(item, "status", None) not in ELIGIBLE_INBOX_STATUSES:
        raise ValueError("Only captured or triaged inbox items can be converted.")


def _append_triage_note(item, note):
    note = _clean_text(note)
    if not note:
        return
    existing = _clean_text(getattr(item, "triage_notes", None))
    item.triage_notes = "{}\n{}".format(existing, note).strip() if existing else note


def serialize_conversion(conversion):
    if conversion is None:
        return {}
    return {
        "id": getattr(conversion, "id", None),
        "workspace_id": getattr(conversion, "workspace_id", None),
        "inbox_item_id": getattr(conversion, "inbox_item_id", None),
        "target_type": getattr(conversion, "target_type", None),
        "target_id": getattr(conversion, "target_id", None),
        "conversion_status": getattr(conversion, "conversion_status", None),
        "conversion_notes": getattr(conversion, "conversion_notes", None),
        "operator_notes": getattr(conversion, "operator_notes", None),
        "created_at": conversion.created_at.isoformat() if getattr(conversion, "created_at", None) else None,
        "updated_at": conversion.updated_at.isoformat() if getattr(conversion, "updated_at", None) else None,
    }


def summarize_eligible_inbox_item(item):
    serialized = serialize_inbox_item(item)
    status = serialized.get("status")
    eligible = status in ELIGIBLE_INBOX_STATUSES
    return {
        "item": serialized,
        "eligible": eligible,
        "reason": "captured or triaged item can be converted"
        if eligible
        else "only captured or triaged items can be converted",
        "targets": [
            {
                "target_type": "work_packet",
                "label": "Work Packet",
                "supported": eligible,
                "boundary": "creates a staged untrusted work packet; no execution",
            },
            {
                "target_type": "task",
                "label": "Manual Task",
                "supported": eligible,
                "boundary": "creates a todo task; no run-one or auto-run",
            },
            {
                "target_type": "document_update",
                "label": "Document Update Note",
                "supported": eligible,
                "boundary": "records an audit-only document update candidate",
            },
            {
                "target_type": "discarded",
                "label": "Discard With Audit",
                "supported": status != "discarded",
                "boundary": "marks discarded and keeps the inbox item",
            },
        ],
    }


def record_conversion(
    db,
    workspace_id,
    inbox_item,
    target_type,
    target_id=None,
    conversion_status="converted",
    conversion_notes=None,
    operator_notes=None,
):
    conversion = InboxConversion(
        workspace_id=workspace_id,
        inbox_item_id=inbox_item.id,
        target_type=_normalize_target_type(target_type),
        target_id=target_id,
        conversion_status=_normalize_conversion_status(conversion_status),
        conversion_notes=_optional_text(conversion_notes),
        operator_notes=_optional_text(operator_notes),
    )
    db.add(conversion)
    return conversion


def convert_inbox_to_work_packet(db, workspace_id, inbox_item, data):
    _require_confirm(data)
    _ensure_eligible(inbox_item)

    packet_title = _clean_text(data.get("packet_title") or data.get("title") or inbox_item.title, 255)
    goal = _require_note(data, ("goal", "summary", "conversion_notes"), "work packet goal or summary is required.")
    safety_notes = _require_note(data, ("safety_notes",), "safety notes are required.")
    verification_notes = _require_note(data, ("verification_notes",), "verification notes are required.")
    operator_notes = _optional_text(data.get("operator_notes") or data.get("notes"))
    risk_level = _clean_text(data.get("risk_level") or "medium", 64) or "medium"
    estimated_minutes = _optional_text(data.get("estimated_minutes"), 64)
    now = datetime.now(timezone.utc)

    work_packet = WorkPacket(
        workspace_id=workspace_id,
        title=packet_title,
        risk_level=risk_level,
        stop_condition="Safety: {}\nVerification: {}".format(safety_notes, verification_notes),
        estimated_minutes=estimated_minutes,
        status="staged",
        trust_status="unreviewed",
        trust_level="standard",
    )
    db.add(work_packet)
    db.flush()

    task = Task(
        workspace_id=workspace_id,
        title=packet_title,
        description="Inbox conversion goal:\n{}\n\nRaw intent:\n{}".format(
            goal,
            _clean_text(inbox_item.raw_intent),
        ),
        status="todo",
    )
    db.add(task)
    db.flush()

    packet_task = WorkPacketTask(
        work_packet_id=work_packet.id,
        task_id=task.id,
        position=1,
        status="staged",
    )
    db.add(packet_task)

    inbox_item.status = "staged"
    inbox_item.updated_at = now
    _append_triage_note(inbox_item, "Converted to work_packet #{}.".format(work_packet.id))
    conversion = record_conversion(
        db,
        workspace_id,
        inbox_item,
        "work_packet",
        target_id=work_packet.id,
        conversion_notes=goal,
        operator_notes=operator_notes,
    )
    db.commit()
    db.refresh(inbox_item)
    db.refresh(work_packet)
    db.refresh(task)
    db.refresh(conversion)
    return {
        "item": inbox_item,
        "conversion": conversion,
        "work_packet": work_packet,
        "task": task,
        "trust": serialize_trust_metadata(work_packet),
    }


def convert_inbox_to_task(db, workspace_id, inbox_item, data):
    _require_confirm(data)
    _ensure_eligible(inbox_item)

    title = _clean_text(data.get("task_title") or data.get("title") or inbox_item.title, 255)
    details = _require_note(data, ("task_description", "summary", "conversion_notes"), "task description or summary is required.")
    operator_notes = _optional_text(data.get("operator_notes") or data.get("notes"))
    now = datetime.now(timezone.utc)

    task = Task(
        workspace_id=workspace_id,
        title=title,
        description="Inbox conversion task:\n{}\n\nRaw intent:\n{}".format(
            details,
            _clean_text(inbox_item.raw_intent),
        ),
        status="todo",
    )
    db.add(task)
    db.flush()

    inbox_item.status = "staged"
    inbox_item.updated_at = now
    _append_triage_note(inbox_item, "Converted to task #{}.".format(task.id))
    conversion = record_conversion(
        db,
        workspace_id,
        inbox_item,
        "task",
        target_id=task.id,
        conversion_notes=details,
        operator_notes=operator_notes,
    )
    db.commit()
    db.refresh(inbox_item)
    db.refresh(task)
    db.refresh(conversion)
    return {"item": inbox_item, "conversion": conversion, "task": task}


def convert_inbox_to_document_update(db, workspace_id, inbox_item, data):
    _require_confirm(data)
    _ensure_eligible(inbox_item)

    notes = _require_note(data, ("document_notes", "conversion_notes", "summary"), "document update notes are required.")
    operator_notes = _optional_text(data.get("operator_notes") or data.get("notes"))
    now = datetime.now(timezone.utc)
    inbox_item.status = "triaged"
    inbox_item.updated_at = now
    _append_triage_note(inbox_item, "Marked as document update candidate.")
    conversion = record_conversion(
        db,
        workspace_id,
        inbox_item,
        "document_update",
        target_id=None,
        conversion_notes=notes,
        operator_notes=operator_notes,
    )
    db.commit()
    db.refresh(inbox_item)
    db.refresh(conversion)
    return {"item": inbox_item, "conversion": conversion}


def discard_inbox_with_audit(db, workspace_id, inbox_item, data):
    _require_confirm(data, field_name="confirm_discard")
    if getattr(inbox_item, "status", None) == "discarded":
        raise ValueError("Inbox item is already discarded.")

    reason = _require_note(data, ("discard_reason", "reason", "conversion_notes", "operator_notes"), "discard reason is required.")
    operator_notes = _optional_text(data.get("operator_notes") or data.get("notes"))
    now = datetime.now(timezone.utc)
    inbox_item.status = "discarded"
    inbox_item.updated_at = now
    _append_triage_note(inbox_item, "Discarded with audit: {}".format(reason))
    conversion = record_conversion(
        db,
        workspace_id,
        inbox_item,
        "discarded",
        target_id=None,
        conversion_status="converted",
        conversion_notes=reason,
        operator_notes=operator_notes,
    )
    db.commit()
    db.refresh(inbox_item)
    db.refresh(conversion)
    return {"item": inbox_item, "conversion": conversion}
