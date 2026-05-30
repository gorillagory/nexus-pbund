import json
from datetime import datetime, timezone

from sqlalchemy import select

from models import OperatorReviewEvent
from src.services.git_explorer import redact_git_output


REVIEW_EVENT_TYPES = {
    "inbox_conversion",
    "readiness_check",
    "trust_decision",
    "intervention_decision",
    "recovery_decision",
    "draft_review",
    "manual_note",
}
REVIEW_SEVERITIES = {"info", "warning", "blocked", "critical"}
MAX_TEXT_CHARS = 4000
MAX_LIST_LIMIT = 100


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


def _normalize_event_type(value):
    event_type = _clean_text(value, 64).lower()
    return event_type if event_type in REVIEW_EVENT_TYPES else "manual_note"


def _normalize_severity(value):
    severity = _clean_text(value, 32).lower()
    return severity if severity in REVIEW_SEVERITIES else "info"


def _require_confirm(data, field_name):
    if data.get(field_name) is not True:
        raise ValueError("{}=true is required.".format(field_name))


def _encode_metadata(value):
    if value in (None, ""):
        return None
    if not isinstance(value, (dict, list)):
        return None
    redacted = _redact_metadata_value(value)
    return json.dumps(redacted, ensure_ascii=True, sort_keys=True)


def _redact_metadata_value(value):
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            clean_key = _clean_text(key, 128)
            if any(marker in clean_key.lower() for marker in ("key", "token", "secret", "password", "passwd", "pwd", "authorization")):
                redacted[clean_key] = "[redacted]"
            else:
                redacted[clean_key] = _redact_metadata_value(item)
        return redacted
    if isinstance(value, list):
        return [_redact_metadata_value(item) for item in value[:50]]
    if isinstance(value, str):
        return _clean_text(value, MAX_TEXT_CHARS)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _clean_text(value, MAX_TEXT_CHARS)


def _parse_metadata(value):
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def serialize_review_event(event):
    if event is None:
        return {}
    return {
        "id": getattr(event, "id", None),
        "workspace_id": getattr(event, "workspace_id", None),
        "event_type": getattr(event, "event_type", None),
        "action": getattr(event, "action", None),
        "title": getattr(event, "title", None),
        "summary": getattr(event, "summary", None),
        "details": getattr(event, "details", None),
        "actor": getattr(event, "actor", None),
        "source_type": getattr(event, "source_type", None),
        "source_id": getattr(event, "source_id", None),
        "related_type": getattr(event, "related_type", None),
        "related_id": getattr(event, "related_id", None),
        "severity": getattr(event, "severity", None),
        "status": getattr(event, "status", None),
        "metadata": _parse_metadata(getattr(event, "metadata_json", None)),
        "created_at": event.created_at.isoformat() if getattr(event, "created_at", None) else None,
        "updated_at": event.updated_at.isoformat() if getattr(event, "updated_at", None) else None,
    }


def create_review_event(db, workspace_id, data, commit=True):
    title = _clean_text(data.get("title"), 255)
    summary = _clean_text(data.get("summary") or data.get("details"), MAX_TEXT_CHARS)
    action = _clean_text(data.get("action") or "noted", 64).lower() or "noted"
    if not title:
        raise ValueError("title is required")
    if not summary:
        raise ValueError("summary is required")

    event = OperatorReviewEvent(
        workspace_id=workspace_id,
        event_type=_normalize_event_type(data.get("event_type")),
        action=action,
        title=title,
        summary=summary,
        details=_optional_text(data.get("details"), MAX_TEXT_CHARS),
        actor=_optional_text(data.get("actor") or data.get("operator"), 128),
        source_type=_optional_text(data.get("source_type"), 64),
        source_id=_optional_text(data.get("source_id"), 128),
        related_type=_optional_text(data.get("related_type"), 64),
        related_id=_optional_text(data.get("related_id"), 128),
        severity=_normalize_severity(data.get("severity")),
        status=_optional_text(data.get("status"), 64),
        metadata_json=_encode_metadata(data.get("metadata")),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(event)
    if commit:
        db.commit()
        db.refresh(event)
    return event


def create_manual_review_note(db, workspace_id, data):
    _require_confirm(data, "confirm_create")
    payload = dict(data)
    payload["event_type"] = "manual_note"
    payload["action"] = payload.get("action") or "manual_note"
    return create_review_event(db, workspace_id, payload, commit=True)


def list_review_events(db, workspace_id, event_type=None, severity=None, source_type=None, limit=50):
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 50
    limit = max(1, min(limit, MAX_LIST_LIMIT))
    statement = select(OperatorReviewEvent).where(OperatorReviewEvent.workspace_id == workspace_id)
    if event_type:
        statement = statement.where(OperatorReviewEvent.event_type == _normalize_event_type(event_type))
    if severity:
        statement = statement.where(OperatorReviewEvent.severity == _normalize_severity(severity))
    if source_type:
        statement = statement.where(OperatorReviewEvent.source_type == _clean_text(source_type, 64))
    statement = statement.order_by(OperatorReviewEvent.created_at.desc(), OperatorReviewEvent.id.desc()).limit(limit)
    return db.execute(statement).scalars().all()


def build_timeline_filters():
    return {
        "event_types": sorted(REVIEW_EVENT_TYPES),
        "severities": sorted(REVIEW_SEVERITIES),
        "source_types": [
            "inbox_item",
            "work_packet",
            "packet_prompt_draft",
            "operator_intervention",
            "task",
            "manual",
        ],
    }


def summarize_review_history(db, workspace_id):
    events = list_review_events(db, workspace_id, limit=MAX_LIST_LIMIT)
    by_type = {}
    by_severity = {}
    for event in events:
        by_type[event.event_type] = by_type.get(event.event_type, 0) + 1
        by_severity[event.severity] = by_severity.get(event.severity, 0) + 1
    return {
        "total_loaded": len(events),
        "by_type": by_type,
        "by_severity": by_severity,
    }
