# Nexus Operator Runbook

Nexus is a Supervised Factory Alpha system. Operators capture intent, review and stage work, run explicit supervised execution only when chosen, recover deliberately, verify locally, tag a baseline, and hand off repo truth to the next chat.

## Starting The App Locally

```bash
cd ~/garage/workspaces/nexus-pbund
python3 -c 'import os; from engine import NexusEngine; from dashboard import NexusDashboard; NexusDashboard(NexusEngine(os.getcwd())).run(5055)'
```

Open `http://localhost:5055`.

Before work:

```bash
git status --short
git log --oneline --decorate -20
python3 scripts/nexus_preflight.py --quick
```

For a packet:

```bash
python3 scripts/nexus_preflight.py --packet 36 --report /tmp/nexus-preflight-packet-036.md
```

## Factory Console

- Use Command Center for mode, preflight, CI, Git Explorer summary, and Branch Per Packet status.
- Use Intake & Triage for Orchestration Inbox, inbox conversion, and Discord capture status.
- Use Packet Preparation for Work Packet Manager, Packet Drafting Assistant, Readiness Checklist, and Trusted Packet Mode.
- Use Human Review for Operator Intervention Queue, Operator Review History, and recovery visibility.
- Use Vault & Settings for Prompt Vault, provider settings, resources, and history.

## Capture And Triage

Capture raw ideas in Orchestration Inbox first. Discord-captured intent also lands in the inbox and remains capture-only. Every inbox item must become a scoped task, staged untrusted work packet, document update audit candidate, or audited discard.

Conversion is not execution. Converted work packets remain untrusted until explicitly reviewed and trusted.

## Packet Preparation

1. Draft the packet prompt with Packet Drafting Assistant or Prompt Vault templates.
2. Check readiness for mission, safety rules, files allowed, verification, report path, and trust visibility.
3. Use Work Packet Readiness Checklist before trust or supervised execution.
4. Use Branch Per Packet only to prepare one validated `factory/packet-###-safe-slug` branch from clean `main`.
5. Mark a packet trusted only after review, explicit confirmation, and a reason.
6. Run one task or one packet only through explicit supervised execution modes.

## Review And Recovery

- Use Operator Intervention Queue for blockers, required decisions, and recommended actions.
- Use Operator Review History for audit visibility and manual review notes.
- Use recovery controls to inspect failed runs, stdout, stderr, changed files, and events.
- Retry or continue requires explicit approval and the appropriate supervised mode.

## Git And Baselines

Normal packet workflow:

```bash
git switch -c factory/packet-###-safe-slug
python3 scripts/nexus_preflight.py --packet ### --report /tmp/nexus-preflight-packet-###.md
git add <scoped files>
git commit -m "<packet summary>"
git switch main
git merge --ff-only factory/packet-###-safe-slug
git tag nexus-<packet-baseline>-2026-05-30
git push origin main
git push origin nexus-<packet-baseline>-2026-05-30
```

Do not force push. Do not use `git reset` or `git clean` unless explicitly approved.

## New Chat Handoff

Use repo truth:

```bash
cd ~/garage/workspaces/nexus-pbund
git status --short
git log --oneline --decorate -20
python3 scripts/nexus_preflight.py --quick
python3 scripts/nexus_preflight.py --list-packet-checks
cat docs/CHAT_HANDOFF.md
cat docs/WORKFLOW_LOCK.md
cat docs/SPRINT_PLAN.md
cat docs/SPRINT_3_PLAN.md
cat docs/OPERATOR_RUNBOOK.md
cat docs/DEPLOYMENT_RUNBOOK.md
cat docs/RECOVERY_RUNBOOK.md
```

## Do Not Do

- No Auto-Pilot unless explicitly building or testing it.
- No direct Discord execution.
- No destructive database operations.
- No raw secret exposure in docs, reports, UI, API responses, events, inbox items, or prompts.
- Git Explorer is read-only.
- No force push, reset, clean, branch deletion, or broad Git write controls in the app.
- No `shell=True` or `subprocess.Popen`.
- No native browser `alert()` or `confirm()`.
