import json
import re
from datetime import datetime, timezone

from sqlalchemy import select

from models import (
    ExecutionChangedFile,
    ExecutionRun,
    OrchestrationInboxItem,
    PacketPromptDraft,
    Task,
    WorkPacket,
    WorkPacketTask,
)
from src.services.git_explorer import redact_git_output
from src.services.orchestration_inbox import create_inbox_item, serialize_inbox_item
from src.services.packet_drafting import (
    build_structured_packet_prompt,
    serialize_packet_prompt_draft,
    update_packet_prompt_draft,
    validate_required_sections,
)
from src.services.trusted_packets import packet_trust_eligible, serialize_trust_metadata
from src.services.work_packet_readiness import evaluate_and_store_readiness, serialize_readiness


SIMPLE_SOURCE = "simple_operator"
MAX_REQUEST_CHARS = 6000
MAX_DRAFT_CHARS = 24000
MAX_SNIPPET_CHARS = 1800
MAX_CHANGED_FILES = 20
FLOW_STATUSES = {"captured", "drafted", "ready", "running", "passed", "failed", "blocked", "cancelled"}


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


def _require_confirm(data, field_name):
    if data.get(field_name) is not True:
        raise ValueError("{}=true is required.".format(field_name))


def _safe_int(value):
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _first_line(value, fallback="Simple Operator Request"):
    text = _clean_text(value, 255)
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:255]
    return fallback


def _json_for_codex_prompt(prompt):
    text = _clean_text(prompt, MAX_DRAFT_CHARS)
    encoded = json.dumps(text, ensure_ascii=True)
    return (
        "Execute this reviewed Nexus operator packet prompt. "
        "The prompt is JSON-encoded; interpret escaped newlines as line breaks before acting: {}".format(encoded)
    )


def _codex_command(prompt):
    command_prompt = _json_for_codex_prompt(prompt)
    return "codex {}".format(json.dumps(command_prompt, ensure_ascii=True))


def _extract_report_path(draft):
    text = _clean_text(getattr(draft, "draft_body", ""), MAX_DRAFT_CHARS)
    if not text:
        return ""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if "report" not in line.lower():
            continue
        for candidate in lines[index : index + 4]:
            stripped = candidate.strip().strip("`")
            if stripped.startswith("/tmp/"):
                return _clean_text(stripped, 500)
    for token in re.findall(r"/tmp/[A-Za-z0-9._/:-]+", text):
        return _clean_text(token, 500)
    return ""


def _latest_draft(db, workspace_id, flow_id):
    return (
        db.execute(
            select(PacketPromptDraft)
            .where(PacketPromptDraft.workspace_id == workspace_id)
            .where(PacketPromptDraft.inbox_item_id == flow_id)
            .order_by(PacketPromptDraft.updated_at.desc(), PacketPromptDraft.created_at.desc(), PacketPromptDraft.id.desc())
        )
        .scalars()
        .first()
    )


def _work_packet_from_flow(db, workspace_id, flow_id, draft=None):
    draft = draft or _latest_draft(db, workspace_id, flow_id)
    if draft is not None and draft.work_packet_id:
        packet = db.get(WorkPacket, draft.work_packet_id)
        if packet is not None and packet.workspace_id == workspace_id:
            return packet
    return None


def _packet_tasks(db, work_packet):
    if work_packet is None:
        return []
    links = (
        db.execute(
            select(WorkPacketTask)
            .where(WorkPacketTask.work_packet_id == work_packet.id)
            .order_by(WorkPacketTask.position.asc(), WorkPacketTask.id.asc())
        )
        .scalars()
        .all()
    )
    tasks = []
    for link in links:
        task = db.get(Task, link.task_id)
        if task is not None and task.workspace_id == work_packet.workspace_id:
            tasks.append((link, task))
    return tasks


def _latest_runs(db, workspace_id, work_packet=None, task=None, limit=5):
    statement = select(ExecutionRun).where(ExecutionRun.workspace_id == workspace_id)
    if work_packet is not None:
        statement = statement.where(ExecutionRun.work_packet_id == work_packet.id)
    elif task is not None:
        statement = statement.where(ExecutionRun.task_id == task.id)
    else:
        return []
    return (
        db.execute(statement.order_by(ExecutionRun.started_at.desc(), ExecutionRun.id.desc()))
        .scalars()
        .all()
    )[:limit]


def _changed_files_for_runs(db, runs):
    run_ids = [run.id for run in runs if getattr(run, "id", None)]
    if not run_ids:
        return []
    files = (
        db.execute(
            select(ExecutionChangedFile)
            .where(ExecutionChangedFile.execution_run_id.in_(run_ids))
            .order_by(ExecutionChangedFile.id.asc())
        )
        .scalars()
        .all()
    )[:MAX_CHANGED_FILES]
    return [
        {
            "execution_run_id": item.execution_run_id,
            "file_path": _clean_text(item.file_path, 500),
            "change_type": _clean_text(item.change_type, 64),
        }
        for item in files
    ]


def _serialize_task(task, link=None):
    if task is None:
        return {}
    payload = {
        "id": task.id,
        "workspace_id": task.workspace_id,
        "title": task.title,
        "status": task.status,
        "created_at": task.created_at.isoformat() if getattr(task, "created_at", None) else None,
    }
    if link is not None:
        payload["packet_task_status"] = link.status
        payload["packet_task_position"] = link.position
    return payload


def serialize_simple_run(run):
    if run is None:
        return {}
    stdout = _clean_text(getattr(run, "stdout", ""), MAX_SNIPPET_CHARS)
    stderr = _clean_text(getattr(run, "stderr", "") or getattr(run, "error_message", ""), MAX_SNIPPET_CHARS)
    verification = "pass" if getattr(run, "status", None) == "success" and getattr(run, "returncode", None) == 0 else "fail"
    if getattr(run, "status", None) in {"running", "created"}:
        verification = "pending"
    return {
        "id": run.id,
        "workspace_id": run.workspace_id,
        "work_packet_id": run.work_packet_id,
        "task_id": run.task_id,
        "status": run.status,
        "returncode": run.returncode,
        "started_at": run.started_at.isoformat() if getattr(run, "started_at", None) else None,
        "finished_at": run.finished_at.isoformat() if getattr(run, "finished_at", None) else None,
        "duration_seconds": run.duration_seconds,
        "stdout_snippet": stdout,
        "stderr_snippet": stderr,
        "verification_result": verification,
    }


def _flow_status(item, draft, work_packet, runs, trust_gate=None):
    if runs:
        latest = runs[0]
        status = _clean_text(getattr(latest, "status", ""), 32)
        if status in {"created", "running"}:
            return "running"
        if status == "success" and getattr(latest, "returncode", None) == 0:
            return "passed"
        return "failed"
    if trust_gate is not None and not trust_gate.get("eligible"):
        return "blocked"
    if work_packet is not None:
        return "ready"
    if draft is not None:
        return "drafted"
    return "captured"


def _next_action(status, draft=None, work_packet=None, trust_gate=None):
    if status == "captured":
        return "Generate a structured draft from the request."
    if status == "drafted":
        return "Review or edit the draft, then prepare one work packet."
    if status == "ready":
        if trust_gate is not None and not trust_gate.get("eligible"):
            return "Trusted Packet Mode is blocking this packet. Review and trust it explicitly before running."
        return "Approve and run the selected work packet when ready."
    if status == "running":
        return "Track the active run; do not start another run."
    if status == "passed":
        return "Review changed files and verification output, then continue the normal packet workflow."
    if status == "failed":
        return "Inspect stdout, stderr, changed files, and add an operator review note before retrying manually."
    if status == "blocked":
        return "Resolve the blocking condition before approval."
    return "Capture a new request."


def serialize_simple_flow(db, workspace_id, item, settings=None):
    if item is None:
        return {}
    draft = _latest_draft(db, workspace_id, item.id)
    work_packet = _work_packet_from_flow(db, workspace_id, item.id, draft=draft)
    packet_tasks = _packet_tasks(db, work_packet)
    primary_task = packet_tasks[0][1] if packet_tasks else None
    runs = _latest_runs(db, workspace_id, work_packet=work_packet, task=primary_task)
    trust_gate = None
    if work_packet is not None:
        trust_gate = packet_trust_eligible(
            work_packet,
            trusted_packet_mode_enabled=bool((settings or {}).get("trusted_packet_mode_enabled")),
        )
    status = _flow_status(item, draft, work_packet, runs, trust_gate=trust_gate)
    return {
        "id": item.id,
        "workspace_id": workspace_id,
        "status": status,
        "request": serialize_inbox_item(item),
        "draft": serialize_packet_prompt_draft(draft) if draft is not None else None,
        "work_packet": serialize_work_packet(work_packet) if work_packet is not None else None,
        "tasks": [_serialize_task(task, link=link) for link, task in packet_tasks],
        "readiness": serialize_readiness(work_packet) if work_packet is not None else None,
        "trust_gate": trust_gate,
        "runs": [serialize_simple_run(run) for run in runs],
        "changed_files": _changed_files_for_runs(db, runs),
        "report_path": _extract_report_path(draft),
        "next_action": _next_action(status, draft=draft, work_packet=work_packet, trust_gate=trust_gate),
    }


def serialize_work_packet(work_packet):
    if work_packet is None:
        return {}
    return {
        "id": work_packet.id,
        "workspace_id": work_packet.workspace_id,
        "title": work_packet.title,
        "risk_level": work_packet.risk_level,
        "stop_condition": _clean_text(work_packet.stop_condition, 2000),
        "estimated_minutes": work_packet.estimated_minutes,
        "status": work_packet.status,
        "readiness_status": work_packet.readiness_status,
        "readiness_score": work_packet.readiness_score,
        "created_at": work_packet.created_at.isoformat() if getattr(work_packet, "created_at", None) else None,
        "started_at": work_packet.started_at.isoformat() if getattr(work_packet, "started_at", None) else None,
        "completed_at": work_packet.completed_at.isoformat() if getattr(work_packet, "completed_at", None) else None,
        "failed_at": work_packet.failed_at.isoformat() if getattr(work_packet, "failed_at", None) else None,
        "trust": serialize_trust_metadata(work_packet),
    }


def list_simple_flows(db, workspace_id, limit=20, settings=None):
    items = (
        db.execute(
            select(OrchestrationInboxItem)
            .where(OrchestrationInboxItem.workspace_id == workspace_id)
            .where(OrchestrationInboxItem.source == SIMPLE_SOURCE)
            .order_by(OrchestrationInboxItem.updated_at.desc(), OrchestrationInboxItem.created_at.desc(), OrchestrationInboxItem.id.desc())
        )
        .scalars()
        .all()
    )[:limit]
    return [serialize_simple_flow(db, workspace_id, item, settings=settings) for item in items]


def get_simple_flow_item(db, workspace_id, flow_id):
    item = db.get(OrchestrationInboxItem, flow_id)
    if item is None or item.workspace_id != workspace_id or item.source != SIMPLE_SOURCE:
        return None
    return item


def create_simple_request(db, workspace_id, data):
    _require_confirm(data, "confirm_create")
    raw_request = _clean_text(data.get("raw_request") or data.get("request") or data.get("raw_intent"), MAX_REQUEST_CHARS)
    if not raw_request:
        raise ValueError("raw_request is required.")
    title = _clean_text(data.get("title"), 255) or _first_line(raw_request)
    item = create_inbox_item(
        db,
        workspace_id,
        {
            "title": title,
            "raw_intent": raw_request,
            "source": SIMPLE_SOURCE,
            "priority": data.get("priority") or "normal",
            "category": data.get("category") or "feature",
            "triage_notes": "Captured by Simple Operator Flow. No execution has occurred.",
        },
    )
    return item


def generate_simple_draft(db, workspace_id, item, data):
    _require_confirm(data, "confirm_generate")
    raw_request = _clean_text(item.raw_intent, MAX_REQUEST_CHARS)
    title = _clean_text(data.get("title") or item.title, 255)
    draft_data = {
        "confirm_generate": True,
        "packet_title": title,
        "title": title,
        "category": data.get("category") or item.category or "feature",
        "goal": data.get("goal") or raw_request,
        "current_state": data.get("current_state")
        or "Simple Operator Flow request captured from the primary operator lane:\n{}".format(raw_request),
        "safety_notes": data.get("safety_notes")
        or (
            "- Simple Operator Flow only.\n"
            "- Execution requires confirm_run=true.\n"
            "- Auto-Pilot remains locked.\n"
            "- Discord remains capture/notification-only.\n"
            "- Trusted Packet Mode must be respected.\n"
            "- Do not mark packets trusted automatically."
        ),
        "verification_notes": data.get("verification_notes")
        or "Run the packet verifier, quick preflight, regression suite, and git diff --check.",
        "files_allowed": data.get("files_allowed") or "Use only files required after repo inspection.",
        "report_path": data.get("report_path") or "/tmp/nexus-simple-operator-flow-report.md",
        "branch_name": data.get("branch_name") or "factory/simple-operator-flow-request-{}".format(item.id),
        "source_type": "inbox_item",
        "source_id": item.id,
    }
    generated = build_structured_packet_prompt(db, workspace_id, draft_data)
    draft = PacketPromptDraft(
        workspace_id=workspace_id,
        inbox_item_id=item.id,
        source_type="inbox_item",
        source_id=str(item.id),
        title=generated["title"],
        draft_body=generated["draft_body"],
        category=generated["category"],
        safety_notes=generated["safety_notes"],
        verification_notes=generated["verification_notes"],
        status="draft",
    )
    db.add(draft)
    item.status = "triaged"
    item.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(draft)
    db.refresh(item)
    return draft, generated.get("validation") or validate_required_sections(draft.draft_body)


def update_simple_draft(db, workspace_id, item, data):
    _require_confirm(data, "confirm_generate")
    draft = _latest_draft(db, workspace_id, item.id)
    if draft is None:
        raise ValueError("Generate a draft before editing it.")
    updated = update_packet_prompt_draft(
        db,
        draft,
        {
            "confirm_save": True,
            "title": data.get("title", draft.title),
            "draft_body": data.get("draft_body", draft.draft_body),
            "category": data.get("category", draft.category),
            "safety_notes": data.get("safety_notes", draft.safety_notes),
            "verification_notes": data.get("verification_notes", draft.verification_notes),
            "status": data.get("status", draft.status),
        },
    )
    return updated, validate_required_sections(updated.draft_body)


def prepare_simple_work_packet(db, workspace_id, item, data):
    _require_confirm(data, "confirm_prepare")
    existing_draft = _latest_draft(db, workspace_id, item.id)
    if existing_draft is None:
        raise ValueError("Generate and review a draft before preparing a work packet.")
    existing_packet = _work_packet_from_flow(db, workspace_id, item.id, draft=existing_draft)
    if existing_packet is not None:
        return existing_packet

    title = _clean_text(data.get("title") or existing_draft.title or item.title, 255)
    stop_condition = _clean_text(
        data.get("stop_condition")
        or "Stop after this one Simple Operator Flow task completes or fails. Do not continue automatically.",
        4000,
    )
    work_packet = WorkPacket(
        workspace_id=workspace_id,
        title=title,
        risk_level=_clean_text(data.get("risk_level") or "medium", 64),
        stop_condition=stop_condition,
        estimated_minutes=_optional_text(data.get("estimated_minutes"), 64),
        status="staged",
        trust_status="unreviewed",
        trust_level="standard",
    )
    db.add(work_packet)
    db.flush()

    command = _codex_command(existing_draft.draft_body)
    task = Task(
        workspace_id=workspace_id,
        title=title,
        description="\n".join(
            [
                "Simple Operator Flow supervised task.",
                "Execution requires confirm_run=true from /api/simple-operator/<id>/approve-run.",
                "",
                "```bash",
                command,
                "```",
            ]
        ),
        status="todo",
    )
    db.add(task)
    db.flush()
    link = WorkPacketTask(
        work_packet_id=work_packet.id,
        task_id=task.id,
        position=1,
        status="staged",
    )
    db.add(link)
    existing_draft.work_packet_id = work_packet.id
    existing_draft.status = "reviewed"
    existing_draft.updated_at = datetime.now(timezone.utc)
    item.status = "staged"
    item.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(work_packet)
    db.refresh(task)
    db.refresh(existing_draft)
    db.refresh(item)
    return work_packet


def evaluate_simple_readiness(db, workspace_id, item, data):
    _require_confirm(data, "confirm_evaluate")
    work_packet = _work_packet_from_flow(db, workspace_id, item.id)
    if work_packet is None:
        raise ValueError("Prepare a work packet before evaluating readiness.")
    return evaluate_and_store_readiness(
        db,
        work_packet,
        {
            "confirm_evaluate": True,
            "readiness_checked_by": data.get("readiness_checked_by") or "simple_operator_flow",
            "readiness_notes": data.get("readiness_notes")
            or "Evaluated from Simple Operator Flow. Execution still requires explicit approval.",
        },
    )


def simple_run_blockers(settings, work_packet, packet_tasks):
    blockers = []
    if work_packet is None:
        blockers.append("Prepare a work packet before approving a run.")
    if work_packet is not None and len(packet_tasks) != 1:
        blockers.append("Simple Operator Flow can run only one linked task.")
    if work_packet is not None:
        trust_gate = packet_trust_eligible(
            work_packet,
            trusted_packet_mode_enabled=bool((settings or {}).get("trusted_packet_mode_enabled")),
        )
        if not trust_gate.get("eligible"):
            blockers.append("Trusted Packet Mode requires trust_status=trusted.")
    return blockers
