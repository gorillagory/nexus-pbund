import os
import re
import sys


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


def extract_between(text, start, end):
    if start not in text:
        return ""
    section = text.split(start, 1)[1]
    if end in section:
        section = section.split(end, 1)[0]
    return section


def verify_console_grouping():
    template = read_file("templates/index.html")
    app = read_file("static/js/app.js")
    style = read_file("static/style.css")

    for label in (
        "Supervised Factory Console",
        "Command Center",
        "Intake & Triage",
        "Packet Preparation",
        "Human Review",
        "Vault & Settings",
    ):
        check(label in template, "dashboard contains consolidated group: {}".format(label))

    for phrase in (
        "factory-console-map",
        "factory-console-map-grid",
        "factory-console-map-group",
        "nav-section-label",
    ):
        check(phrase in template + style, "console grouping style exists: {}".format(phrase))

    for phrase in (
        "latestFactoryConsoleSummary",
        "loadFactoryConsoleSummary",
        "/api/factory-console/summary",
        "Inbox To Triage",
        "Active Packets",
        "Interventions",
        "Readiness Attention",
        "Trusted Mode",
        "Latest Review Event",
        "read_only_visibility_only",
    ):
        check(phrase in app, "factory summary UI contains {}".format(phrase))

    check(re.search(r"\balert\s*\(", app + template) is None, "no native alert() in frontend")
    check(re.search(r"\bconfirm\s*\(", app + template) is None, "no native confirm() in frontend")


def verify_summary_endpoint():
    dashboard = read_file("dashboard.py")
    app = read_file("static/js/app.js")
    template = read_file("templates/index.html")
    summary_route = extract_between(dashboard, '@self.app.route("/api/factory-console/summary"', '@self.app.route("/api/factory/events"')
    summary_js = extract_between(app, "async loadFactoryConsoleSummary", "startFactoryConsolePolling")
    console_map = extract_between(template, '<section class="factory-console-map', '<div class="row g-4 mb-4">')

    check('/api/factory-console/summary", methods=["GET"]' in dashboard, "summary endpoint is GET-only")
    check("def get_factory_console_summary" in summary_route, "summary route exists")
    check("func.count" in summary_route, "summary endpoint aggregates counts")
    check("serialize_review_event" in summary_route, "summary endpoint uses safe review serialization")
    check("summarize_git_changes" in summary_route, "summary endpoint reuses read-only git summary")
    check("read_only_visibility_only" in summary_route + summary_js, "summary endpoint declares read-only boundary")

    for phrase in (
        "/api/tasks/auto-run",
        "/api/tasks/run-one",
        "/api/work-packets/run",
        "/api/execute-codex",
        "_execute_factory_task",
        "CodexRunner",
        "retry_factory_run",
        "continue_factory_run",
        "mark_packet_trusted(",
        "revoke_packet_trust(",
        "prepare_packet_branch",
        "set_execution_mode",
        "execution_mode =",
    ):
        check(phrase not in summary_route + summary_js + console_map, "consolidation code does not call {}".format(phrase))

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
        check(phrase not in summary_route + summary_js, "summary code does not expose {}".format(phrase))

    check("shell=True" not in summary_route + summary_js, "summary code avoids shell=True")
    check("subprocess.Popen" not in summary_route + summary_js and "Popen(" not in summary_route + summary_js, "summary code avoids subprocess.Popen")


def verify_docs():
    combined = "\n".join(
        read_file(path)
        for path in (
            "docs/SPRINT_PLAN.md",
            "docs/SPRINT_3_PLAN.md",
            "docs/WORKFLOW_LOCK.md",
            "docs/CHAT_HANDOFF.md",
        )
    )
    for phrase in (
        "Factory Console Consolidation",
        "navigation/visibility only",
        "does not add execution behavior",
        "Auto-Pilot remains locked",
        "Git Explorer remains read-only",
        "Branch Per Packet",
        "Trusted Packet Mode",
        "restrictive",
        "Packet 034 — Packet-Aware Preflight Expansion",
        "nexus-factory-console-consolidation-baseline-2026-05-30",
    ):
        check(phrase in combined, "docs preserve consolidation boundary: {}".format(phrase))


def main():
    verify_console_grouping()
    verify_summary_endpoint()
    verify_docs()
    if FAILURES:
        print("FAIL: Packet 033 verification failed")
        return 1
    print("PASS: Packet 033 verification complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
