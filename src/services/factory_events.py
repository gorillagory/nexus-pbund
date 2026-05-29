import json
import re

from sqlalchemy import select

from models import ExecutionChangedFile, ExecutionRun, FactoryEvent


SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(
        r"(?i)\b(api[_ -]?key|gemini_api_key|openai_api_key|authorization|secret|token)\b"
        r"(\s*[:=]\s*[\"']?)([^\s\"'`]+)"
    ),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"),
)


def _redact_text(value):
    if value is None:
        return None
    text = str(value)
    text = SECRET_PATTERNS[0].sub("[REDACTED_API_KEY]", text)
    text = SECRET_PATTERNS[1].sub("[REDACTED_API_KEY]", text)
    text = SECRET_PATTERNS[2].sub(
        lambda match: "{}{}[REDACTED_API_KEY]".format(match.group(1), match.group(2)),
        text,
    )
    text = SECRET_PATTERNS[3].sub("Bearer [REDACTED_API_KEY]", text)
    return text


def _as_iso(value):
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else None


def _as_int(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _payload_to_json(payload):
    if payload is None:
        return None
    try:
        return json.dumps(payload, ensure_ascii=True, sort_keys=True)
    except (TypeError, ValueError):
        return json.dumps({"value": _redact_text(payload)}, ensure_ascii=True, sort_keys=True)


def _payload_from_json(payload_json):
    if not payload_json:
        return None
    try:
        payload = json.loads(payload_json)
    except (TypeError, ValueError):
        return {"raw": _redact_text(payload_json)}
    return _redact_payload(payload)


def _redact_payload(value):
    if isinstance(value, dict):
        safe = {}
        for key, item in value.items():
            key_text = str(key)
            if re.search(r"(?i)(api[_ -]?key|secret|token|authorization)", key_text):
                safe[key_text] = "[REDACTED_API_KEY]"
            else:
                safe[key_text] = _redact_payload(item)
        return safe
    if isinstance(value, list):
        return [_redact_payload(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def serialize_factory_event(event):
    if event is None:
        return {}
    return {
        "id": getattr(event, "id", None),
        "workspace_id": getattr(event, "workspace_id", None),
        "work_packet_id": getattr(event, "work_packet_id", None),
        "task_id": getattr(event, "task_id", None),
        "execution_run_id": getattr(event, "execution_run_id", None),
        "event_type": _redact_text(getattr(event, "event_type", None)),
        "message": _redact_text(getattr(event, "message", None)),
        "payload": _payload_from_json(getattr(event, "payload_json", None)),
        "created_at": _as_iso(getattr(event, "created_at", None)),
    }


def serialize_execution_run(run):
    if run is None:
        return {}
    return {
        "id": getattr(run, "id", None),
        "workspace_id": getattr(run, "workspace_id", None),
        "work_packet_id": getattr(run, "work_packet_id", None),
        "task_id": getattr(run, "task_id", None),
        "command": _redact_text(getattr(run, "command", None)),
        "prompt": _redact_text(getattr(run, "prompt", None)),
        "status": _redact_text(getattr(run, "status", None)),
        "returncode": getattr(run, "returncode", None),
        "stdout": _redact_text(getattr(run, "stdout", None)),
        "stderr": _redact_text(getattr(run, "stderr", None)),
        "started_at": _as_iso(getattr(run, "started_at", None)),
        "finished_at": _as_iso(getattr(run, "finished_at", None)),
        "duration_seconds": _as_float(getattr(run, "duration_seconds", None)),
        "provider": _redact_text(getattr(run, "provider", None)),
        "model": _redact_text(getattr(run, "model", None)),
        "input_tokens": _as_int(getattr(run, "input_tokens", None)),
        "output_tokens": _as_int(getattr(run, "output_tokens", None)),
        "total_tokens": _as_int(getattr(run, "total_tokens", None)),
        "estimated_cost_usd": _as_float(getattr(run, "estimated_cost_usd", None)),
        "error_message": _redact_text(getattr(run, "error_message", None)),
    }


def serialize_changed_file(changed_file):
    if changed_file is None:
        return {}
    return {
        "id": getattr(changed_file, "id", None),
        "execution_run_id": getattr(changed_file, "execution_run_id", None),
        "file_path": _redact_text(getattr(changed_file, "file_path", None)),
        "change_type": _redact_text(getattr(changed_file, "change_type", None)),
        "insertions": _as_int(getattr(changed_file, "insertions", None)),
        "deletions": _as_int(getattr(changed_file, "deletions", None)),
        "diff_summary": _redact_text(getattr(changed_file, "diff_summary", None)),
    }


def create_factory_event(
    db,
    workspace_id,
    event_type,
    message,
    work_packet_id=None,
    task_id=None,
    execution_run_id=None,
    payload=None,
):
    event = FactoryEvent(
        workspace_id=workspace_id,
        work_packet_id=work_packet_id,
        task_id=task_id,
        execution_run_id=execution_run_id,
        event_type=_redact_text(event_type) or "event",
        message=_redact_text(message) or "",
        payload_json=_payload_to_json(_redact_payload(payload)),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def _limit_value(limit, default):
    try:
        value = int(limit)
    except (TypeError, ValueError):
        return default
    return max(1, min(value, 500))


def get_recent_factory_events(db, workspace_id=None, limit=100):
    statement = select(FactoryEvent)
    if workspace_id is not None:
        statement = statement.where(FactoryEvent.workspace_id == workspace_id)
    statement = statement.order_by(FactoryEvent.created_at.desc(), FactoryEvent.id.desc())
    statement = statement.limit(_limit_value(limit, 100))
    return db.execute(statement).scalars().all()


def get_recent_execution_runs(db, workspace_id=None, limit=50):
    statement = select(ExecutionRun)
    if workspace_id is not None:
        statement = statement.where(ExecutionRun.workspace_id == workspace_id)
    statement = statement.order_by(ExecutionRun.started_at.desc(), ExecutionRun.id.desc())
    statement = statement.limit(_limit_value(limit, 50))
    return db.execute(statement).scalars().all()


def summarize_factory_state(events, runs):
    events = events or []
    runs = runs or []
    current_state = "idle"
    for run in runs:
        status = (getattr(run, "status", "") or "").lower()
        if status in {"running", "started"}:
            current_state = "running"
            break
        if status in {"failed", "timeout"} and current_state == "idle":
            current_state = "failed"

    return {
        "current_state": current_state,
        "recent_event_count": len(events),
        "recent_run_count": len(runs),
    }
