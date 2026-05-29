import json
import os
import re
from datetime import datetime, timezone


LEDGER_DIR = ".nexus"
LEDGER_FILE = "cost_ledger.jsonl"
EVENT_FIELDS = (
    "timestamp",
    "source",
    "provider",
    "model",
    "task_id",
    "total_tokens",
    "input_tokens",
    "output_tokens",
    "estimated_cost_usd",
    "notes",
)
INTEGER_FIELDS = {"total_tokens", "input_tokens", "output_tokens"}
FLOAT_FIELDS = {"estimated_cost_usd"}
TEXT_FIELDS = {"timestamp", "source", "provider", "model", "task_id", "notes"}
SECRET_VALUE_PATTERN = re.compile(
    r"(?i)\b(api[_ -]?key|authorization|secret|token)\b"
    r"(\s*[:=]\s*)[^\n\r\"'`]+"
)
BEARER_PATTERN = re.compile(
    r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"
)
RAW_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
)


def ensure_ledger_dir(root_dir):
    path = os.path.join(os.path.abspath(os.path.expanduser(str(root_dir))), LEDGER_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def ledger_path(root_dir):
    return os.path.join(
        os.path.abspath(os.path.expanduser(str(root_dir))), LEDGER_DIR, LEDGER_FILE
    )


def _utc_timestamp():
    return datetime.now(timezone.utc).isoformat()


def _redact_secrets(value):
    if not isinstance(value, str):
        return value
    value = SECRET_VALUE_PATTERN.sub(
        lambda match: "%s%s[REDACTED]" % (match.group(1), match.group(2)), value
    )
    value = BEARER_PATTERN.sub("Bearer [REDACTED]", value)
    for pattern in RAW_SECRET_PATTERNS:
        value = pattern.sub("[REDACTED]", value)
    return value


def _coerce_int(value):
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_float(value):
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_event(event):
    if not isinstance(event, dict):
        event = {}

    clean = {"timestamp": _redact_secrets(str(event.get("timestamp") or _utc_timestamp()))}
    for field in EVENT_FIELDS:
        if field == "timestamp" or field not in event:
            continue

        value = event.get(field)
        if field in INTEGER_FIELDS:
            value = _coerce_int(value)
        elif field in FLOAT_FIELDS:
            value = _coerce_float(value)
        elif field in TEXT_FIELDS and value is not None:
            value = _redact_secrets(str(value))

        if value is not None:
            clean[field] = value

    return clean


def append_cost_event(root_dir, event):
    record = _clean_event(event)
    ensure_ledger_dir(root_dir)
    with open(ledger_path(root_dir), "a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n")
    return record


def read_cost_events(root_dir, limit=100):
    path = ledger_path(root_dir)
    try:
        limit_value = int(limit)
    except (TypeError, ValueError):
        limit_value = 100
    if limit_value <= 0:
        return []

    events = []
    try:
        with open(path, "r", encoding="utf-8") as file:
            for line in file:
                try:
                    payload = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if isinstance(payload, dict):
                    events.append(_clean_event(payload))
    except OSError:
        return []

    return events[-limit_value:]


def summarize_cost_events(events):
    summary = {
        "event_count": 0,
        "total_tokens": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "estimated_cost_usd": 0.0,
        "by_provider": {},
        "by_model": {},
    }

    for event in events or []:
        if not isinstance(event, dict):
            continue

        clean = _clean_event(event)
        summary["event_count"] += 1
        for field in INTEGER_FIELDS:
            summary[field] += clean.get(field, 0)
        summary["estimated_cost_usd"] += clean.get("estimated_cost_usd", 0.0)

        provider = clean.get("provider")
        if provider:
            summary["by_provider"][provider] = summary["by_provider"].get(provider, 0) + 1

        model = clean.get("model")
        if model:
            summary["by_model"][model] = summary["by_model"].get(model, 0) + 1

    summary["estimated_cost_usd"] = round(summary["estimated_cost_usd"], 6)
    return summary
