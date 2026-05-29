import os
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dashboard import NexusDashboard  # noqa: E402


class FakeEngine:
    def __init__(self, target_dir):
        self.target_dir = target_dir
        self.state = {}
        self.telemetry_logger = None


def fail(message):
    print("FAIL:", message)
    return False


def main():
    with tempfile.TemporaryDirectory() as root:
        dashboard = NexusDashboard(FakeEngine(root))
        client = dashboard.app.test_client()

        response = client.get("/api/cost-ledger")
        if response.status_code != 200:
            return fail("GET /api/cost-ledger should succeed")
        data = response.get_json()
        if data.get("status") != "success" or data.get("events") != []:
            return fail("empty ledger should return success with no events")

        response = client.post(
            "/api/cost-ledger/manual-entry",
            json={
                "provider": "openai",
                "model": "example-model",
                "source": "manual",
                "task_id": "T-1",
                "total_tokens": "25",
                "estimated_cost_usd": "0.0123",
                "notes": "manual adjustment",
            },
        )
        if response.status_code != 201:
            return fail("manual entry POST should create an event")
        summary = response.get_json().get("summary", {})
        if summary.get("event_count") != 1:
            return fail("manual entry should return updated summary")
        if summary.get("total_tokens") != 25:
            return fail("manual entry should summarize total_tokens")

        response = client.get("/api/cost-ledger")
        data = response.get_json()
        if len(data.get("events", [])) != 1:
            return fail("GET /api/cost-ledger should include recent events")
        if "estimated_cost_usd" not in data.get("summary", {}):
            return fail("GET /api/cost-ledger should include summary")

        response = client.post(
            "/api/cost-ledger/manual-entry",
            json={"total_tokens": 1, "notes": "Authorization: Bearer sk-test-secret"},
        )
        if response.status_code != 400:
            return fail("manual entry should reject secret-looking notes")
        if "sk-test-secret" in response.get_data(as_text=True):
            return fail("error response must not expose submitted secrets")

        response = client.post(
            "/api/cost-ledger/manual-entry",
            json={"total_tokens": 1, "api_key": "sk-test-secret"},
        )
        if response.status_code != 400:
            return fail("manual entry should reject unsupported fields")
        if "sk-test-secret" in response.get_data(as_text=True):
            return fail("unsupported-field response must not expose submitted secrets")

        if not os.path.exists(os.path.join(root, ".nexus", "cost_ledger.jsonl")):
            return fail("manual entry should write the local cost ledger")

    print("dashboard_cost_ledger_routes_ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
