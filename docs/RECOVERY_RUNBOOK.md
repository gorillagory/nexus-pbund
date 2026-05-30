# Nexus Recovery Runbook

Recovery is supervised. Inspect first, record decisions, verify locally, and only retry or continue with explicit approval.

## Failed Run Inspection

1. Open Factory Console.
2. Inspect execution run details.
3. Read stdout, stderr, changed files, and factory events.
4. Check Git Explorer for read-only repo state.
5. Add an operator note.
6. Create or update an Operator Intervention Queue item if human action is needed.
7. Add an Operator Review History note for the decision.
8. Check Mobile Operator Alerts if the operator needs phone notification for attention-required states.

## Review Required Flow

Use review-required states to pause, not to automate. A blocked run should become one of:

- explicit retry approval,
- explicit continue-packet approval,
- corrective work packet,
- intervention item,
- documented discard or stop decision.

Retry and continue are not automatic and require explicit approval.

## Verification During Recovery

Run:

```bash
git status --short
python3 scripts/nexus_preflight.py --quick
python3 scripts/nexus_preflight.py --packet 36 --report /tmp/nexus-preflight-packet-036.md
python3 scripts/verify_factory_regression_suite.py
```

If the failure touched a specific packet, run that packet verifier directly and through packet-aware preflight.

## Restoring Workflow Discipline

- Return raw new ideas to Orchestration Inbox.
- Convert inbox items only into non-executing workflow records.
- Draft or update packet prompts before implementation.
- Re-run readiness before trust or execution.
- Trust or revoke only with explicit operator confirmation and reason.
- Keep Operator Review History and Intervention Queue updated.
- Tag a new baseline only after verification passes.

## Explicit Approval Required

- Retry a failed task.
- Continue a packet after failure.
- Run a packet or task.
- Use Auto-Pilot.
- Run destructive database action.
- Use `git reset`, `git clean`, force push, branch deletion, or broad Git writes.

## Secret Handling

- Do not paste raw API keys, Discord ingest secrets, HMAC signatures, passwords, tokens, or private keys into docs, reports, UI, inbox items, queue items, review history, or prompts.
- Redact stdout/stderr before sharing externally.
- Packet-aware preflight reports bound and redact command output, but operators remain responsible for reviewing reports before sharing.

## Discord Capture Recovery

Rejected Discord payloads do not create inbox items. Review the Discord Router status and capture audit, then fix allowlists, timestamp tolerance, signature settings, or shared secret configuration. Do not treat Discord as an execution path.

## Mobile Notification Recovery

Mobile Operator Alerts are notification-only. If alerts fail, inspect Factory Console status and recent notification records, verify the webhook is configured without exposing the raw URL, and send a test notification. Notification failure must not change the original workflow result and must not become a retry, continue, execution, Git, trust, or Auto-Pilot path.
