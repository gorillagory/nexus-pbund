import hmac
import json
import re
from datetime import datetime, timezone
from hashlib import sha256

from sqlalchemy import select

from models import DiscordCaptureEvent


DISCORD_SOURCE = "discord"
MAX_TITLE_CHARS = 160
MAX_BODY_CHARS = 6000
MAX_METADATA_CHARS = 2000
MAX_REASON_CHARS = 255
SECRET_TEXT_PATTERN = re.compile(
    r"(?i)(api[_ -]?key|authorization|bearer\s+[A-Za-z0-9._~+/=-]+|"
    r"secret|token|sk-[A-Za-z0-9_-]{8,}|AIza[0-9A-Za-z_-]{20,})"
)


def _clean_text(value, max_length=None):
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    value = value.strip()
    if max_length is not None:
        value = value[:max_length]
    return value


def _redact_secret_text(value):
    return SECRET_TEXT_PATTERN.sub("[redacted]", value or "")


def _coerce_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _coerce_int(value, default=0):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _split_allowlist(value):
    if value in (None, ""):
        return set()
    if isinstance(value, (list, tuple, set)):
        candidates = value
    else:
        candidates = re.split(r"[\s,]+", str(value))
    return {
        _clean_text(candidate, 128)
        for candidate in candidates
        if _clean_text(candidate, 128)
    }


def discord_router_status(settings):
    secret = _clean_text(settings.get("discord_ingest_secret"))
    guilds = _split_allowlist(settings.get("discord_allowed_guild_ids"))
    channels = _split_allowlist(settings.get("discord_allowed_channel_ids"))
    authors = _split_allowlist(settings.get("discord_allowed_author_ids"))
    tolerance = max(0, _coerce_int(settings.get("discord_timestamp_tolerance_seconds"), 0))
    return {
        "enabled": _coerce_bool(settings.get("discord_router_enabled")),
        "secret_configured": bool(secret),
        "signature_required": _coerce_bool(settings.get("discord_signature_required")),
        "guild_allowlist_configured": bool(guilds),
        "guild_allowlist_count": len(guilds),
        "channel_allowlist_configured": bool(channels),
        "channel_allowlist_count": len(channels),
        "author_allowlist_configured": bool(authors),
        "author_allowlist_count": len(authors),
        "timestamp_tolerance_configured": tolerance > 0,
        "timestamp_tolerance_seconds": tolerance,
        "replay_guard_configured": _coerce_bool(settings.get("discord_replay_guard_enabled")),
        "source": DISCORD_SOURCE,
        "mode": "capture_only",
    }


def _authorization_token(headers):
    authorization = _clean_text(headers.get("Authorization"))
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def provided_ingest_secret(headers):
    return (
        _clean_text(headers.get("X-Nexus-Discord-Secret"))
        or _clean_text(headers.get("X-Discord-Ingest-Secret"))
        or _authorization_token(headers)
    )


def verify_ingest_secret(settings, headers):
    status = discord_router_status(settings)
    if not status["enabled"]:
        return False, "Discord router is disabled."
    expected = _clean_text(settings.get("discord_ingest_secret"))
    if not expected:
        return False, "Discord router ingest secret is not configured."
    submitted = provided_ingest_secret(headers)
    if not submitted or not hmac.compare_digest(submitted, expected):
        return False, "Discord router authentication failed."
    return True, None


def _signature_value(headers):
    submitted = (
        _clean_text(headers.get("X-Nexus-Discord-Signature"))
        or _clean_text(headers.get("X-Discord-Signature"))
    )
    if submitted.lower().startswith("sha256="):
        return submitted.split("=", 1)[1].strip()
    return submitted


def verify_ingest_signature(settings, headers, raw_body):
    if not _coerce_bool(settings.get("discord_signature_required")):
        return True, None
    expected_secret = _clean_text(settings.get("discord_ingest_secret"))
    if not expected_secret:
        return False, "Discord router signature secret is not configured."
    submitted = _signature_value(headers)
    if not submitted:
        return False, "Discord router signature is required."
    body = raw_body or b""
    if isinstance(body, str):
        body = body.encode("utf-8")
    digest = hmac.new(expected_secret.encode("utf-8"), body, sha256).hexdigest()
    if not hmac.compare_digest(submitted, digest):
        return False, "Discord router signature verification failed."
    return True, None


def _first_present(payload, keys):
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return value
    return None


def _nested(payload, *keys):
    current = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _id_from_object(value):
    if isinstance(value, dict):
        return _clean_text(value.get("id"), 128)
    return _clean_text(value, 128)


def _message_object(payload):
    message = payload.get("message")
    return message if isinstance(message, dict) else {}


def event_identity(payload):
    message = _message_object(payload)
    author = payload.get("author") or payload.get("user") or _nested(payload, "member", "user")
    channel = payload.get("channel")
    guild = payload.get("guild") or payload.get("server")
    return {
        "event_id": _redact_secret_text(
            _clean_text(
                _first_present(payload, ("id", "event_id", "message_id", "interaction_id"))
                or message.get("id"),
                128,
            )
        ),
        "guild_id": _redact_secret_text(
            _clean_text(
                _first_present(payload, ("guild_id", "server_id"))
                or _id_from_object(guild),
                128,
            )
        ),
        "channel_id": _redact_secret_text(
            _clean_text(
                _first_present(payload, ("channel_id",))
                or message.get("channel_id")
                or _id_from_object(channel),
                128,
            )
        ),
        "author_id": _redact_secret_text(
            _clean_text(
                _first_present(payload, ("author_id", "user_id"))
                or _id_from_object(author),
                128,
            )
        ),
        "timestamp": _clean_text(
            _first_present(payload, ("timestamp", "created_at"))
            or message.get("timestamp")
            or message.get("created_at"),
            80,
        ),
    }


def _author_name(payload):
    author = payload.get("author") or payload.get("user") or _nested(payload, "member", "user")
    if isinstance(author, dict):
        return (
            _clean_text(author.get("username"), 80)
            or _clean_text(author.get("global_name"), 80)
            or _clean_text(author.get("name"), 80)
            or _clean_text(author.get("id"), 80)
        )
    return _clean_text(author, 80)


def _command_name(payload):
    data = payload.get("data")
    if isinstance(data, dict):
        name = _clean_text(data.get("name"), 80)
        if name:
            return name
    return _clean_text(_first_present(payload, ("command", "command_name", "name")), 80)


def _message_content(payload):
    message = payload.get("message")
    if isinstance(message, dict):
        content = _clean_text(message.get("content"))
        if content:
            return content
    return _clean_text(_first_present(payload, ("content", "message", "text", "body")))


def _channel_name(payload):
    channel = payload.get("channel")
    if isinstance(channel, dict):
        return (
            _clean_text(channel.get("name"), 80)
            or _clean_text(channel.get("id"), 80)
        )
    return _clean_text(_first_present(payload, ("channel", "channel_name", "channel_id")), 80)


def _parse_timestamp(value):
    text = _clean_text(value, 80)
    if not text:
        return None
    if text.isdigit():
        number = int(text)
        if number > 100000000000:
            number = number / 1000
        return datetime.fromtimestamp(number, tz=timezone.utc)
    if text.endswith("Z"):
        text = "{}+00:00".format(text[:-1])
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _validate_allowlist(label, value, allowed):
    if allowed and value not in allowed:
        raise ValueError("Discord {} is not allowlisted.".format(label))


def validate_discord_capture(settings, headers, payload, db=None, workspace_id=None, raw_body=None):
    authorized, error = verify_ingest_secret(settings, headers)
    if not authorized:
        raise ValueError(error)
    signed, signature_error = verify_ingest_signature(settings, headers, raw_body)
    if not signed:
        raise ValueError(signature_error)
    if not isinstance(payload, dict):
        raise ValueError("JSON object is required.")

    identity = event_identity(payload)
    _validate_allowlist("guild", identity.get("guild_id"), _split_allowlist(settings.get("discord_allowed_guild_ids")))
    _validate_allowlist("channel", identity.get("channel_id"), _split_allowlist(settings.get("discord_allowed_channel_ids")))
    _validate_allowlist("author", identity.get("author_id"), _split_allowlist(settings.get("discord_allowed_author_ids")))

    tolerance = max(0, _coerce_int(settings.get("discord_timestamp_tolerance_seconds"), 0))
    if tolerance > 0 and identity.get("timestamp"):
        parsed = _parse_timestamp(identity.get("timestamp"))
        if parsed is None:
            raise ValueError("Discord timestamp could not be validated.")
        age = abs((datetime.now(timezone.utc) - parsed).total_seconds())
        if age > tolerance:
            raise ValueError("Discord event timestamp is outside tolerance.")

    replay_enabled = _coerce_bool(settings.get("discord_replay_guard_enabled"))
    if replay_enabled and db is not None and workspace_id is not None and identity.get("event_id"):
        existing = (
            db.execute(
                select(DiscordCaptureEvent)
                .where(
                    DiscordCaptureEvent.workspace_id == workspace_id,
                    DiscordCaptureEvent.event_id == identity["event_id"],
                    DiscordCaptureEvent.accepted == 1,
                )
                .limit(1)
            )
            .scalars()
            .first()
        )
        if existing is not None:
            raise ValueError("Discord event was already captured.")
    return identity


def create_discord_capture_event(db, workspace_id, identity, accepted, rejection_reason=None, inbox_item_id=None, commit=True):
    identity = identity or {}
    event = DiscordCaptureEvent(
        workspace_id=workspace_id,
        event_id=_clean_text(identity.get("event_id"), 128) or None,
        guild_id=_clean_text(identity.get("guild_id"), 128) or None,
        channel_id=_clean_text(identity.get("channel_id"), 128) or None,
        author_id=_clean_text(identity.get("author_id"), 128) or None,
        accepted=1 if accepted else 0,
        rejection_reason=_clean_text(_redact_secret_text(rejection_reason), MAX_REASON_CHARS) or None,
        inbox_item_id=inbox_item_id,
    )
    db.add(event)
    if commit:
        db.commit()
        db.refresh(event)
    return event


def normalize_discord_event(payload):
    if not isinstance(payload, dict):
        raise ValueError("JSON object is required.")

    content = _redact_secret_text(_message_content(payload))
    command = _redact_secret_text(_command_name(payload))
    author = _redact_secret_text(_author_name(payload))
    channel = _redact_secret_text(_channel_name(payload))
    identity = event_identity(payload)
    timestamp = identity.get("timestamp") or _clean_text(_first_present(payload, ("timestamp", "created_at")), 80)
    event_type = _clean_text(_first_present(payload, ("type", "event_type")), 80)

    if not content and not command:
        raise ValueError("Discord event content or command name is required.")

    title_seed = command or content
    title = "Discord: {}".format(title_seed.splitlines()[0][:120])[:MAX_TITLE_CHARS]
    raw_lines = []
    if content:
        raw_lines.append(content)
    if command:
        raw_lines.append("Command: {}".format(command))
    if author:
        raw_lines.append("Author: {}".format(author))
    if channel:
        raw_lines.append("Channel: {}".format(channel))
    if timestamp:
        raw_lines.append("Timestamp: {}".format(timestamp))

    metadata = {
        "event_id": identity.get("event_id") or None,
        "guild_id": identity.get("guild_id") or None,
        "channel_id": identity.get("channel_id") or None,
        "author_id": identity.get("author_id") or None,
        "author": author or None,
        "channel": channel or None,
        "command": command or None,
        "timestamp": timestamp or None,
        "event_type": event_type or None,
    }
    metadata = {key: value for key, value in metadata.items() if value}
    triage_notes = "Captured from Discord for supervised triage."
    if metadata:
        triage_notes = "{} Metadata: {}".format(
            triage_notes,
            _redact_secret_text(json.dumps(metadata, ensure_ascii=True, sort_keys=True))[:MAX_METADATA_CHARS],
        )

    return {
        "title": title,
        "raw_intent": _redact_secret_text("\n".join(raw_lines).strip())[:MAX_BODY_CHARS],
        "source": DISCORD_SOURCE,
        "category": "discord",
        "priority": "normal",
        "triage_notes": triage_notes[:MAX_METADATA_CHARS],
    }
