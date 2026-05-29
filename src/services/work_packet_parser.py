import re


CODEX_COMMAND_PATTERN = re.compile(r'\bcodex\s+"(?:\\.|[^"\\])*"')
METADATA_PATTERN = re.compile(
    r"^\s*(?:risk(?:\s+level)?|stop(?:\s+condition)?|estimated(?:\s+minutes)?|duration|timebox)\s*:",
    re.IGNORECASE,
)
SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(
        r"(?i)\b(api[_ -]?key|gemini_api_key|openai_api_key|secret|token)\b(\s*[:=]\s*[\"']?)([^\s\"'`]+)"
    ),
)


def _redact_secrets(text):
    if not isinstance(text, str):
        return ""

    redacted = text
    redacted = SECRET_PATTERNS[0].sub("[REDACTED_API_KEY]", redacted)
    redacted = SECRET_PATTERNS[1].sub("[REDACTED_API_KEY]", redacted)
    redacted = SECRET_PATTERNS[2].sub(
        lambda match: "{}{}[REDACTED_API_KEY]".format(match.group(1), match.group(2)),
        redacted,
    )
    return redacted


def extract_codex_commands(text):
    if not isinstance(text, str) or not text:
        return []

    try:
        return [match.group(0) for match in CODEX_COMMAND_PATTERN.finditer(text)]
    except Exception:
        return []


def _clean_title(line):
    title = (line or "").strip()
    title = re.sub(r"^\s{0,3}#{1,6}\s*", "", title).strip()
    title = re.sub(r"^\s*[-*+]\s+", "", title).strip()
    title = re.sub(r"^\s*\d+\s*[.)-]\s*", "", title).strip()
    title = re.sub(r"(?i)^\s*task\s+\d+\s*(?:[.)\-:]\s*|[\u2013\u2014]\s*)?", "", title).strip()
    return title


def _first_matching_value(lines, pattern):
    for line in lines:
        match = pattern.match(line)
        if match:
            return _redact_secrets(match.group(1).strip())
    return None


def _packet_title(lines):
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            title = _clean_title(stripped)
            if title:
                return _redact_secrets(title)

    for line in lines:
        stripped = line.strip()
        if stripped and "Packet" in stripped:
            title = _clean_title(stripped)
            if title:
                return _redact_secrets(title)

    for line in lines:
        stripped = line.strip()
        if stripped:
            title = _clean_title(stripped)
            if title:
                return _redact_secrets(title)

    return "Untitled Work Packet"


def _infer_task_title(text, command_start, order):
    prefix = text[:command_start]
    for line in reversed(prefix.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("```"):
            continue
        if CODEX_COMMAND_PATTERN.search(stripped):
            continue
        if METADATA_PATTERN.match(stripped):
            continue

        title = _clean_title(stripped)
        if title:
            return _redact_secrets(title[:255])

    return "Task {}".format(order)


def build_task_description(packet, task):
    packet = packet or {}
    task = task or {}
    title = _redact_secrets(packet.get("title") or "Untitled Work Packet")
    risk_level = _redact_secrets(packet.get("risk_level") or "unspecified")
    stop_condition = _redact_secrets(
        packet.get("stop_condition") or "Stop after packet completion or first failure."
    )
    codex_command = _redact_secrets(task.get("codex_command") or "")

    return "\n".join(
        [
            "## Work Packet",
            "",
            "- Title: {}".format(title),
            "- Risk level: {}".format(risk_level),
            "- Stop condition: {}".format(stop_condition),
            "",
            "### Codex command",
            "",
            "```bash",
            codex_command,
            "```",
        ]
    )


def parse_work_packet(text):
    if not isinstance(text, str) or not text:
        text = ""

    try:
        lines = text.splitlines()
        title = _packet_title(lines)
        risk_level = _first_matching_value(
            lines,
            re.compile(r"^\s*Risk(?:\s+Level)?\s*:\s*(.+?)\s*$", re.IGNORECASE),
        ) or "unspecified"
        stop_condition = _first_matching_value(
            lines,
            re.compile(r"^\s*(?:Stop\s+condition|Stop)\s*:\s*(.+?)\s*$", re.IGNORECASE),
        ) or "Stop after packet completion or first failure."
        estimated_minutes = _first_matching_value(
            lines,
            re.compile(
                r"^\s*(?:Estimated\s+minutes|Estimated|Duration|Timebox)\s*:\s*(.+?)\s*$",
                re.IGNORECASE,
            ),
        ) or ""

        packet = {
            "title": title,
            "risk_level": risk_level,
            "stop_condition": stop_condition,
            "estimated_minutes": estimated_minutes,
            "tasks": [],
        }

        matches = list(CODEX_COMMAND_PATTERN.finditer(text))
        for index, match in enumerate(matches, start=1):
            command = _redact_secrets(match.group(0))
            task = {
                "order": index,
                "title": _infer_task_title(text, match.start(), index),
                "description": "",
                "codex_command": command,
            }
            task["description"] = build_task_description(packet, task)
            packet["tasks"].append(task)

        return packet
    except Exception:
        return {
            "title": "Untitled Work Packet",
            "risk_level": "unspecified",
            "stop_condition": "Stop after packet completion or first failure.",
            "estimated_minutes": "",
            "tasks": [],
        }
