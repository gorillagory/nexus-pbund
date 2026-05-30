import hmac
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from hashlib import sha256

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

FAILURES = []


def check(condition, message):
    if condition:
        print("PASS: {}".format(message))
        return
    print("FAIL: {}".format(message))
    FAILURES.append(message)


def read_file(relative_path):
    with open(os.path.join(PROJECT_ROOT, relative_path), "r", encoding="utf-8") as handle:
        return handle.read()


def verify_static_sources():
    service = read_file("src/services/discord_router.py")
    dashboard = read_file("dashboard.py")
    engine = read_file("engine.py")
    models = read_file("models.py")
    sync = read_file("scripts/sync_factory_schema.py")
    app = read_file("static/js/app.js")
    settings = read_file("static/js/settings.js")
    template = read_file("templates/index.html")
    env_example = read_file(".env.example")

    for phrase in (
        "discord_allowed_guild_ids",
        "discord_allowed_channel_ids",
        "discord_allowed_author_ids",
        "discord_timestamp_tolerance_seconds",
        "discord_replay_guard_enabled",
        "discord_signature_required",
    ):
        check(phrase in service + engine + settings + template + env_example, "Discord hardening setting exists: {}".format(phrase))

    check("class DiscordCaptureEvent" in models, "DiscordCaptureEvent model exists")
    check('"discord_capture_events"' in sync, "schema sync includes discord_capture_events")
    for field in ("event_id", "guild_id", "channel_id", "author_id", "accepted", "rejection_reason", "inbox_item_id"):
        check(field in models and field in sync, "capture audit field exists: {}".format(field))

    for phrase in (
        "validate_discord_capture",
        "verify_ingest_signature",
        "event_identity",
        "create_discord_capture_event",
        "timestamp_tolerance_configured",
        "replay_guard_configured",
        "guild_allowlist_count",
        "channel_allowlist_count",
        "author_allowlist_count",
        "MAX_BODY_CHARS",
        "MAX_METADATA_CHARS",
    ):
        check(phrase in service, "Discord service contains {}".format(phrase))

    for phrase in (
        "validate_discord_capture",
        "create_discord_capture_event",
        "discord_capture_rejected",
        "discord_capture_accepted",
        "create_inbox_item",
    ):
        check(phrase in dashboard, "Discord ingest route uses {}".format(phrase))

    check("public.pop(\"discord_ingest_secret\"" in engine, "public settings remove Discord secret")
    check("public.pop(\"discord_allowed_guild_ids\"" in engine, "public settings remove guild allowlist values")
    check("public.pop(\"discord_allowed_channel_ids\"" in engine, "public settings remove channel allowlist values")
    check("public.pop(\"discord_allowed_author_ids\"" in engine, "public settings remove author allowlist values")

    for phrase in (
        "/api/tasks/auto-run",
        "/api/tasks/run-one",
        "/api/work-packets/run",
        "/api/execute-codex",
        "_execute_factory_task",
        "CodexRunner",
        "retry_factory_run",
        "continue_factory_run",
        "mark_packet_trusted",
        "revoke_packet_trust",
        "prepare_packet_branch",
        "set_execution_mode",
    ):
        check(phrase not in service, "Discord service does not call {}".format(phrase))

    for phrase in (
        "git add",
        "git commit",
        "git merge",
        "git push",
        "git reset",
        "git clean",
        "git rebase",
        "git stash",
        "git tag",
        "git switch",
        "git checkout",
    ):
        check(phrase not in service, "Discord service does not expose {}".format(phrase))

    check("shell=True" not in service + dashboard, "Discord hardening avoids shell=True")
    check("subprocess.Popen" not in service + dashboard and "Popen(" not in service + dashboard, "Discord hardening avoids subprocess.Popen")
    check(re.search(r"\balert\s*\(", app + settings + template) is None, "no native alert() in frontend")
    check(re.search(r"\bconfirm\s*\(", app + settings + template) is None, "no native confirm() in frontend")
    check("Signature Required" in app and "Guild Allowlist" in app and "Replay Guard" in app, "dashboard shows redacted hardening status")


def verify_service_behavior():
    from models import Base, DiscordCaptureEvent, OrchestrationInboxItem, Workspace
    from src.services.discord_router import (
        create_discord_capture_event,
        discord_router_status,
        normalize_discord_event,
        validate_discord_capture,
    )
    from src.services.orchestration_inbox import create_inbox_item

    db_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=db_engine)
    Session = sessionmaker(bind=db_engine)
    db = Session()
    workspace = Workspace(name="Packet 035 Test", local_path=PROJECT_ROOT)
    db.add(workspace)
    db.commit()
    db.refresh(workspace)

    settings = {
        "discord_router_enabled": True,
        "discord_ingest_secret": "shared-secret",
        "discord_signature_required": True,
        "discord_allowed_guild_ids": "guild-1",
        "discord_allowed_channel_ids": "channel-1",
        "discord_allowed_author_ids": "author-1",
        "discord_timestamp_tolerance_seconds": 300,
        "discord_replay_guard_enabled": True,
    }
    payload = {
        "id": "event-1",
        "guild_id": "guild-1",
        "channel_id": "channel-1",
        "author_id": "author-1",
        "content": "Capture this safely token=super-secret",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    raw = b'{"id":"event-1"}'
    signature = hmac.new(settings["discord_ingest_secret"].encode("utf-8"), raw, sha256).hexdigest()
    headers = {
        "X-Nexus-Discord-Secret": "shared-secret",
        "X-Nexus-Discord-Signature": "sha256={}".format(signature),
    }

    status = discord_router_status(settings)
    check(status["secret_configured"] is True, "status reports secret configured")
    check("shared-secret" not in str(status), "status redacts raw secret")
    check(status["guild_allowlist_configured"] is True and status["guild_allowlist_count"] == 1, "status reports guild allowlist count only")
    check("guild-1" not in str(status), "status hides allowlist values")

    identity = validate_discord_capture(settings, headers, payload, db=db, workspace_id=workspace.id, raw_body=raw)
    inbox_data = normalize_discord_event(payload)
    item = create_inbox_item(db, workspace.id, inbox_data)
    create_discord_capture_event(db, workspace.id, identity, accepted=True, inbox_item_id=item.id)
    check(item.source == "discord", "accepted payload creates source=discord inbox item")
    check("super-secret" not in item.raw_intent and "super-secret" not in (item.triage_notes or ""), "accepted payload is redacted before storage")
    check(len(item.raw_intent) <= 6000, "accepted payload body is bounded")

    duplicate_count_before = db.execute(select(OrchestrationInboxItem)).scalars().all()
    try:
        validate_discord_capture(settings, headers, payload, db=db, workspace_id=workspace.id, raw_body=raw)
    except ValueError as exception:
        create_discord_capture_event(db, workspace.id, identity, accepted=False, rejection_reason=str(exception))
        check("already captured" in str(exception), "replay guard rejects duplicate event")
    else:
        check(False, "replay guard rejects duplicate event")
    duplicate_count_after = db.execute(select(OrchestrationInboxItem)).scalars().all()
    check(len(duplicate_count_after) == len(duplicate_count_before), "rejected replay does not create inbox item")

    bad_headers = {"X-Nexus-Discord-Secret": "wrong"}
    try:
        validate_discord_capture(settings, bad_headers, dict(payload, id="event-2"), db=db, workspace_id=workspace.id, raw_body=raw)
    except ValueError as exception:
        check("authentication failed" in str(exception), "invalid shared secret is rejected")
    else:
        check(False, "invalid shared secret is rejected")

    wrong_channel = dict(payload, id="event-3", channel_id="channel-2")
    wrong_raw = b'{"id":"event-3"}'
    wrong_sig = hmac.new(settings["discord_ingest_secret"].encode("utf-8"), wrong_raw, sha256).hexdigest()
    try:
        validate_discord_capture(
            settings,
            {"X-Nexus-Discord-Secret": "shared-secret", "X-Nexus-Discord-Signature": wrong_sig},
            wrong_channel,
            db=db,
            workspace_id=workspace.id,
            raw_body=wrong_raw,
        )
    except ValueError as exception:
        check("channel" in str(exception), "channel allowlist rejects non-allowed channel")
    else:
        check(False, "channel allowlist rejects non-allowed channel")

    stale_payload = dict(payload, id="event-4", timestamp=(datetime.now(timezone.utc) - timedelta(hours=2)).isoformat())
    stale_raw = b'{"id":"event-4"}'
    stale_sig = hmac.new(settings["discord_ingest_secret"].encode("utf-8"), stale_raw, sha256).hexdigest()
    try:
        validate_discord_capture(
            settings,
            {"X-Nexus-Discord-Secret": "shared-secret", "X-Nexus-Discord-Signature": stale_sig},
            stale_payload,
            db=db,
            workspace_id=workspace.id,
            raw_body=stale_raw,
        )
    except ValueError as exception:
        check("outside tolerance" in str(exception), "stale payload is rejected")
    else:
        check(False, "stale payload is rejected")

    audit_events = db.execute(select(DiscordCaptureEvent)).scalars().all()
    check(any(event.accepted == 1 for event in audit_events), "accepted capture audit is recorded")
    check(any(event.accepted == 0 for event in audit_events), "rejected capture audit is recorded")


def verify_docs():
    combined = "\n".join(
        read_file(path)
        for path in (
            "docs/SPRINT_PLAN.md",
            "docs/SPRINT_3_PLAN.md",
            "docs/WORKFLOW_LOCK.md",
            "docs/CHAT_HANDOFF.md",
            "docs/PROMPTING_GUIDE.md",
        )
    )
    for phrase in (
        "Discord Capture Hardening",
        "Discord remains capture-only",
        "Discord cannot execute Codex",
        "Rejected payloads",
        "Auto-Pilot",
        "nexus-discord-capture-hardening-baseline-2026-05-30",
        "Packet 036 — Deployment And Operator Runbooks",
    ):
        check(phrase in combined, "docs preserve Discord capture boundary: {}".format(phrase))


def main():
    verify_static_sources()
    verify_service_behavior()
    verify_docs()
    if FAILURES:
        print("FAIL: Packet 035 verification failed")
        return 1
    print("PASS: Packet 035 verification complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
