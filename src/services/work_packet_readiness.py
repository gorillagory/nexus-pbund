import json
from datetime import datetime, timezone

from sqlalchemy import select

from models import PacketPromptDraft, Task, WorkPacketTask
from src.services.git_explorer import redact_git_output
from src.services.trusted_packets import serialize_trust_metadata


READINESS_STATUSES = {"incomplete", "ready_for_review", "ready_for_trust", "blocked"}
MAX_TEXT_CHARS = 6000
MAX_NOTE_CHARS = 4000
NO_SHELL_TRUE = "shell" + "=True"
NO_POPEN = "subprocess." + "Popen"


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
    return status if status in READINESS_STATUSES else "incomplete"


def _require_confirm(data, field_name):
    if data.get(field_name) is not True:
        raise ValueError("{}=true is required.".format(field_name))


def _contains_any(text, values):
    lowered = _clean_text(text).lower()
    return any(value.lower() in lowered for value in values)


def _latest_prompt_draft(db, work_packet_id):
    return (
        db.execute(
            select(PacketPromptDraft)
            .where(PacketPromptDraft.work_packet_id == work_packet_id)
            .order_by(PacketPromptDraft.updated_at.desc(), PacketPromptDraft.created_at.desc(), PacketPromptDraft.id.desc())
        )
        .scalars()
        .first()
    )


def _packet_tasks(db, work_packet_id):
    links = (
        db.execute(
            select(WorkPacketTask)
            .where(WorkPacketTask.work_packet_id == work_packet_id)
            .order_by(WorkPacketTask.position.asc(), WorkPacketTask.id.asc())
        )
        .scalars()
        .all()
    )
    tasks = []
    for link in links:
        task = db.get(Task, link.task_id)
        if task is not None:
            tasks.append((link, task))
    return tasks


def collect_work_packet_readiness_context(db, work_packet):
    draft = _latest_prompt_draft(db, work_packet.id)
    tasks = _packet_tasks(db, work_packet.id)
    task_text = "\n\n".join(
        "{}. {} [{}]\n{}".format(
            link.position,
            _clean_text(task.title, 255),
            _clean_text(task.status, 32),
            _clean_text(task.description, 1200),
        )
        for link, task in tasks
    )
    draft_text = _clean_text(getattr(draft, "draft_body", ""), MAX_TEXT_CHARS)
    context_text = _clean_text(
        "\n".join(
            (
                _clean_text(work_packet.title, 255),
                _clean_text(work_packet.risk_level, 64),
                _clean_text(work_packet.stop_condition, MAX_TEXT_CHARS),
                task_text,
                draft_text,
                _clean_text(getattr(draft, "safety_notes", ""), MAX_NOTE_CHARS),
                _clean_text(getattr(draft, "verification_notes", ""), MAX_NOTE_CHARS),
            )
        ),
        MAX_TEXT_CHARS,
    )
    return {
        "work_packet": work_packet,
        "draft": draft,
        "tasks": tasks,
        "context_text": context_text,
        "task_count": len(tasks),
    }


def _check(key, label, passed, detail, required=True):
    return {
        "key": key,
        "label": label,
        "passed": bool(passed),
        "required": bool(required),
        "detail": _clean_text(detail, 600),
    }


def evaluate_readiness_checklist(db, work_packet):
    context = collect_work_packet_readiness_context(db, work_packet)
    text = context["context_text"]
    draft = context["draft"]
    draft_body = _clean_text(getattr(draft, "draft_body", ""), MAX_TEXT_CHARS)
    stop_condition = _clean_text(getattr(work_packet, "stop_condition", ""), MAX_TEXT_CHARS)
    notes_text = "\n".join(
        (
            _clean_text(getattr(work_packet, "readiness_notes", ""), MAX_NOTE_CHARS),
            _clean_text(getattr(draft, "safety_notes", ""), MAX_NOTE_CHARS),
            _clean_text(getattr(draft, "verification_notes", ""), MAX_NOTE_CHARS),
        )
    )
    all_text = "\n".join((text, notes_text))
    secret_free = redact_git_output(all_text) == all_text
    checklist = [
        _check("clear_title", "Clear title", len(_clean_text(work_packet.title)) >= 8, "Packet title is present and specific."),
        _check(
            "clear_goal",
            "Clear goal or summary",
            _contains_any(all_text, ("goal", "summary", "mission", "intent", "conversion goal")),
            "Goal can come from a reviewed draft, task description, or packet stop condition.",
        ),
        _check(
            "safety_rules",
            "Safety rules present",
            _contains_any(all_text, ("safety rules", "safety:", "do not execute", "no auto-pilot", "no autopilot")),
            "Safety boundaries should be visible before trust review.",
        ),
        _check(
            "files_allowed",
            "Files allowed or scope boundary",
            _contains_any(all_text, ("files allowed", "files:", "scope", "scoped", "only files")),
            "Packet should identify allowed files or a narrow scope boundary.",
        ),
        _check(
            "verification",
            "Verification commands or notes",
            _contains_any(all_text, ("verification", "preflight", "py_compile", "node --check", "verifier")),
            "Verification notes should be explicit.",
        ),
        _check(
            "report_path",
            "Report path or reporting expectation",
            "/tmp/" in all_text or _contains_any(all_text, ("report path", "write final report", "packet report")),
            "Packet should name or require a report path.",
        ),
        _check(
            "no_autopilot",
            "Auto-Pilot remains out of scope unless explicitly scoped",
            _contains_any(all_text, ("no auto-pilot", "no autopilot", "auto-pilot remains locked", "do not start auto-pilot")),
            "Packet should preserve the Auto-Pilot lock unless explicitly scoped.",
        ),
        _check(
            "no_execution_routes",
            "Unsafe execution routes are not authorized",
            not _contains_any(all_text, ("/api/tasks/auto-run", "/api/tasks/run-one", "/api/work-packets/run", "/api/execute-codex"))
            or _contains_any(all_text, ("do not call /api/tasks/auto-run", "do not call /api/work-packets/run", "unless explicitly tests it with mocks")),
            "Packet should not authorize execution routes without explicit scope.",
        ),
        _check(
            "no_destructive_db",
            "No destructive database operations",
            not _contains_any(all_text, ("drop table", "truncate", "delete from", "destructive database"))
            or _contains_any(all_text, ("no destructive database", "no destructive db")),
            "Packet should avoid destructive DB operations unless explicitly approved.",
        ),
        _check("no_secret_exposure", "No raw secret exposure", secret_free, "Readiness output is redacted before return."),
        _check(
            "no_shell_true",
            "No {}".format(NO_SHELL_TRUE),
            NO_SHELL_TRUE not in all_text or "No {}".format(NO_SHELL_TRUE) in all_text,
            "Packet should prohibit unsafe shell execution.",
        ),
        _check(
            "no_popen",
            "No {}".format(NO_POPEN),
            NO_POPEN not in all_text or "No {}".format(NO_POPEN) in all_text,
            "Packet should prohibit unmanaged subprocess usage.",
        ),
        _check(
            "no_native_alert_confirm",
            "No native alert/confirm for UI packets",
            not _contains_any(all_text, ("alert(", "confirm(")) or _contains_any(all_text, ("no native browser alert", "no native browser confirm")),
            "UI packets should use the async modal pattern.",
        ),
        _check(
            "trust_visible",
            "Trust status visible, not automatic",
            _clean_text(getattr(work_packet, "trust_status", "")) in {"unreviewed", "trusted", "revoked"},
            "Trust status is visible but readiness does not modify trust.",
            required=False,
        ),
        _check(
            "branch_recommendation",
            "Packet branch recommendation visible",
            _contains_any(all_text, ("factory/packet-", "branch per packet", "packet branch")),
            "Branch Per Packet remains a supervised preparation helper.",
            required=False,
        ),
    ]
    required_items = [item for item in checklist if item["required"]]
    passed_required = [item for item in required_items if item["passed"]]
    score = int(round((len(passed_required) / max(1, len(required_items))) * 100))
    missing = [item["label"] for item in required_items if not item["passed"]]
    if missing:
        status = "blocked" if score < 60 else "incomplete"
    elif _clean_text(getattr(work_packet, "trust_status", "")) == "trusted":
        status = "ready_for_trust"
    else:
        status = "ready_for_review"
    return {
        "status": status,
        "score": score,
        "missing_items": missing,
        "checklist": checklist,
        "summary": _clean_text(
            "{} readiness: {}% with {} missing required item(s).".format(
                status,
                score,
                len(missing),
            ),
            600,
        ),
        "context": {
            "task_count": context["task_count"],
            "draft_id": getattr(draft, "id", None),
            "has_prompt_draft": draft is not None,
        },
    }


def serialize_readiness(work_packet, evaluation=None):
    evaluation = evaluation or {}
    missing_items = getattr(work_packet, "readiness_missing_items", None)
    try:
        stored_missing = json.loads(missing_items) if missing_items else []
    except (TypeError, ValueError):
        stored_missing = []
    return {
        "work_packet_id": getattr(work_packet, "id", None),
        "readiness_status": _normalize_status(getattr(work_packet, "readiness_status", None)),
        "readiness_checked_at": work_packet.readiness_checked_at.isoformat() if getattr(work_packet, "readiness_checked_at", None) else None,
        "readiness_checked_by": getattr(work_packet, "readiness_checked_by", None),
        "readiness_notes": getattr(work_packet, "readiness_notes", None),
        "readiness_score": getattr(work_packet, "readiness_score", None),
        "readiness_missing_items": stored_missing,
        "trust": serialize_trust_metadata(work_packet),
        "evaluation": evaluation,
    }


def evaluate_and_store_readiness(db, work_packet, data):
    _require_confirm(data, "confirm_evaluate")
    evaluation = evaluate_readiness_checklist(db, work_packet)
    work_packet.readiness_status = evaluation["status"]
    work_packet.readiness_score = evaluation["score"]
    work_packet.readiness_missing_items = json.dumps(evaluation["missing_items"], ensure_ascii=True, sort_keys=True)
    work_packet.readiness_checked_at = datetime.now(timezone.utc)
    work_packet.readiness_checked_by = _optional_text(data.get("readiness_checked_by") or data.get("operator"), 128)
    if "readiness_notes" in data:
        work_packet.readiness_notes = _optional_text(data.get("readiness_notes"), MAX_NOTE_CHARS)
    db.commit()
    db.refresh(work_packet)
    return serialize_readiness(work_packet, evaluation=evaluation)


def update_readiness_metadata(db, work_packet, data):
    _require_confirm(data, "confirm_update")
    if "readiness_status" in data:
        work_packet.readiness_status = _normalize_status(data.get("readiness_status"))
    if "readiness_notes" in data:
        work_packet.readiness_notes = _optional_text(data.get("readiness_notes"), MAX_NOTE_CHARS)
    if "readiness_checked_by" in data:
        work_packet.readiness_checked_by = _optional_text(data.get("readiness_checked_by"), 128)
    work_packet.readiness_checked_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(work_packet)
    return serialize_readiness(work_packet)
