import hmac
import json
import re


DISCORD_SOURCE = "discord"
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


def discord_router_status(settings):
    secret = _clean_text(settings.get("discord_ingest_secret"))
    return {
        "enabled": _coerce_bool(settings.get("discord_router_enabled")),
        "secret_configured": bool(secret),
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


def normalize_discord_event(payload):
    if not isinstance(payload, dict):
        raise ValueError("JSON object is required.")

    content = _redact_secret_text(_message_content(payload))
    command = _redact_secret_text(_command_name(payload))
    author = _redact_secret_text(_author_name(payload))
    channel = _redact_secret_text(_channel_name(payload))
    timestamp = _clean_text(_first_present(payload, ("timestamp", "created_at")), 80)
    event_type = _clean_text(_first_present(payload, ("type", "event_type")), 80)

    if not content and not command:
        raise ValueError("Discord event content or command name is required.")

    title_seed = command or content
    title = "Discord: {}".format(title_seed.splitlines()[0][:120])
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
            json.dumps(metadata, ensure_ascii=True, sort_keys=True),
        )

    return {
        "title": title,
        "raw_intent": "\n".join(raw_lines).strip(),
        "source": DISCORD_SOURCE,
        "category": "discord",
        "priority": "normal",
        "triage_notes": triage_notes,
    }
