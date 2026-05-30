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
- Keep reusable successful prompts in the Prompt Vault.
- Use Packet Drafting Assistant to generate, edit, save, review, and copy packet prompts from Prompt Vault templates and selected context. It is draft-only and does not execute the prompt.
- Use Work Packet Readiness Checklist before trust or supervised execution to identify missing safety, scope, verification, and report metadata. It is guidance only and does not trust or execute packets.
- Use Operator Review History to inspect or add audit notes for human governance decisions. It is audit-only visibility and does not execute, trust, recover, or mutate Git state.
- Use packet-aware preflight for local checks/reporting before merge: `python3 scripts/nexus_preflight.py --packet 34 --report /tmp/nexus-preflight-packet-034.md`. It does not execute packets, run Codex, auto-fix files, write Git state, or replace human review, readiness, or trust.
- Treat Discord as capture-only. Discord hardening may reject non-allowlisted, stale, replayed, unsigned, or unauthenticated payloads before inbox capture, but it must never execute Codex, tasks, packets, Git actions, trust changes, or Auto-Pilot.
- Use `docs/OPERATOR_RUNBOOK.md`, `docs/DEPLOYMENT_RUNBOOK.md`, and `docs/RECOVERY_RUNBOOK.md` for day-to-day operation, deployment verification, recovery, baseline tagging, and new-chat handoff.

## Safety Rails

- Do not expose API keys.
- Do not use `shell=True` or `subprocess.Popen`.
- Do not call execution routes unless explicitly allowed.
- Do not start Auto-Pilot unless explicitly building or testing it.
- Do not force push, reset, clean, or delete data without explicit instruction.
- Do not treat a generated packet draft as trusted or executable until the operator explicitly reviews and chooses the supervised execution path.
