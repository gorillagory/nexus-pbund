# Nexus Prompting Guide

## General Style

Use direct operator prompts. State the mission, current state, goal, safety rules, workflow, verification, git actions, and report path. Prefer one complete Codex operator prompt over many small copy/paste fragments.

## Codex Operator Prompt Style

Codex should inspect local context, make routine implementation decisions, run verification, commit, merge, tag, push when authorized, and write the report. The human should only approve risky direction or intervene on blockers.

## Packet Prompt Structure

- Mission.
- Current state / context.
- Goal.
- Safety Rules.
- Workflow.
- Files allowed.
- Parts A/B/C for implementation phases.
- Verification.
- Commit / Merge / Push.
- Report.

## Categories

- feature
- bugfix
- upgrade
- refactor
- infra
- testing
- docs
- security
- recovery
- analysis
- schema
- uiux
- discord
- git
- ci

## Reducing User Copy/Paste

- Use one Codex operator prompt.
- Let Codex run git, verification, and report writing itself.
- Write final reports to `/tmp`.
- Use Simple Operator Flow as the primary lane for routine work: capture one request, generate and review one draft, prepare one work packet, explicitly approve one selected run, and track the result.
- Keep reusable successful prompts in the Prompt Vault.
- Use Packet Drafting Assistant to generate, edit, save, review, and copy packet prompts from Prompt Vault templates and selected context. It is draft-only and does not execute the prompt.
- Use Work Packet Readiness Checklist before trust or supervised execution to identify missing safety, scope, verification, and report metadata. It is guidance only and does not trust or execute packets.
- Use Operator Review History to inspect or add audit notes for human governance decisions. It is audit-only visibility and does not execute, trust, recover, or mutate Git state.
- Use packet-aware preflight for local checks/reporting before merge: `python3 scripts/nexus_preflight.py --packet 34 --report /tmp/nexus-preflight-packet-034.md`. It does not execute packets, run Codex, auto-fix files, write Git state, or replace human review, readiness, or trust.
- Treat Discord as capture-only. Discord hardening may reject non-allowlisted, stale, replayed, unsigned, or unauthenticated payloads before inbox capture, but it must never execute Codex, tasks, packets, Git actions, trust changes, or Auto-Pilot.
- Use `docs/OPERATOR_RUNBOOK.md`, `docs/DEPLOYMENT_RUNBOOK.md`, and `docs/RECOVERY_RUNBOOK.md` for day-to-day operation, deployment verification, recovery, baseline tagging, and new-chat handoff.
- Use `docs/SPRINT_4_PLAN.md` for Sprint 4 packet direction. Sprint 4 is production hardening, operator observability, workflow integrity, verification maturity, and onboarding quality while keeping execution supervised and explicit.
- Treat Mobile Operator Alerts as notification-only. Alert text must be redacted and bounded, must not include raw webhook URLs or secrets, and must never imply Discord execution.

## Safety Rails

- Do not expose API keys.
- Do not use `shell=True` or `subprocess.Popen`.
- Do not call execution routes unless explicitly allowed.
- Do not start Auto-Pilot unless explicitly building or testing it.
- Do not force push, reset, clean, or delete data without explicit instruction.
- Do not treat a generated packet draft as trusted or executable until the operator explicitly reviews and chooses the supervised execution path.
- Do not use Simple Operator Flow to bypass Trusted Packet Mode, Auto-Pilot lock, Discord capture/notification boundaries, or explicit `confirm_run=true` approval.
