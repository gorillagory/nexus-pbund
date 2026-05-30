from datetime import datetime, timezone

from src.services.git_explorer import redact_git_output


TRUST_STATUSES = {"unreviewed", "trusted", "revoked"}
TRUST_LEVELS = {"standard", "elevated"}


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


def normalize_trust_status(value):
    status = _clean_text(value, 32).lower()
    return status if status in TRUST_STATUSES else "unreviewed"


def normalize_trust_level(value):
    level = _clean_text(value, 32).lower()
    return level if level in TRUST_LEVELS else "standard"


def serialize_trust_metadata(work_packet):
    if work_packet is None:
        return {}
    return {
        "trust_status": normalize_trust_status(getattr(work_packet, "trust_status", None)),
        "trust_level": normalize_trust_level(getattr(work_packet, "trust_level", None)),
        "trust_reason": getattr(work_packet, "trust_reason", None),
        "trust_reviewer": getattr(work_packet, "trust_reviewer", None),
        "trust_notes": getattr(work_packet, "trust_notes", None),
        "trusted_at": work_packet.trusted_at.isoformat() if getattr(work_packet, "trusted_at", None) else None,
        "revoked_at": work_packet.revoked_at.isoformat() if getattr(work_packet, "revoked_at", None) else None,
    }


def mark_packet_trusted(db, work_packet, data):
    if data.get("confirm_trust") is not True:
        raise ValueError("confirm_trust=true is required.")

    reason = _clean_text(data.get("trust_reason") or data.get("reason"))
    notes = _optional_text(data.get("trust_notes") or data.get("notes"))
    if not reason and not notes:
        raise ValueError("trust reason or notes are required.")

    now = datetime.now(timezone.utc)
    work_packet.trust_status = "trusted"
    work_packet.trust_level = normalize_trust_level(data.get("trust_level"))
    work_packet.trust_reason = reason or notes
    work_packet.trust_reviewer = _optional_text(data.get("trust_reviewer") or data.get("reviewer"), 128)
    work_packet.trust_notes = notes
    work_packet.trusted_at = now
    work_packet.revoked_at = None
    db.commit()
    db.refresh(work_packet)
    return work_packet


def revoke_packet_trust(db, work_packet, data):
    if data.get("confirm_revoke") is not True:
        raise ValueError("confirm_revoke=true is required.")

    reason = _clean_text(data.get("trust_reason") or data.get("reason") or data.get("trust_notes") or data.get("notes"))
    if not reason:
        raise ValueError("revoke reason or notes are required.")

    now = datetime.now(timezone.utc)
    work_packet.trust_status = "revoked"
    work_packet.trust_level = normalize_trust_level(getattr(work_packet, "trust_level", None))
    work_packet.trust_reason = reason
    work_packet.trust_notes = _optional_text(data.get("trust_notes") or data.get("notes"))
    work_packet.revoked_at = now
    db.commit()
    db.refresh(work_packet)
    return work_packet


def is_packet_trusted(work_packet):
    return normalize_trust_status(getattr(work_packet, "trust_status", None)) == "trusted"


def packet_trust_eligible(work_packet, trusted_packet_mode_enabled=False):
    enabled = bool(trusted_packet_mode_enabled)
    trusted = is_packet_trusted(work_packet)
    return {
        "trusted_packet_mode_enabled": enabled,
        "eligible": (not enabled) or trusted,
        "reason": "trusted packet mode disabled"
        if not enabled
        else ("packet trusted" if trusted else "trusted packet mode requires trust_status=trusted"),
        "trust": serialize_trust_metadata(work_packet),
    }


def summarize_trust_gate(settings, work_packet=None):
    enabled = bool(settings.get("trusted_packet_mode_enabled"))
    summary = {
        "trusted_packet_mode_enabled": enabled,
        "mode": "enabled" if enabled else "disabled",
    }
    if work_packet is not None:
        summary["packet"] = packet_trust_eligible(
            work_packet,
            trusted_packet_mode_enabled=enabled,
        )
    return summary
