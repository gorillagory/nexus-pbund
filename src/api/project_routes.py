from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict

from flask import Blueprint, jsonify, request
from sqlalchemy import select

from database import get_db
from engine import NexusEngine
from src.models.execution_log import ExecutionLog


projects_blueprint = Blueprint("projects", __name__)
bp = projects_blueprint

_background_tasks = ThreadPoolExecutor(
    max_workers=2,
    thread_name_prefix="project-initializer",
)


def _serialize_execution_log(log: ExecutionLog) -> Dict[str, Any]:
    return {
        "id": str(log.id),
        "project_id": log.project_id,
        "timestamp": log.timestamp.isoformat(),
        "event_type": log.event_type,
        "status": log.status,
        "summary": log.summary,
        "details": log.details,
    }


def run_scan_and_generate_context(project_path: str) -> Dict[str, Any]:
    """Build the project's generated brain without blocking the HTTP request."""
    engine = NexusEngine(project_path)
    return asyncio.run(engine.rebuild_brain())


@projects_blueprint.route("/api/projects/<project_id>/execution-log", methods=["GET"])
def get_execution_log(project_id: str):
    db_context = get_db()
    db = next(db_context)
    try:
        logs = db.execute(
            select(ExecutionLog)
            .where(ExecutionLog.project_id == project_id)
            .order_by(ExecutionLog.timestamp.desc())
        ).scalars().all()
        return jsonify([_serialize_execution_log(log) for log in logs])
    finally:
        db_context.close()


@projects_blueprint.route("/api/projects/initialize", methods=["POST"])
def initialize_project():
    payload = request.get_json(silent=True) or {}
    project_path = payload.get("project_path")

    if not isinstance(project_path, str) or not project_path.strip():
        return jsonify({"status": "error", "message": "Project path is required."}), 400

    normalized_path = os.path.abspath(os.path.expanduser(project_path.strip()))
    project_id = os.path.basename(os.path.normpath(normalized_path))
    if not project_id:
        return jsonify({"status": "error", "message": "Invalid project path."}), 400

    db_context = get_db()
    db = next(db_context)
    try:
        log = ExecutionLog(
            project_id=project_id,
            event_type="INITIALIZE",
            status="IN_PROGRESS",
            details={"project_path": normalized_path},
        )
        db.add(log)
        db.commit()
        db.refresh(log)
    except Exception:
        db.rollback()
        raise
    finally:
        db_context.close()

    _background_tasks.submit(run_scan_and_generate_context, normalized_path)
    return jsonify(_serialize_execution_log(log)), 202
