# Nexus Chat Handoff

## Current Baseline
- Current branch: `main`
- Current commit at prior chat handoff: `208dbdbaecd646b013a590fae2db32d06daff408`
- Prior chat handoff summary: `208dbdb add chat handoff for next session`
- Latest Packet 033 baseline tag: `nexus-factory-console-consolidation-baseline-2026-05-30`
- Previous Packet 032 baseline tag: `nexus-operator-review-history-baseline-2026-05-30`
- Recent visible baseline tags:
  - `nexus-workflow-lock-prompt-vault-baseline-2026-05-29`
  - `nexus-recovery-audit-baseline-2026-05-29`
  - `nexus-failure-recovery-baseline-2026-05-29`
  - `nexus-ci-status-ingestion-baseline-2026-05-29`
  - `nexus-operator-ux-baseline-2026-05-29`
  - `nexus-ci-status-console-baseline-2026-05-29`
  - `nexus-ci-preflight-baseline-2026-05-29`
  - `nexus-local-preflight-baseline-2026-05-29`
  - `nexus-no-token-regression-baseline-2026-05-29`
  - `nexus-supervised-packet-runner-baseline-2026-05-29`
- Status: Supervised Factory Alpha.
- Git clean/pushed status at handoff creation: clean worktree, `main` aligned with `origin/main`.

## What Nexus Can Do Now
- Work Packet Manager
- Prompt Vault
- Orchestration Inbox
- Discord Event Router
- Git Explorer
- Branch Per Packet
- Operator Intervention Queue
- Trusted Packet Mode
- Sprint 3 Direction Lock
- Inbox Triage Conversion Flow
- Packet Drafting Assistant
- Work Packet Readiness Checklist
- Operator Review History
- Factory Console Consolidation
- Workflow Lock docs
- Orchestration-ready workflow foundation
- Supervised packet runner
- Run one task
- Factory Console
- Execution ledger
- Execution run records
- Factory events
- Changed file tracking
- Cost ledger
- Budget Guard
- Recovery controls
- Recovery audit trail
- Git status/diff foundation
- CI/preflight status panel
- Local preflight command
- GitHub Actions preflight
- No-token regression harness
- Schema sync repair script

## Safety Rules
- No force push.
- No `git reset` or `git clean` unless explicitly approved.
- No destructive database operations, including drop, truncate, bulk delete, or schema-destructive migration without explicit approval.
- No raw API key exposure in logs, docs, reports, commits, prompts, or UI output.
- No Auto-Pilot unless explicitly building or testing it.
- Do not call `/api/tasks/auto-run` unless explicitly intended.
- Do not call `/api/tasks/run-one` unless explicitly intended.
- Do not call `/api/work-packets/run` unless explicitly intended.
- Do not call `/api/execute-codex` unless explicitly intended.
- Do not set `execution_mode` to `autopilot` unless explicitly intended.
- No `shell=True`.
- No `subprocess.Popen`.
- Codex can run routine operator commands: `git status`, `git log`, `git add`, `git commit`, `git merge`, `git tag`, `git push`, verification scripts, local `curl` endpoint checks, and report generation.
- Prefer one pasteable Codex operator prompt that reduces manual copy/paste.

## Operating Modes
- `manual`: Default safety-first mode. Human operator chooses work, Codex prepares or applies scoped local changes, and no automatic task execution runs.
- `one_task`: Supervised single-task execution path. Intended for explicit, narrow runs only.
- `one_packet`: Supervised packet execution path. Intended for one reviewed work packet at a time with ledger, events, recovery, and preflight visibility.
- `autopilot`: Locked future mode. Treat as unavailable unless the user explicitly asks to build or test Auto-Pilot behavior.

## Locked Workflow
1. Idea Capture
2. Triage
3. Packet Drafting
4. Prompt Vault selection/saving
5. Staging to Kanban
6. Supervised execution
7. Factory Console visibility
8. Recovery
9. Preflight/CI
10. Baseline tag/push

## Current Roadmap
- Packet 022 — Orchestration Inbox foundation complete
- Packet 023 — Discord Event Router complete
- Packet 024 — Git Explorer complete
- Packet 025 — Branch Per Packet complete
- Packet 026 — Operator Intervention Queue complete
- Packet 027 — Trusted Packet Mode complete
- Packet 028 — Sprint 3 Direction Lock complete
- Packet 029 — Inbox Triage Conversion Flow complete
- Packet 030 — Packet Drafting Assistant complete
- Packet 031 — Work Packet Readiness Checklist complete
- Packet 032 — Operator Review History complete
- Packet 033 — Factory Console Consolidation complete
- Packet 034 — Packet-Aware Preflight Expansion
- Packet 035 — Discord Capture Hardening
- Packet 036 — Deployment And Operator Runbooks

## New Chat Startup Instructions
Ask the user to run this local context capture before planning new implementation work:

```bash
cd ~/garage/workspaces/nexus-pbund
git status --short
git log --oneline --decorate -20
python3 scripts/nexus_preflight.py --quick
cat docs/CHAT_HANDOFF.md
cat docs/WORKFLOW_LOCK.md
cat docs/SPRINT_PLAN.md
cat docs/SPRINT_3_PLAN.md
cat docs/PROMPTING_GUIDE.md
```

Paste the command output into the new ChatGPT chat.

## Instruction to Next Assistant
Act as The General / Lead Systems Architect.

Use the repository docs as source of truth. Do not rely on old ChatGPT memory when repo docs disagree.

Prefer one pasteable Codex operator prompt for local execution. Reduce manual copy/paste. Codex should act as the local operator for routine git, verification, local endpoint, and report tasks.

Keep the safety rails in this document. Do not force push, reset, clean, run destructive database operations, expose API keys, or start Auto-Pilot unless the user explicitly asks for that exact work.

Packet 033 consolidates Factory Console navigation into Command Center, Intake & Triage, Packet Preparation, Human Review, and Vault & Settings, with read-only summary visibility only. The next recommended packet is Packet 034 — Packet-Aware Preflight Expansion. Keep the work supervised: no Auto-Pilot, no direct Discord execution, no broad Git writes, no automatic recovery, no automatic trust, and no execution without explicit operator action.
