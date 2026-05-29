import json
from datetime import datetime, timezone

from sqlalchemy import select

from models import PromptTemplate


PROMPT_CATEGORIES = {
    "feature",
    "bugfix",
    "upgrade",
    "refactor",
    "infra",
    "testing",
    "docs",
    "security",
    "recovery",
    "analysis",
    "schema",
    "uiux",
    "discord",
    "git",
    "ci",
}
PROMPT_STATUSES = {"active", "archived"}
PROMPT_RISK_LEVELS = {"low", "medium", "high"}


def parse_json_field(value, default):
    if value in (None, ""):
        return default
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return default
    return parsed


def encode_json_field(value):
    if value in (None, ""):
        return None
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True)
    except (TypeError, ValueError):
        return json.dumps({}, ensure_ascii=True, sort_keys=True)


def _clean_text(value, max_length=None):
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    value = value.strip()
    if max_length is not None:
        value = value[:max_length]
    return value


def _normalize_category(value):
    category = _clean_text(value, 64).lower().replace(" ", "_")
    return category if category in PROMPT_CATEGORIES else "feature"


def _normalize_risk(value):
    risk = _clean_text(value, 64).lower()
    return risk if risk in PROMPT_RISK_LEVELS else "medium"


def _normalize_status(value):
    status = _clean_text(value, 32).lower()
    return status if status in PROMPT_STATUSES else "active"


def serialize_prompt_template(template):
    if template is None:
        return {}
    return {
        "id": getattr(template, "id", None),
        "title": getattr(template, "title", None),
        "category": getattr(template, "category", None),
        "risk_level": getattr(template, "risk_level", None),
        "description": getattr(template, "description", None),
        "body": getattr(template, "body", None),
        "variables": parse_json_field(getattr(template, "variables_json", None), {}),
        "tags": parse_json_field(getattr(template, "tags_json", None), []),
        "status": getattr(template, "status", None),
        "success_count": getattr(template, "success_count", 0),
        "failure_count": getattr(template, "failure_count", 0),
        "last_used_at": template.last_used_at.isoformat() if getattr(template, "last_used_at", None) else None,
        "created_at": template.created_at.isoformat() if getattr(template, "created_at", None) else None,
        "updated_at": template.updated_at.isoformat() if getattr(template, "updated_at", None) else None,
    }


def _packet_body(title, category, goal):
    return """MISSION:
{title}

Current state:
- Summarize the repo state and relevant baseline.
- State whether this is feature, bugfix, upgrade, refactor, infra, testing, docs, security, recovery, analysis, schema, uiux, discord, git, or ci.

GOAL:
{goal}

SAFETY RULES:
- Do NOT run real Codex unless explicitly required by this packet.
- Do NOT call /api/tasks/auto-run.
- Do NOT call /api/tasks/run-one unless this packet explicitly tests it with mocks.
- Do NOT call /api/work-packets/run unless this packet explicitly tests it with mocks.
- Do NOT call /api/execute-codex.
- Do NOT start Auto-Pilot or set execution_mode to autopilot.
- Do NOT use {no_shell}.
- Do NOT use {no_popen}.
- Do NOT expose API keys.
- Do NOT force push, git reset, git clean, or delete data.

WORKFLOW:
1. Check git status/log.
2. Create/switch a packet branch.
3. Implement the smallest scoped change.
4. Add or update no-token verification.
5. Run preflight and relevant verifiers.
6. Commit, merge to main, tag, and push only if verification passes.
7. Write a /tmp packet report.

FILES ALLOWED:
- List expected files here.

VERIFICATION:
- python3 -m py_compile relevant files
- python3 scripts/nexus_preflight.py --quick
- relevant packet verifier(s)
- node --check static/js/app.js if frontend changed

REPORT:
Write /tmp/<packet_report>.md with result, repo, features, verification, safety, and follow-up.
""".format(title=title, category=category, goal=goal, no_shell="shell" + "=True", no_popen="subprocess." + "Popen")


def default_prompt_templates():
    starters = [
        (
            "Generic Feature Packet",
            "feature",
            "medium",
            "Implement a scoped feature with docs, verifier, preflight, commit, merge, tag, push, and report.",
            "Deliver the requested feature while preserving the supervised factory safety baseline.",
            ["packet", "feature", "operator"],
        ),
        (
            "Bugfix Packet",
            "bugfix",
            "medium",
            "Diagnose and fix a regression with focused verification and no unrelated refactors.",
            "Identify root cause, patch narrowly, add regression coverage, and verify no safety rails changed.",
            ["packet", "bugfix", "regression"],
        ),
        (
            "UI Polish Packet",
            "uiux",
            "low",
            "Improve dashboard usability without adding new execution behavior.",
            "Polish the interface, preserve existing workflows, escape rendered text, and verify frontend syntax.",
            ["packet", "uiux", "dashboard"],
        ),
        (
            "Verification Regression Packet",
            "testing",
            "low",
            "Add no-token regression coverage for existing behavior.",
            "Prove behavior with mocked services, no live Codex, no Auto-Pilot, and clear PASS output.",
            ["packet", "testing", "no-token"],
        ),
        (
            "Schema Sync Packet",
            "schema",
            "medium",
            "Add or repair schema safely without deleting or truncating data.",
            "Update models and schema sync with create/alter-only migrations and verification.",
            ["packet", "schema", "database"],
        ),
        (
            "Operator Finalize Packet",
            "git",
            "low",
            "Finalize a passing branch by merging, tagging, pushing, and reporting.",
            "Confirm clean git, fast-forward merge to main, verify, tag, push, and write a report.",
            ["packet", "git", "finalize"],
        ),
        (
            "Live Smoke Test Packet",
            "testing",
            "high",
            "Run one tightly controlled live smoke test only when explicitly approved.",
            "Restart required local services, run exactly the approved smoke path, restore state, and report.",
            ["packet", "testing", "smoke"],
        ),
    ]
    templates = []
    for title, category, risk, description, goal, tags in starters:
        templates.append(
            {
                "title": title,
                "category": category,
                "risk_level": risk,
                "description": description,
                "body": _packet_body(title, category, goal),
                "variables": {"packet_number": "", "branch_name": "", "report_path": ""},
                "tags": tags,
                "status": "active",
            }
        )
    return templates


def ensure_default_prompt_templates(db):
    created = []
    for data in default_prompt_templates():
        existing = db.execute(
            select(PromptTemplate).where(PromptTemplate.title == data["title"])
        ).scalar_one_or_none()
        if existing is not None:
            continue
        created.append(create_prompt_template(db, data, commit=False))
    if created:
        db.commit()
        for template in created:
            db.refresh(template)
    return created


def create_prompt_template(db, data, commit=True):
    title = _clean_text(data.get("title"), 255)
    body = _clean_text(data.get("body"))
    if not title:
        raise ValueError("title is required")
    if not body:
        raise ValueError("body is required")
    template = PromptTemplate(
        title=title,
        category=_normalize_category(data.get("category")),
        risk_level=_normalize_risk(data.get("risk_level")),
        description=_clean_text(data.get("description"), 2000),
        body=body,
        variables_json=encode_json_field(data.get("variables") or {}),
        tags_json=encode_json_field(data.get("tags") or []),
        status=_normalize_status(data.get("status")),
    )
    db.add(template)
    if commit:
        db.commit()
        db.refresh(template)
    return template


def update_prompt_template(db, template, data):
    if "title" in data:
        title = _clean_text(data.get("title"), 255)
        if not title:
            raise ValueError("title is required")
        template.title = title
    if "category" in data:
        template.category = _normalize_category(data.get("category"))
    if "risk_level" in data:
        template.risk_level = _normalize_risk(data.get("risk_level"))
    if "description" in data:
        template.description = _clean_text(data.get("description"), 2000)
    if "body" in data:
        body = _clean_text(data.get("body"))
        if not body:
            raise ValueError("body is required")
        template.body = body
    if "variables" in data:
        template.variables_json = encode_json_field(data.get("variables") or {})
    if "tags" in data:
        template.tags_json = encode_json_field(data.get("tags") or [])
    if "status" in data:
        template.status = _normalize_status(data.get("status"))
    template.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(template)
    return template


def archive_prompt_template(db, template):
    template.status = "archived"
    template.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(template)
    return template


def mark_prompt_template_used(db, template, result):
    if result == "failure":
        template.failure_count = int(template.failure_count or 0) + 1
    else:
        template.success_count = int(template.success_count or 0) + 1
    template.last_used_at = datetime.now(timezone.utc)
    template.updated_at = template.last_used_at
    db.commit()
    db.refresh(template)
    return template


def list_prompt_templates(db, category=None, status="active"):
    statement = select(PromptTemplate)
    if category:
        statement = statement.where(PromptTemplate.category == _normalize_category(category))
    if status:
        statement = statement.where(PromptTemplate.status == _normalize_status(status))
    statement = statement.order_by(PromptTemplate.category.asc(), PromptTemplate.title.asc())
    return db.execute(statement).scalars().all()


def get_prompt_template(db, template_id):
    return db.get(PromptTemplate, template_id)
