# Nexus Sprint Plan

## Current State

Nexus is in Supervised Factory Alpha.

Sprint 2 is complete. It delivered a remote-operable supervised factory foundation where the operator can capture intent, inspect repo state, stage packet work, supervise one task or one packet, recover from failures, and apply trust controls before packet execution.

## Sprint 2 Delivered

- Prompt Vault for reusable operator prompts.
- Orchestration Inbox for capture-first raw intent handling.
- Discord Event Router for authenticated Discord capture into the inbox.
- Git Explorer for read-only repository visibility.
- Branch Per Packet for narrow supervised packet branch preparation.
- Operator Intervention Queue for human review and decision tracking.
- Trusted Packet Mode for reviewed packet trust metadata and restrictive execution gating.
- Inbox Triage Conversion Flow for turning captured or triaged ideas into non-executing workflow records with audit notes.
- Packet Drafting Assistant for deterministic Prompt Vault based packet prompt drafts.
- Work Packet Readiness Checklist for planning, safety, and verification metadata review.
- Operator Review History for consolidated human governance and decision audit events.
- Factory Console Consolidation for grouped navigation and read-only dashboard summary visibility.
- Packet-Aware Preflight Expansion for packet-specific local checks and bounded operator reports.
- Discord Capture Hardening for allowlisted, timestamp-aware, replay-guarded capture intake.
- Deployment and Operator Runbooks for consistent operation, verification, recovery, deployment, and handoff.
- Packet 027 Trusted Packet Mode foundation.
- Supervised packet runner and Run One Task.
- Factory Console visibility, execution ledger, changed-file tracking, recovery controls, and recovery audit notes.
- Cost ledger and Budget Guard.
- Local quick preflight, GitHub Actions preflight, CI status panel, and no-token regression harness.
- Schema sync repair script.

## Current Safety Rules

Inbox capture rule: raw ideas are captured first, then triaged into a scoped task, work packet, document update, or explicit discard. The inbox must not execute work.

Discord router rule: Discord-originated intent is accepted only through the capture router, stored as source `discord`, and then triaged in the Orchestration Inbox. Discord must not directly start Codex, tasks, packets, or Auto-Pilot.

Discord capture hardening rule: Discord remains capture-only. Hardening controls restrict what can enter the Orchestration Inbox through shared-secret/signature checks, optional guild/channel/author allowlists, timestamp tolerance, and replay guard audit. Rejected payloads must not create inbox items or leak secrets. Discord cannot execute Codex, tasks, packets, Git actions, trust changes, recovery, or Auto-Pilot.

Git Explorer rule: dashboard Git inspection is read-only. It may show branch, status, commits, baseline tags, changed files, diff stat, and bounded redacted diff previews. It must not expose git write actions.

Branch Per Packet rule: the app may only prepare a validated `factory/packet-###-safe-slug` branch from clean `main` after explicit operator confirmation. It must not commit, merge, push, pull, fetch, reset, clean, rebase, stash, tag, delete branches, or expose arbitrary checkout.

Operator Intervention Queue rule: the queue records human review items, blockers, recommended actions, and operator notes. It may acknowledge, resolve, dismiss, and update queue records only. It must not execute tasks, run packets, run Codex, retry or continue failed runs, recover automatically, perform Git actions, or start Auto-Pilot.

Trusted Packet Mode rule: operators may mark reviewed packets trusted or revoke trust with explicit confirmation and a recorded reason. Enabling Trusted Packet Mode does not execute automatically and does not unlock Auto-Pilot. When enabled, supervised packet execution is restricted to packets with `trust_status=trusted`.

Inbox conversion rule: captured or triaged inbox items may be converted only into reviewed non-executing records: staged work packet, manual todo task, document update audit candidate, or audited discard. Converted work packets remain `trust_status=unreviewed` until explicitly trusted. Discard keeps the inbox item and records an audit entry.

Packet drafting rule: Packet Drafting Assistant may generate, edit, save, review, and copy structured packet prompt drafts only. It must not execute generated prompts, stage automatically, mark packets trusted, call execution routes, perform Git writes, retry/continue runs, or start Auto-Pilot.

Readiness checklist rule: Work Packet Readiness Checklist evaluates and stores readiness metadata only. It does not bypass Trusted Packet Mode, execute packets, trust packets automatically, retry/continue runs, perform Git actions, or start Auto-Pilot.

Operator review history rule: Operator Review History is audit and visibility only. It records human review decisions and governance events, preserves original source records, and must not execute packets, trust packets automatically, recover automatically, perform Git actions, retry/continue runs, or start Auto-Pilot.

Factory Console consolidation rule: the consolidated Factory Console is navigation and visibility only. It may group dashboard surfaces and show read-only summary counts, but it must not add execution behavior, Git write controls, automatic trust changes, retry/continue behavior, or Auto-Pilot behavior. Git Explorer remains read-only.

Packet-aware preflight rule: packet-aware preflight is local checks/reporting only. It may discover and run strict `verify_factory_packet_###.py` verifier scripts and write bounded redacted reports, but it does not execute packets, run Codex, auto-fix files, write Git state, call app execution routes, or replace human review, readiness, or trust.

Packet-aware preflight does not auto-fix files, does not write Git state, and does not replace human review, readiness, or trust.

Auto-Pilot remains locked. Do not build, enable, or rely on Auto-Pilot unless a future packet explicitly scopes Auto-Pilot build/test work.

Runbook rule: `docs/OPERATOR_RUNBOOK.md`, `docs/DEPLOYMENT_RUNBOOK.md`, and `docs/RECOVERY_RUNBOOK.md` are the operator references for daily workflow, deployment checks, recovery, baseline tagging, and new-chat handoff. They are documentation only and do not add runtime execution behavior.

## Sprint 3 Direction

Sprint 3 is complete. It prioritized supervised workflow quality, not autonomy, and made captured intent flow into reviewed, ready, trusted work packets while preserving explicit human execution.

Do not automatically choose Auto-Pilot. Auto-Pilot remains out of scope until explicitly approved.

## Sprint 3 Packet Roadmap

1. Packet 028 — Sprint 3 Direction Lock. Type: docs/planning, safety. Boundary: documents direction only; no runtime behavior. Complete.
2. Packet 029 — Inbox Triage Conversion Flow. Type: workflow, backend, UI. Boundary: converts inbox items into task, staged untrusted work packet, document update note, or discard audit only; no execution. Complete.
3. Packet 030 — Packet Drafting Assistant. Type: workflow, backend, UI. Boundary: uses Prompt Vault templates and selected context to draft, save, review, and copy packet text; does not run Codex, stage automatically, or trust packets. Complete.
4. Packet 031 — Work Packet Readiness Checklist. Type: safety, backend, UI. Boundary: validates safety rules, files allowed, verification commands, and trust visibility before readiness; does not execute or trust packets. Complete.
5. Packet 032 — Operator Review History. Type: workflow, backend, UI. Boundary: records triage, trust/revoke, intervention, readiness, and recovery decisions; no automatic recovery or execution. Complete.
6. Packet 033 — Factory Console Consolidation. Type: UI. Boundary: reorganizes existing visibility and controls; no new execution or Git write capability. Complete.
7. Packet 034 — Packet-Aware Preflight Expansion. Type: safety, testing. Boundary: adds checks and reports only; no execution route calls. Complete.
8. Packet 035 — Discord Capture Hardening. Type: integration, safety. Boundary: channel allowlisting or stronger verification for capture-only ingest; Discord still cannot execute work. Complete.
9. Packet 036 — Deployment And Operator Runbooks. Type: docs/planning. Boundary: documentation only; no runtime changes unless verification requires a docs checker. Complete.

## Sprint 3 Closure

Sprint 3 is complete at Packet 036. The supervised factory now has capture-first intake, triage conversion, packet drafting, readiness checks, review history, console consolidation, packet-aware preflight, hardened Discord capture, and operator/deployment/recovery runbooks.

Packet 037 locks the Sprint 4 direction before adding new runtime behavior. Auto-Pilot remains locked until explicitly scoped.

## Sprint 4 Direction

Sprint 4 focuses on production hardening, operator observability, workflow integrity, verification maturity, and onboarding quality for the supervised factory.

The Sprint 4 plan is maintained in `docs/SPRINT_4_PLAN.md`. Packet 038 adds notification-only mobile operator awareness through outbound Discord alerts.

## Sprint 4 Packet Roadmap

1. Packet 037 — Sprint 4 Direction Lock. Type: docs/planning, safety. Boundary: documents direction only; no runtime behavior. Complete.
2. Packet 038 — Mobile Operator Notification Bridge. Type: integration, observability, safety. Boundary: outbound Discord phone alerts only; no Discord command execution, Codex execution, task/packet execution, Git writes, trust changes, retry/continue automation, or Auto-Pilot. Complete.
3. Packet 039 — Environment Validation And Startup Diagnostics. Type: infra, safety, observability. Boundary: diagnostics only; no execution routes, no Git writes, no raw secrets, no Auto-Pilot.
4. Packet 040 — Work Packet Lifecycle State Map. Type: workflow, UI, safety. Boundary: state visibility and metadata guidance only; no execution, no automatic trust, no branch or Git writes.
5. Packet 041 — Linked Operator Context Timeline. Type: observability, UI. Boundary: read-only timeline and append-only notes only; no retry, continue, execution, trust automation, or Git mutation.
6. Packet 042 — Preflight Verifier Registry. Type: testing, safety, workflow. Boundary: checks and reporting only; no auto-fix, no execution routes, no workflow packet execution.
7. Packet 043 — CI Report Artifact Polish. Type: infra, testing, observability. Boundary: CI reporting only; no deployment automation, no execution expansion, no secrets.
8. Packet 044 — Operator Troubleshooting Matrix. Type: docs, onboarding, recovery. Boundary: documentation only; no runtime behavior.
9. Packet 045 — Discord Setup And Notification Harness. Type: integration, docs, testing. Boundary: Discord remains capture-only or notification-only; no Discord-triggered Codex, task, packet, Git, trust, recovery, or Auto-Pilot actions.
10. Packet 046 — Sprint 4 Closure And Next Direction Lock. Type: docs/planning. Boundary: planning only; no runtime behavior.

## Local Configuration Notes

- Set `DISCORD_ROUTER_ENABLED=true` or enable Discord Router in Settings.
- Set `DISCORD_INGEST_SECRET` or save a shared ingest secret in Settings.
- Send the shared secret in `X-Nexus-Discord-Secret`, `X-Discord-Ingest-Secret`, or `Authorization: Bearer ...`.
- Enable `trusted_packet_mode_enabled` only when the operator wants supervised packet execution to require `trust_status=trusted`.
- Never place real secret values in docs, reports, commits, UI text, API responses, or events.
