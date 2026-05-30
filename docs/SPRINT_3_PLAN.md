# Nexus Sprint 3 Plan

## Direction Lock

Sprint 3 is about supervised workflow quality. Nexus should become easier to operate from capture through triage, packet drafting, readiness review, trust, supervised execution, recovery, and baseline tagging.

Do not build autonomy in Sprint 3 by default. Auto-Pilot remains locked unless a future packet explicitly scopes Auto-Pilot build or test work.

## What Sprint 2 Delivered

- Capture-first intent intake through Orchestration Inbox.
- Authenticated Discord capture routed into the inbox.
- Read-only Git Explorer.
- Narrow Branch Per Packet preparation.
- Operator Intervention Queue for manual human decisions.
- Trusted Packet Mode with restrictive packet execution gate.
- Prompt Vault, Work Packet Manager, supervised packet runner, Run One Task, recovery controls, execution ledger, cost ledger, local preflight, CI status, and regression harnesses.

## Sprint 3 Priorities

1. Convert captured intent into explicit next artifacts.
2. Make packet drafting faster while staying copy/stage only.
3. Add readiness checks before a work packet is trusted or run.
4. Preserve review history across triage, trust, intervention, and recovery decisions.
5. Simplify the dashboard after Sprint 2 growth.
6. Expand verification without adding execution paths.
7. Harden capture integrations without direct execution.
8. Improve deployment and operator documentation.

## Recommended Packet 029+ Roadmap

### Packet 029 — Inbox Triage Conversion Flow

Type: workflow, backend, UI.

Build a guided flow that converts inbox items into one of four outcomes: task, work packet draft, document update note, or discard audit.

Safety boundary: conversion only. No Codex execution, no packet run, no task run, no Auto-Pilot.

Status: complete. Packet 029 adds audited conversion records, staged untrusted work packet creation, manual todo task creation, document update audit candidates, and audited discard. Converted packets remain `trust_status=unreviewed` until an operator explicitly trusts them.

### Packet 030 — Packet Drafting Assistant

Type: workflow, UI.

Use Prompt Vault templates and inbox context to help draft packet text that the operator can review and copy or stage.

Safety boundary: drafting and copying only. No automatic staging or execution.

Status: complete. Packet 030 adds a draft-only Packet Drafting Assistant with Prompt Vault template selection, inbox/work-packet/manual source context, deterministic structured prompt generation, saved draft records, review marking, and copy-to-clipboard. It does not execute generated drafts, stage automatically, trust packets, or call execution routes.

### Packet 031 — Work Packet Readiness Checklist

Type: safety, backend, UI.

Track whether a staged packet includes mission, safety rules, files allowed, verification commands, trust metadata, and rollback/stop criteria.

Safety boundary: readiness metadata only. Does not execute or bypass trust.

Status: complete. Packet 031 adds readiness metadata on work packets, deterministic checklist evaluation, readiness score/status/missing items, notes, and a Work Packet Manager panel. It is validation and guidance only: it does not execute packets, trust packets automatically, bypass Trusted Packet Mode, retry/continue runs, or perform Git actions.

### Packet 032 — Operator Review History

Type: workflow, backend, UI.

Create a consolidated audit trail for triage decisions, trust/revoke decisions, interventions, and recovery notes.

Safety boundary: audit trail only. No automatic recovery, retry, continue, or execution.

Status: complete. Packet 032 adds Operator Review History as an append-only audit timeline for inbox conversions, audited discards, readiness decisions, trust/revoke decisions, intervention decisions, packet draft review, manual notes, and a narrow review-required recovery marker. It is audit/visibility only: it does not execute packets, trust packets automatically, replace source records, retry/continue runs, recover automatically, or perform Git actions.

### Packet 033 — Factory Console Consolidation

Type: UI.

Reorganize Factory Console, Git Explorer, Branch Per Packet, Intervention Queue, and Trusted Packet surfaces for faster repeated operation.

Safety boundary: UI organization only. No new execution route calls and no new Git write controls.

Status: complete. Packet 033 groups the dashboard into Command Center, Intake & Triage, Packet Preparation, Human Review, and Vault & Settings, and adds a read-only Factory Console summary endpoint for counts and status cards. It is navigation/visibility only: it does not add execution behavior, Git write actions, trust auto-marking, retry/continue behavior, or Auto-Pilot behavior.

### Packet 034 — Packet-Aware Preflight Expansion

Type: safety, testing.

Add packet-specific checks for required docs, safety boundaries, route restrictions, verifier presence, and no-token execution safety.

Safety boundary: checks and reports only. No packet execution.

Status: complete. Packet 034 adds `python3 scripts/nexus_preflight.py --packet <number>`, `--report <path>`, and `--list-packet-checks`. It discovers strict packet verifier scripts, runs bounded local verification commands, and writes redacted packet-aware operator reports. It is checks/reporting only: it does not execute packets, run Codex, auto-fix files, write Git state, call app execution routes, replace human review, bypass readiness, trust packets, or start Auto-Pilot.

### Packet 035 — Discord Capture Hardening

Type: integration, safety.

Add channel allowlisting or stronger signature-style verification for Discord capture.

Safety boundary: capture-only. Discord must not directly start Codex, tasks, packets, Git actions, or Auto-Pilot.

Status: complete. Packet 035 adds shared-secret plus optional HMAC signature verification, guild/channel/author allowlist checks, timestamp tolerance, replay guard tracking, capture audit records, redacted status, and audit-only review history notes for Discord capture accept/reject decisions. It remains capture-only: Discord cannot execute Codex, tasks, packets, Git actions, trust changes, retry/continue behavior, or Auto-Pilot.

### Packet 036 — Deployment And Operator Runbooks

Type: docs/planning.

Document setup, env vars, dashboard operations, recovery playbook, baseline tagging, and new-chat handoff practice.

Safety boundary: documentation only unless a verifier is added.

Status: complete. Packet 036 adds Operator, Deployment, and Recovery runbooks plus verifier coverage. It is documentation/runbook only and does not add runtime behavior, app execution controls, Git write UI/API, retry/continue automation, trust automation, direct Discord execution, or Auto-Pilot behavior.

## Sprint 3 Closure

Sprint 3 is complete. It delivered supervised workflow quality improvements from inbox conversion through runbooks while preserving explicit human execution.

Recommended next step: create a Sprint 4 Direction Lock before implementing additional feature work. Auto-Pilot, direct execution expansion, broad Git write controls, trusted auto-execution, and retry/continue automation remain out of scope until explicitly approved.

## Out Of Scope Until Explicit Approval

- Auto-Pilot buildout or enablement.
- Direct Discord command execution.
- Broad Git write controls in the app.
- Commit, merge, push, reset, clean, rebase, stash, tag, or branch deletion UI/API.
- Automatic retry, continue, recovery, or packet execution.
- Secret exposure in docs, reports, UI, API responses, prompts, or events.
