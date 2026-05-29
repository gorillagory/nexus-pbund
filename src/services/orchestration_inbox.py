from datetime import datetime, timezone

from sqlalchemy import select

from models import OrchestrationInboxItem


INBOX_STATUSES = {"captured", "triaged", "staged", "discarded"}
INBOX_PRIORITIES = {"low", "normal", "high", "urgent"}


def _clean_text(value, max_length=None):
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    value = value.strip()
    if max_length is not None:
        value = value[:max_length]
    return value


def _normalize_status(value):
    status = _clean_text(value, 32).lower()
    return status if status in INBOX_STATUSES else "captured"


def _normalize_priority(value):
    priority = _clean_text(value, 32).lower()
    return priority if priority in INBOX_PRIORITIES else "normal"


def _optional_text(value, max_length=None):
    cleaned = _clean_text(value, max_length)
    return cleaned or None


def serialize_inbox_item(item):
    if item is None:
        return {}
    return {
        "id": getattr(item, "id", None),
        "workspace_id": getattr(item, "workspace_id", None),
        "title": getattr(item, "title", None),
        "raw_intent": getattr(item, "raw_intent", None),
        "source": getattr(item, "source", None),
        "status": getattr(item, "status", None),
        "priority": getattr(item, "priority", None),
        "category": getattr(item, "category", None),
        "triage_notes": getattr(item, "triage_notes", None),
        "created_at": item.created_at.isoformat() if getattr(item, "created_at", None) else None,
        "updated_at": item.updated_at.isoformat() if getattr(item, "updated_at", None) else None,
    }


def create_inbox_item(db, workspace_id, data):
    title = _clean_text(data.get("title"), 255)
    raw_intent = _clean_text(data.get("raw_intent") or data.get("body"))
    if not title:
        raise ValueError("title is required")
    if not raw_intent:
        raise ValueError("raw_intent is required")

    item = OrchestrationInboxItem(
        workspace_id=workspace_id,
        title=title,
        raw_intent=raw_intent,
        source=_clean_text(data.get("source"), 64).lower() or "manual",
        status="captured",
        priority=_normalize_priority(data.get("priority")),
        category=_optional_text(data.get("category"), 64),
        triage_notes=_optional_text(data.get("triage_notes")),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def list_inbox_items(db, workspace_id, status=None):
    statement = select(OrchestrationInboxItem).where(
        OrchestrationInboxItem.workspace_id == workspace_id
    )
    if status:
        statement = statement.where(OrchestrationInboxItem.status == _normalize_status(status))
    statement = statement.order_by(
        OrchestrationInboxItem.created_at.desc(),
        OrchestrationInboxItem.id.desc(),
    )
    return db.execute(statement).scalars().all()


def get_inbox_item(db, workspace_id, item_id):
    item = db.get(OrchestrationInboxItem, item_id)
    if item is None or item.workspace_id != workspace_id:
        return None
    return item


def update_inbox_item(db, item, data):
    if "title" in data:
        title = _clean_text(data.get("title"), 255)
        if not title:
            raise ValueError("title is required")
        item.title = title
    if "raw_intent" in data or "body" in data:
        raw_intent = _clean_text(data.get("raw_intent") or data.get("body"))
        if not raw_intent:
            raise ValueError("raw_intent is required")
        item.raw_intent = raw_intent
    if "source" in data:
        item.source = _clean_text(data.get("source"), 64).lower() or "manual"
    if "status" in data:
        item.status = _normalize_status(data.get("status"))
    if "priority" in data:
        item.priority = _normalize_priority(data.get("priority"))
    if "category" in data:
        item.category = _optional_text(data.get("category"), 64)
    if "triage_notes" in data:
        item.triage_notes = _optional_text(data.get("triage_notes"))
    item.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(item)
    return item


def discard_inbox_item(db, item, triage_notes=None):
    item.status = "discarded"
    if triage_notes is not None:
        item.triage_notes = _optional_text(triage_notes)
    item.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(item)
    return item
