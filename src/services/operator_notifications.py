import json
import os
from datetime import datetime, timedelta, timezone
from urllib import error, request

from sqlalchemy import select

from models import OperatorNotification
from src.services.git_explorer import redact_git_output


NOTIFICATION_CHANNEL = "discord"
SEVERITY_ORDER = {"info": 0, "warning": 1, "blocked": 2, "critical": 3}
DELIVERY_STATUSES = {"sent", "failed", "skipped"}
MAX_TITLE_CHARS = 160
MAX_SUMMARY_CHARS = 1200
MAX_FAILURE_CHARS = 500
MAX_RECENT_LIMIT = 50
DISCORD_CONTENT_LIMIT = 1800


def _clean_text(value, max_length=None):
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    value = redact_git_output(value).strip()
    if max_length is not None:
        value = value[:max_length]
    return value


def _coerce_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _coerce_int(value, default=0, minimum=0, maximum=3600):
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(number, maximum))


def _normalize_severity(value):
    severity = _clean_text(value, 32).lower()
    return severity if severity in SEVERITY_ORDER else "info"


def _normalize_status(value):
    status = _clean_text(value, 32).lower()
    return status if status in DELIVERY_STATUSES else "failed"


def _webhook_url(settings):
    return _clean_text(
        settings.get("operator_notify_discord_webhook_url")
        or os.getenv("NEXUS_OPERATOR_NOTIFY_DISCORD_WEBHOOK_URL")
    )


def _dashboard_url(settings):
    return _clean_text(
        settings.get("operator_dashboard_url")
        or os.getenv("NEXUS_OPERATOR_DASHBOARD_URL"),
        500,
    )


def notification_status(settings):
    min_severity = _normalize_severity(settings.get("operator_notify_min_severity") or "info")
    cooldown = _coerce_int(settings.get("operator_notify_cooldown_seconds"), default=30)
    dashboard_url = _dashboard_url(settings)
    return {
        "enabled": _coerce_bool(settings.get("operator_notify_discord_enabled")),
        "channel": NOTIFICATION_CHANNEL,
        "webhook_configured": bool(_webhook_url(settings)),
        "dashboard_url_configured": bool(dashboard_url),
        "min_severity": min_severity,
        "cooldown_seconds": cooldown,
        "mode": "notification_only",
        "severities": sorted(SEVERITY_ORDER, key=SEVERITY_ORDER.get),
    }


def redact_and_bound_message(value, limit=MAX_SUMMARY_CHARS):
    text = _clean_text(value)
    if len(text) <= limit:
        return text
    return "{}\n[message truncated to {} characters]".format(text[:limit], limit)


def build_notification_payload(settings, event_type, severity, title, summary, dashboard_path=None):
    severity = _normalize_severity(severity)
    title = _clean_text(title, MAX_TITLE_CHARS) or "Nexus operator notification"
    summary = redact_and_bound_message(summary, MAX_SUMMARY_CHARS) or "Nexus needs operator attention."
    dashboard_url = _dashboard_url(settings)
    link = ""
    if dashboard_url:
        link = dashboard_url.rstrip("/")
        if dashboard_path:
            link = "{}{}".format(link, "/" + str(dashboard_path).lstrip("/"))
    lines = [
        "**Nexus {}**".format(severity.upper()),
        "**{}**".format(title),
        summary,
        "Event: `{}`".format(_clean_text(event_type, 64) or "operator_notification"),
        "Mode: notification-only. No Discord execution is available.",
    ]
    if link:
        lines.append("Dashboard: {}".format(redact_and_bound_message(link, 500)))
    content = redact_and_bound_message("\n".join(lines), DISCORD_CONTENT_LIMIT)
    return {
        "content": content,
        "event_type": _clean_text(event_type, 64) or "operator_notification",
        "severity": severity,
        "title": title,
        "summary": summary,
    }


def should_send_notification(db, workspace_id, settings, event_type, severity, dedupe_key=None):
    status = notification_status(settings)
    if not status["enabled"]:
        return False, "notifications disabled"
    if not status["webhook_configured"]:
        return False, "discord webhook not configured"

    severity = _normalize_severity(severity)
    if SEVERITY_ORDER[severity] < SEVERITY_ORDER[status["min_severity"]]:
        return False, "severity below notification threshold"

    key = _clean_text(dedupe_key, 255)
    if key and status["cooldown_seconds"] > 0 and db is not None and workspace_id is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=status["cooldown_seconds"])
        recent = (
            db.execute(
                select(OperatorNotification)
                .where(
                    OperatorNotification.workspace_id == workspace_id,
                    OperatorNotification.channel == NOTIFICATION_CHANNEL,
                    OperatorNotification.dedupe_key == key,
                    OperatorNotification.created_at >= cutoff,
                    OperatorNotification.delivery_status.in_(("sent", "failed")),
                )
                .limit(1)
            )
            .scalars()
            .first()
        )
        if recent is not None:
            return False, "notification cooldown active"
    return True, "ready"


def record_notification_result(
    db,
    workspace_id,
    event_type,
    severity,
    title,
    summary,
    delivery_status,
    failure_reason=None,
    dedupe_key=None,
    commit=True,
):
    notification = OperatorNotification(
        workspace_id=workspace_id,
        channel=NOTIFICATION_CHANNEL,
        event_type=_clean_text(event_type, 64) or "operator_notification",
        severity=_normalize_severity(severity),
        title=_clean_text(title, MAX_TITLE_CHARS) or "Nexus operator notification",
        summary=redact_and_bound_message(summary, MAX_SUMMARY_CHARS),
        delivery_status=_normalize_status(delivery_status),
        failure_reason=_clean_text(failure_reason, MAX_FAILURE_CHARS) or None,
        dedupe_key=_clean_text(dedupe_key, 255) or None,
        delivered_at=datetime.now(timezone.utc) if delivery_status == "sent" else None,
    )
    db.add(notification)
    if commit:
        db.commit()
        db.refresh(notification)
    return notification


def serialize_notification(notification):
    if notification is None:
        return {}
    return {
        "id": getattr(notification, "id", None),
        "workspace_id": getattr(notification, "workspace_id", None),
        "channel": getattr(notification, "channel", None),
        "event_type": getattr(notification, "event_type", None),
        "severity": getattr(notification, "severity", None),
        "title": getattr(notification, "title", None),
        "summary": getattr(notification, "summary", None),
        "delivery_status": getattr(notification, "delivery_status", None),
        "failure_reason": getattr(notification, "failure_reason", None),
        "dedupe_key": getattr(notification, "dedupe_key", None),
        "created_at": notification.created_at.isoformat() if getattr(notification, "created_at", None) else None,
        "delivered_at": notification.delivered_at.isoformat() if getattr(notification, "delivered_at", None) else None,
    }


def list_recent_notifications(db, workspace_id, limit=20):
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(limit, MAX_RECENT_LIMIT))
    statement = (
        select(OperatorNotification)
        .where(OperatorNotification.workspace_id == workspace_id)
        .order_by(OperatorNotification.created_at.desc(), OperatorNotification.id.desc())
        .limit(limit)
    )
    return db.execute(statement).scalars().all()


def _post_discord_webhook(webhook_url, payload):
    body = json.dumps({"content": payload["content"]}, ensure_ascii=True).encode("utf-8")
    webhook_request = request.Request(
        webhook_url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "nexus-operator-notifications"},
        method="POST",
    )
    with request.urlopen(webhook_request, timeout=5) as response:
        return getattr(response, "status", 204)


def send_discord_notification(
    db,
    workspace_id,
    settings,
    event_type,
    severity,
    title,
    summary,
    dedupe_key=None,
    dashboard_path=None,
    record_skipped=False,
):
    payload = build_notification_payload(
        settings,
        event_type=event_type,
        severity=severity,
        title=title,
        summary=summary,
        dashboard_path=dashboard_path,
    )
    should_send, reason = should_send_notification(
        db,
        workspace_id,
        settings,
        event_type=payload["event_type"],
        severity=payload["severity"],
        dedupe_key=dedupe_key,
    )
    if not should_send:
        notification = None
        if record_skipped:
            notification = record_notification_result(
                db,
                workspace_id,
                payload["event_type"],
                payload["severity"],
                payload["title"],
                payload["summary"],
                "skipped",
                failure_reason=reason,
                dedupe_key=dedupe_key,
            )
        return {
            "status": "skipped",
            "message": reason,
            "notification": notification,
            "payload": payload,
        }

    try:
        status_code = _post_discord_webhook(_webhook_url(settings), payload)
        if status_code < 200 or status_code >= 300:
            raise ValueError("Discord webhook returned HTTP {}".format(status_code))
        notification = record_notification_result(
            db,
            workspace_id,
            payload["event_type"],
            payload["severity"],
            payload["title"],
            payload["summary"],
            "sent",
            dedupe_key=dedupe_key,
        )
        return {
            "status": "sent",
            "message": "notification sent",
            "notification": notification,
            "payload": payload,
        }
    except (OSError, ValueError, error.URLError, error.HTTPError):
        notification = record_notification_result(
            db,
            workspace_id,
            payload["event_type"],
            payload["severity"],
            payload["title"],
            payload["summary"],
            "failed",
            failure_reason="Discord notification delivery failed.",
            dedupe_key=dedupe_key,
        )
        return {
            "status": "failed",
            "message": "Discord notification delivery failed.",
            "notification": notification,
            "payload": payload,
        }


def send_test_notification(db, workspace_id, settings, confirm_send=False):
    if confirm_send is not True:
        raise ValueError("confirm_send=true is required.")
    return send_discord_notification(
        db,
        workspace_id,
        settings,
        event_type="notification_test",
        severity="info",
        title="Nexus mobile alert test",
        summary="This is a notification-only test. It does not execute Codex, tasks, packets, Git actions, trust changes, recovery, or Auto-Pilot.",
        dedupe_key="notification_test",
        dashboard_path="",
        record_skipped=True,
    )
