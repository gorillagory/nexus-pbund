import json
import os
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.services.cost_ledger import (  # noqa: E402
    append_cost_event,
    ensure_ledger_dir,
    ledger_path,
    read_cost_events,
    summarize_cost_events,
)


def fail(message):
    print("FAIL:", message)
    return False


def main():
    with tempfile.TemporaryDirectory() as root:
        ledger_dir = ensure_ledger_dir(root)
        if not ledger_dir.endswith(os.path.join(".nexus")):
            return fail("ledger dir should live under .nexus")

        path = ledger_path(root)
        record = append_cost_event(
            root,
            {
                "source": "test",
                "provider": "openai",
                "model": "example-model",
                "task_id": "T-1",
                "total_tokens": "123",
                "input_tokens": 100,
                "output_tokens": 23,
                "estimated_cost_usd": "0.0123456",
                "notes": "api_key=SECRET should not leak",
                "api_key": "SECRET",
            },
        )
        if "api_key" in record:
            return fail("secret fields should not be stored")
        if "SECRET" in json.dumps(record):
            return fail("secret-looking note content should be redacted")

        bearer_record = append_cost_event(
            root,
            {
                "source": "test",
                "notes": "Authorization: Bearer sk-test-secret",
            },
        )
        if "sk-test-secret" in json.dumps(bearer_record):
            return fail("bearer token notes should be redacted")

        with open(path, "a", encoding="utf-8") as file:
            file.write("not json\n")
            file.write(json.dumps({"source": "second", "total_tokens": 7}) + "\n")

        events = read_cost_events(root, limit=10)
        if len(events) != 3:
            return fail("reader should skip corrupt JSONL lines")

        limited = read_cost_events(root, limit=1)
        if len(limited) != 1 or limited[0].get("source") != "second":
            return fail("reader should return latest events up to limit")

        summary = summarize_cost_events(events)
        if summary.get("event_count") != 3:
            return fail("summary should count valid events")
        if summary.get("total_tokens") != 130:
            return fail("summary should total tokens")
        if summary.get("by_provider", {}).get("openai") != 1:
            return fail("summary should count providers")

    missing_events = read_cost_events(os.path.join(tempfile.gettempdir(), "missing-ledger"), limit=5)
    if missing_events != []:
        return fail("missing ledger should read as empty")

    print("cost_ledger_ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
