import json
from datetime import datetime, timezone

from sqlalchemy import select

from models import OperatorIntervention
from src.services.git_explorer import redact_git_output


INTERVENTION_STATUSES = {"open", "acknowledged", "resolved", "dismissed"}
INTERVENTION_SEVERITIES = {"info", "warning", "blocked", "critical"}


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


def _normalize_status(value):
    status = _clean_text(value, 32).lower()
    return status if status in INTERVENTION_STATUSES else "open"


def _normalize_severity(value):
    severity = _clean_text(value, 32).lower()
    return severity if severity in INTERVENTION_SEVERITIES else "warning"


def _encode_context(value):
    if value in (None, ""):
        return None
    if not isinstance(value, (dict, list)):
        return None
    redacted = json.loads(redact_git_output(json.dumps(value, ensure_ascii=True, sort_keys=True)))
    return json.dumps(redacted, ensure_ascii=True, sort_keys=True)


def _parse_context(value):
    if value in (None, ""):
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def serialize_intervention(item):
    if item is None:
        return {}
    return {
        "id": getattr(item, "id", None),
        "workspace_id": getattr(item, "workspace_id", None),
        "title": getattr(item, "title", None),
        "details": getattr(item, "details", None),
        "source_type": getattr(item, "source_type", None),
        "source_id": getattr(item, "source_id", None),
        "severity": getattr(item, "severity", None),
        "status": getattr(item, "status", None),
        "category": getattr(item, "category", None),
        "recommended_action": getattr(item, "recommended_action", None),
        "operator_notes": getattr(item, "operator_notes", None),
        "context": _parse_context(getattr(item, "context_json", None)),
        "created_at": item.created_at.isoformat() if getattr(item, "created_at", None) else None,
        "updated_at": item.updated_at.isoformat() if getattr(item, "updated_at", None) else None,
        "acknowledged_at": item.acknowledged_at.isoformat() if getattr(item, "acknowledged_at", None) else None,
        "resolved_at": item.resolved_at.isoformat() if getattr(item, "resolved_at", None) else None,
    }


def create_intervention(db, workspace_id, data):
    title = _clean_text(data.get("title"), 255)
    details = _clean_text(data.get("details") or data.get("body"))
    if not title:
        raise ValueError("title is required")
    if not details:
        raise ValueError("details is required")

    item = OperatorIntervention(
        workspace_id=workspace_id,
        title=title,
        details=details,
        source_type=_optional_text(data.get("source_type"), 64),
        source_id=_optional_text(data.get("source_id"), 128),
        severity=_normalize_severity(data.get("severity")),
        status="open",
        category=_optional_text(data.get("category"), 64),
        recommended_action=_optional_text(data.get("recommended_action")),
        operator_notes=_optional_text(data.get("operator_notes")),
        context_json=_encode_context(data.get("context")),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def list_interventions(db, workspace_id, status=None, severity=None):
    statement = select(OperatorIntervention).where(OperatorIntervention.workspace_id == workspace_id)
    if status:
        statement = statement.where(OperatorIntervention.status == _normalize_status(status))
    if severity:
        statement = statement.where(OperatorIntervention.severity == _normalize_severity(severity))
    statement = statement.order_by(OperatorIntervention.created_at.desc(), OperatorIntervention.id.desc())
    return db.execute(statement).scalars().all()


def get_intervention(db, workspace_id, intervention_id):
    item = db.get(OperatorIntervention, intervention_id)
    if item is None or item.workspace_id != workspace_id:
        return None
    return item


def update_intervention(db, item, data):
    if "title" in data:
        title = _clean_text(data.get("title"), 255)
        if not title:
            raise ValueError("title is required")
        item.title = title
    if "details" in data or "body" in data:
        details = _clean_text(data.get("details") or data.get("body"))
        if not details:
            raise ValueError("details is required")
        item.details = details
    if "source_type" in data:
        item.source_type = _optional_text(data.get("source_type"), 64)
    if "source_id" in data:
        item.source_id = _optional_text(data.get("source_id"), 128)
    if "severity" in data:
        item.severity = _normalize_severity(data.get("severity"))
    if "category" in data:
        item.category = _optional_text(data.get("category"), 64)
    if "recommended_action" in data:
        item.recommended_action = _optional_text(data.get("recommended_action"))
    if "operator_notes" in data:
        item.operator_notes = _optional_text(data.get("operator_notes"))
    if "context" in data:
        item.context_json = _encode_context(data.get("context"))
    item.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(item)
    return item


def acknowledge_intervention(db, item, operator_notes=None):
    item.status = "acknowledged"
    if operator_notes is not None:
        item.operator_notes = _optional_text(operator_notes)
    item.acknowledged_at = datetime.now(timezone.utc)
    item.updated_at = item.acknowledged_at
    db.commit()
    db.refresh(item)
    return item


def resolve_intervention(db, item, operator_notes=None):
    item.status = "resolved"
    if operator_notes is not None:
        item.operator_notes = _optional_text(operator_notes)
    item.resolved_at = datetime.now(timezone.utc)
    item.updated_at = item.resolved_at
    db.commit()
    db.refresh(item)
    return item


def dismiss_intervention(db, item, operator_notes=None):
    item.status = "dismissed"
    if operator_notes is not None:
        item.operator_notes = _optional_text(operator_notes)
    item.resolved_at = datetime.now(timezone.utc)
    item.updated_at = item.resolved_at
    db.commit()
    db.refresh(item)
    return item
