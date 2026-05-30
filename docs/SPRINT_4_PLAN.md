# Nexus Sprint 4 Plan

## Sprint Goal

Sprint 4 focuses on production hardening, operator observability, workflow integrity, verification maturity, and onboarding quality for the supervised factory.

This sprint must keep Nexus in Supervised Factory Alpha. Execution remains supervised and explicit. Auto-Pilot remains locked.

## Current Baseline

- Latest completed baseline: `nexus-sprint-4-direction-baseline-2026-05-30`
- Sprint 3 status: complete at Packet 036.
- Packet 037 status: Sprint 4 Direction Lock complete.
- Next packet: Packet 038 -- Mobile Operator Notification Bridge.

## Sprint 3 Delivered

- Packet 029 -- Inbox Triage Conversion Flow.
- Packet 030 -- Packet Drafting Assistant.
- Packet 031 -- Work Packet Readiness Checklist.
- Packet 032 -- Operator Review History.
- Packet 033 -- Factory Console Consolidation.
- Packet 034 -- Packet-Aware Preflight Expansion.
- Packet 035 -- Discord Capture Hardening.
- Packet 036 -- Deployment And Operator Runbooks.

## Current Capabilities

- Orchestration Inbox captures manual and Discord-originated intent before triage.
- Hardened Discord capture can reject unsigned, stale, replayed, or non-allowlisted payloads before inbox capture.
- Inbox Triage Conversion Flow converts reviewed intent into non-executing workflow records or audited discards.
- Prompt Vault stores reusable operator prompt templates.
- Packet Drafting Assistant generates, saves, reviews, and copies structured packet drafts without executing them.
- Work Packet Manager tracks packet records and supervised packet workflow state.
- Work Packet Readiness Checklist evaluates packet planning, safety, scope, verification, and report metadata.
- Trusted Packet Mode can restrict supervised packet execution to explicitly trusted packets.
- Operator Intervention Queue tracks human decisions, blockers, and review items manually.
- Operator Review History records append-only governance and review events.
- Factory Console groups supervised factory surfaces and shows read-only summary visibility.
- Mobile Operator Notification Bridge sends outbound Discord alerts for operator attention without enabling mobile execution.
- Git Explorer provides read-only branch, status, commit, tag, change, and bounded diff visibility.
- Branch Per Packet prepares one validated packet branch from clean `main` after explicit confirmation.
- Recovery controls support failed-run inspection, notes, review-required marking, and supervised recovery decisions.
- Local, CI, and packet-aware preflight provide checks and bounded reports.
- Operator, deployment, and recovery runbooks document the daily operating model.
- Baseline tagging workflow is documented and expected after verified packet merges.

## Remaining Gaps

- Mobile awareness is needed while the operator is away from the terminal.
- Startup and environment diagnostics are still spread across runbooks and ad hoc checks.
- Configuration sanity is not summarized in one operator-safe health view.
- Run details, events, review history, interventions, readiness, trust, and inbox conversion context are still too disconnected.
- Work packet lifecycle states need a clearer state map and transition guidance.
- Packet-to-branch linkage remains operational knowledge instead of a first-class visible relationship.
- Readiness-to-trust workflow needs clearer guardrails and status presentation.
- Packet verifier discovery exists, but verifier ownership and feature coverage are not yet organized as a registry.
- CI reports can be easier to inspect as artifacts and operator summaries.
- New operator troubleshooting needs a symptom-to-action matrix.
- Discord setup needs a safe setup guide and test harness that remains capture-only or notification-only.

## Packet 038+ Roadmap

1. Packet 038 -- Mobile Operator Notification Bridge. Type: integration, observability, safety. Goal: send outbound Discord phone alerts when Nexus needs operator attention. Safety boundary: notification-only; no Discord command execution, no Codex/task/packet execution, no Git writes, no trust changes, no retry/continue automation, no Auto-Pilot.
2. Packet 039 -- Server-Side Codex Job Runner. Type: infra, safety, reliability. Goal: launch long Codex work as detached local operator jobs with status, logs, PID tracking, and report expectations under `/tmp/nexus-codex-jobs`. Safety boundary: terminal-only utility; no app/API execution controls, no Auto-Pilot, no Discord execution, no Git write UI.
3. Packet 040 -- Simple Operator Flow. Type: workflow, UI, safety. Goal: make the primary operator lane Input -> Draft -> Approve -> Execute one selected item -> Track. Safety boundary: explicit confirmation only, one selected task/work packet per approval, Trusted Packet Mode respected, no Auto-Pilot, no Discord execution, no Git write controls.
4. Packet 041 -- Linked Operator Context Timeline. Type: observability, UI. Goal: connect inbox items, conversions, drafts, readiness checks, trust decisions, interventions, review events, notifications, and execution runs into a readable operator context trail. Safety boundary: read-only timeline and append-only notes only; no retry, continue, execution, trust automation, or Git mutation.
5. Packet 042 -- Preflight Verifier Registry. Type: testing, safety, workflow. Goal: organize packet and feature verifiers into a registry with ownership, coverage, and expected commands. Safety boundary: checks and reporting only; no auto-fix, no execution routes, no workflow packet execution.
6. Packet 043 -- CI Report Artifact Polish. Type: infra, testing, observability. Goal: improve CI preflight output, packet-aware report artifacts, and operator-readable failure summaries. Safety boundary: CI reporting only; no deployment automation, no execution expansion, no secrets.
7. Packet 044 -- Operator Troubleshooting Matrix. Type: docs, onboarding, recovery. Goal: map common operator symptoms to safe inspection commands, runbook sections, and escalation points. Safety boundary: documentation only; no runtime behavior.
8. Packet 045 -- Discord Setup And Notification Harness. Type: integration, docs, testing. Goal: document hardened Discord setup and safe capture/notification checks. Safety boundary: Discord remains capture-only or notification-only; no Discord-triggered Codex, task, packet, Git, trust, recovery, or Auto-Pilot actions.
9. Packet 046 -- Sprint 4 Closure And Next Direction Lock. Type: docs, planning. Goal: close Sprint 4, summarize delivered hardening, and decide the next supervised roadmap. Safety boundary: planning only; no runtime behavior.

## Safety Boundaries

- Auto-Pilot remains locked unless a future packet explicitly scopes research, build, or test work for it.
- Discord remains capture-only. Discord must not execute Codex, tasks, packets, Git actions, trust changes, recovery, or Auto-Pilot.
- Outbound Discord notifications are phone alerts only. They must not include raw secrets, webhook URLs, full stdout/stderr, or command execution controls.
- Git Explorer remains read-only.
- Branch Per Packet remains narrow and may only prepare a validated packet branch after clean-worktree checks and explicit confirmation.
- Trusted Packet Mode remains restrictive only. It may block supervised packet execution when enabled; it must not execute or trust automatically.
- Operator Intervention Queue remains manual decision tracking.
- Operator Review History remains append-only audit visibility and must not replace source records.
- Packet-aware preflight remains checks and reporting only.
- Execution remains supervised and explicit through existing one-task or one-packet paths only.
- No destructive database operations, raw secret exposure, force push, reset, clean, broad Git write controls, automatic retry, automatic continue, trusted auto-execution, or direct Discord execution.

## Verification Expectations

Each Sprint 4 packet should include a focused verifier when it changes docs, workflow, UI, backend, infra, or safety behavior. Standard verification should include:

- `python3 scripts/nexus_preflight.py --quick`
- `python3 scripts/nexus_preflight.py --packet <packet-number> --report /tmp/nexus-preflight-packet-<packet-number>.md`
- The previous packet verifier.
- `python3 scripts/verify_factory_regression_suite.py`
- Syntax checks for changed Python or JavaScript files.
- `git diff --check`
- Safety inspection for execution route calls, Git write expansion, Auto-Pilot unlocks, raw secrets, and native browser prompts.

## Explicit Out Of Scope

- Auto-Pilot implementation or enablement.
- Direct Discord command execution.
- Commit, merge, push, pull, fetch, reset, clean, rebase, stash, tag, branch deletion, or broad checkout controls in the app.
- Automatic retry, automatic continue, automatic recovery, or autonomous execution.
- Trusted auto-execution or automatic trust marking.
- Runtime behavior that is not explicitly scoped by the active packet.
- Raw secret exposure in docs, reports, prompts, logs, UI, API responses, events, inbox items, review notes, or queue items.
