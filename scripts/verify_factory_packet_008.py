import json
import os
import re
import sys
import tempfile


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


def fail(message):
    print("FAIL: {}".format(message))
    return False


def pass_line(message):
    print("PASS: {}".format(message))


def read_text(relative_path):
    path = os.path.join(ROOT_DIR, relative_path)
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def js_method_body(source, method_name):
    match = re.search(
        r"(?:async\s+)?{}\s*\([^)]*\)\s*\{{(?P<body>.*?)(?=\n    (?:async\s+)?[A-Za-z0-9_]+\s*\([^)]*\)\s*\{{|\n\}};)".format(
            re.escape(method_name)
        ),
        source,
        re.DOTALL,
    )
    return match.group("body") if match else ""


def main():
    checks = []

    from src.services.codex_runner import _extract_cli_token_usage
    from src.services.cost_ledger import (
        append_cost_event,
        ledger_path,
        read_cost_events,
        summarize_cost_events,
    )

    usage = _extract_cli_token_usage("tokens used\n20,578")
    checks.append(
        usage.get("total_tokens") == 20578
        or fail("_extract_cli_token_usage did not parse tokens used block")
    )
    pass_line("_extract_cli_token_usage parses tokens used total")

    with tempfile.TemporaryDirectory() as root_dir:
        first = append_cost_event(
            root_dir,
            {
                "source": "manual",
                "provider": "openai",
                "model": "example-model",
                "task_id": "T-008",
                "total_tokens": "100",
                "input_tokens": 70,
                "output_tokens": 30,
                "estimated_cost_usd": "0.123456",
                "notes": "packet 008 verification",
            },
        )
        second = append_cost_event(
            root_dir,
            {
                "source": "manual",
                "provider": "openai",
                "model": "example-model",
                "total_tokens": 25,
                "estimated_cost_usd": 0.01,
            },
        )
        checks.append(first.get("total_tokens") == 100 or fail("first ledger append coerces tokens"))
        checks.append(second.get("total_tokens") == 25 or fail("second ledger append stores tokens"))
        checks.append(os.path.exists(ledger_path(root_dir)) or fail("ledger file was not created"))

        with open(ledger_path(root_dir), "a", encoding="utf-8") as handle:
            handle.write("corrupt jsonl line\n")

        events = read_cost_events(root_dir, limit=10)
        summary = summarize_cost_events(events)
        dumped_events = json.dumps(events, sort_keys=True)
        checks.append(len(events) == 2 or fail("read_cost_events should skip corrupt lines"))
        checks.append(summary.get("event_count") == 2 or fail("summary event_count mismatch"))
        checks.append(summary.get("total_tokens") == 125 or fail("summary total_tokens mismatch"))
        checks.append(summary.get("input_tokens") == 70 or fail("summary input_tokens mismatch"))
        checks.append(summary.get("output_tokens") == 30 or fail("summary output_tokens mismatch"))
        checks.append("api_key" not in dumped_events or fail("ledger events expose api_key"))
    pass_line("cost ledger appends, reads, and summarizes temporary events")

    dashboard_text = read_text("dashboard.py")
    checks.append('"/api/cost-ledger"' in dashboard_text or fail("/api/cost-ledger route missing"))
    checks.append(
        '"/api/cost-ledger/manual-entry"' in dashboard_text
        or fail("/api/cost-ledger/manual-entry route missing")
    )
    checks.append(
        "append_cost_event" in dashboard_text
        and "read_cost_events" in dashboard_text
        and "summarize_cost_events" in dashboard_text
        or fail("dashboard does not use cost ledger helpers")
    )
    pass_line("dashboard cost ledger routes are present")

    app_text = read_text("static/js/app.js")
    template_text = read_text("templates/index.html")
    ui_text = app_text + "\n" + template_text
    required_ui = "Budget Guard: manual tracking only. No automatic spending is triggered here."
    checks.append("Budget Guard" in ui_text or fail("Budget Guard heading missing"))
    checks.append(required_ui in ui_text or fail("Budget Guard manual tracking text missing"))
    checks.append("loadCostLedger" in app_text or fail("loadCostLedger frontend method missing"))
    checks.append("renderCostLedger" in app_text or fail("renderCostLedger frontend method missing"))
    checks.append(
        "submitManualCostEntry" in app_text or fail("submitManualCostEntry frontend method missing")
    )
    checks.append('"/api/cost-ledger"' in app_text or fail("frontend cost ledger GET missing"))
    checks.append(
        '"/api/cost-ledger/manual-entry"' in app_text
        or fail("frontend manual cost entry POST missing")
    )

    cost_method_names = ("loadCostLedger", "renderCostLedger", "submitManualCostEntry")
    cost_js = "\n".join(js_method_body(app_text, method) for method in cost_method_names)
    checks.append(cost_js.strip() != "" or fail("cost ledger frontend method bodies not found"))
    checks.append(
        "/api/execute-codex" not in cost_js
        and "/api/tasks/auto-run" not in cost_js
        or fail("cost ledger frontend path references execution endpoints")
    )
    pass_line("Budget Guard frontend is present and avoids execution endpoints")

    if not all(checks):
        return 1

    pass_line("Packet 008 verification complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
