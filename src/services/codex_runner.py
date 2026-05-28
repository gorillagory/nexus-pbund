import json
import os
import re
import subprocess
import time
from dataclasses import dataclass


@dataclass
class CodexExecutionResult:
    status: str
    stdout: str
    stderr: str
    returncode: int
    timeout_seconds: int
    execution_time: float
    token_usage: dict
    command: list


def _safe_text(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def _normalize_usage_key(key):
    aliases = {
        "prompt_tokens": "input_tokens",
        "completion_tokens": "output_tokens",
    }
    return aliases.get(key, key)


def _merge_usage_value(usage, key, value):
    normalized_key = _normalize_usage_key(key)
    if normalized_key not in {"input_tokens", "output_tokens", "total_tokens"}:
        return
    if isinstance(value, bool):
        return
    try:
        usage[normalized_key] = int(value)
    except (TypeError, ValueError):
        return


def _extract_cli_token_usage(output):
    usage = {}
    try:
        text = output or ""
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or ("usage" not in stripped and "token" not in stripped):
                continue

            try:
                payload = json.loads(stripped)
            except (TypeError, ValueError):
                payload = None

            if not isinstance(payload, dict):
                continue

            candidates = []
            token_usage = payload.get("token_usage")
            if isinstance(token_usage, dict):
                candidates.append(token_usage)

            direct_usage = payload.get("usage")
            if isinstance(direct_usage, dict):
                candidates.append(direct_usage)

            candidates.append(payload)

            for candidate in candidates:
                for key in (
                    "input_tokens",
                    "output_tokens",
                    "total_tokens",
                    "prompt_tokens",
                    "completion_tokens",
                ):
                    if key in candidate:
                        _merge_usage_value(usage, key, candidate.get(key))

        patterns = {
            "input_tokens": r"(?i)(?:input|prompt)[_\s-]*tokens[\"']?\s*[:=]\s*(\d+)",
            "output_tokens": r"(?i)(?:output|completion)[_\s-]*tokens[\"']?\s*[:=]\s*(\d+)",
            "total_tokens": r"(?i)total[_\s-]*tokens[\"']?\s*[:=]\s*(\d+)",
        }
        for key, pattern in patterns.items():
            match = re.search(pattern, text)
            if match:
                _merge_usage_value(usage, key, match.group(1))
    except Exception:
        return {}

    return usage


def _default_timeout(prompt):
    try:
        from engine import calculate_prompt_timeout

        return calculate_prompt_timeout(prompt)
    except Exception:
        return min(300, 45 + len(prompt) // 50)


class CodexRunner:
    def __init__(self, timeout_factory=None):
        self.timeout_factory = timeout_factory

    def run(self, prompt, workspace_path, task_id=None):
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("Prompt must be a non-empty string.")

        workspace = os.path.abspath(os.path.expanduser(str(workspace_path)))
        if not os.path.exists(workspace):
            raise ValueError("Workspace path does not exist.")

        command_prompt = prompt
        command = ["codex", "exec", command_prompt]
        timeout_factory = self.timeout_factory or _default_timeout
        timeout_seconds = timeout_factory(command_prompt)
        environment = os.environ.copy()
        environment.update(
            {
                "CI": "true",
                "DEBIAN_FRONTEND": "noninteractive",
                "PYTHONUNBUFFERED": "1",
            }
        )

        started_at = time.time()
        stdout = ""
        stderr = ""
        try:
            process = subprocess.run(
                command,
                cwd=workspace,
                env=environment,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
                start_new_session=True,
            )
            stdout = _safe_text(process.stdout)
            stderr = _safe_text(process.stderr)
            returncode = process.returncode
            status = "success" if returncode == 0 else "failed"
        except subprocess.TimeoutExpired as exception:
            stdout = _safe_text(exception.stdout)
            stderr = _safe_text(exception.stderr)
            returncode = -1
            status = "timeout"

        output = "{0}\n{1}".format(stdout, stderr)
        return CodexExecutionResult(
            status=status,
            stdout=stdout,
            stderr=stderr,
            returncode=returncode,
            timeout_seconds=timeout_seconds,
            execution_time=time.time() - started_at,
            token_usage=_extract_cli_token_usage(output),
            command=list(command),
        )
