# Nexus Workflow Lock v1.0

Nexus is currently operating as a supervised factory. The locked workflow keeps decisions visible, keeps execution explicit, and lets Codex handle routine operator work after the human sets direction.

## Idea Capture

Capture raw ideas in the Orchestration Inbox before they become work. Do not execute from capture. Every idea must become a scoped task, work packet, document update, or explicit discard.

Packet 022 added the Orchestration Inbox foundation for manual capture and later triage. The inbox is supervised only: it stores raw intent, priority, category, status, and triage notes without calling Codex, task execution, packet execution, or Auto-Pilot routes.

Packet 023 added the Discord Event Router foundation. Discord-originated operator intent is captured into the Orchestration Inbox with source `discord`; Discord messages do not execute tasks, packets, Codex, or Auto-Pilot directly.

Packet 035 hardened Discord capture. Discord ingest now supports optional signature verification, guild/channel/author allowlists, timestamp tolerance, replay guard audit, and redacted capture status. These controls only decide whether payloads may enter the Orchestration Inbox. Rejected payloads do not create inbox items and must not leak secrets.

## Triage

Triage asks four questions:

- What outcome is required?
- What files or systems are allowed to change?
- What safety rules apply?
- What verification proves the work?

If the answers are unclear, Codex should inspect local context first and ask the human only when the decision is risky or cannot be inferred.

Discord-captured items follow the same triage rule as manual inbox items. Each captured message must become a scoped task, work packet, document update, or explicit discard before any supervised execution path is considered.

Discord remains capture-only after hardening. It cannot execute Codex, run tasks, run packets, perform Git actions, trust packets, retry or continue work, or start Auto-Pilot.

Packet 029 added the Inbox Triage Conversion Flow. Captured or triaged inbox items may be converted only into non-executing workflow records: a staged untrusted work packet, a manual todo task, a document update audit candidate, or an audited discard. Conversion requires explicit operator confirmation, records a conversion audit, and never calls Codex, task execution, packet execution, Git write actions, recovery automation, Discord execution, or Auto-Pilot. Converted work packets stay `trust_status=unreviewed` until explicitly trusted.

## Packet Drafting

Packets use the Codex operator prompt structure:

- Mission
- Current state / context
- Goal
- Safety rules
- Workflow
- Files allowed
- Parts A/B/C as needed
- Verification
- Commit / merge / push instructions
- Report path under `/tmp`

Packet 030 added the Packet Drafting Assistant. It may collect manual, inbox, or work-packet context, use Prompt Vault templates, generate deterministic structured packet drafts, save draft records, mark drafts reviewed, and copy draft text. It is draft/review/copy/save only: it must not execute generated prompts, stage work automatically, call execution routes, perform Git writes, retry or continue runs, or start Auto-Pilot. It does not trust packets automatically.

## Prompt Vault Usage

Reusable prompts belong in the Prompt Vault. Use categories such as feature, bugfix, upgrade, refactor, infra, testing, docs, security, recovery, analysis, schema, uiux, discord, git, and ci.

The vault is for storing and copying prompts. It must not execute Codex, start Auto-Pilot, or call packet execution routes.

## Staging To Kanban

Drafted work can be staged to Kanban when it is scoped and has safety rules. Staging is not execution. Staged work is reviewed in the board before a supervised mode runs it.

Packet 031 added the Work Packet Readiness Checklist. It evaluates planning, safety, scope, verification, report, trust visibility, and branch-preparation metadata for a work packet. It may store readiness status, score, missing items, notes, and checker metadata. It is validation/guidance only and must not execute packets, trust packets automatically, bypass Trusted Packet Mode, perform Git writes, retry or continue runs, or start Auto-Pilot.

Packet 032 added Operator Review History. It records human review decisions and governance events as append-only audit records, including inbox conversions, audited discards, readiness decisions, trust/revoke decisions, intervention decisions, packet draft review, manual notes, and narrow review-required recovery markers. It is audit/visibility only and does not replace source records; it must not execute packets, trust packets automatically, recover automatically, retry or continue runs, perform Git writes, or start Auto-Pilot.

## Supervised Execution Modes

- `manual`: no automation. The operator inspects, edits, stages, and copies commands.
- `one_task`: run exactly one selected task.
- `one_packet`: run exactly one selected work packet.
- `autopilot`: locked for future work. Do not use unless explicitly building or testing Auto-Pilot.

Automatic analysis is enabled only for Auto-Pilot.

## Server-Side Codex Job Runner

Packet 039 adds the Server-Side Codex Job Runner for local operator reliability. It is a terminal-only CLI utility at `scripts/nexus_codex_job.py`; it is not an app route, API route, dashboard control, Discord command surface, packet executor, task executor, Auto-Pilot unlock, or Git write feature.

Use the job runner, or `tmux`, for long Codex jobs from a mobile SSH session. Do not run long Codex jobs in raw phone SSH foreground. A client disconnect must not be allowed to hide live work, logs, status, or report expectations.

Start a detached local Codex job with:

```bash
python3 scripts/nexus_codex_job.py start --name packet_039 --prompt-file /tmp/packet-039-prompt.txt --expect-report /tmp/nexus-packet-039-server-side-codex-job-runner-report.md
```

Recover after disconnect with:

```bash
python3 scripts/nexus_codex_job.py list
python3 scripts/nexus_codex_job.py status --job-id <job-id>
python3 scripts/nexus_codex_job.py tail --job-id <job-id>
```

Jobs live under `/tmp/nexus-codex-jobs/<job-id>/` and keep copied prompt text, bounded status metadata, PID tracking, and combined logs outside repo working files. `stop --job-id <job-id>` may stop only the recorded managed process and must not become broad `pkill` or `killall` behavior.

No Auto-Pilot, app/API execution controls, Discord execution, packet auto-execution, task auto-execution, broad Git write controls, raw secret exposure, or report writes into the repo are added by this runner.

## Factory Console Visibility

The Factory Console is the operator surface for mode, automatic analysis state, Git state, preflight, CI metadata, recent events, execution runs, changed files, and recovery actions.

Packet 024 added Git Explorer as a read-only dashboard surface for branch, clean/dirty status, recent commits, baseline tags, changed files, diff stat, and bounded redacted diff previews. Git Explorer must not perform git writes. Branch Per Packet remains Packet 025.

Packet 025 added Branch Per Packet as a supervised branch preparation helper. Its only app-level git write is `git switch -c` for a validated `factory/packet-###-safe-slug` branch from clean `main` after explicit operator confirmation. It does not commit, merge, push, reset, clean, rebase, stash, tag, delete branches, or run arbitrary checkout.

Packet 026 added the Operator Intervention Queue as the human review and decision lane. It records blockers, required review, recommended actions, and operator notes. It does not execute tasks, run packets, run Codex, retry or continue failed runs, recover automatically, perform Git actions, or start Auto-Pilot. Recovery controls remain separate.

Packet 027 added Trusted Packet Mode as a supervised trust gate. Operators may mark reviewed work packets as trusted or revoke trust with explicit confirmation and a recorded reason. Enabling Trusted Packet Mode does not execute anything, does not unlock Auto-Pilot, and does not bypass explicit operator execution. When enabled, supervised packet execution rejects packets unless `trust_status=trusted`.

Packet 033 consolidated the Factory Console into grouped operator surfaces: Command Center, Intake & Triage, Packet Preparation, Human Review, and Vault & Settings. It may show read-only summary counts and status cards, but it does not add execution behavior, Git write controls, automatic trust changes, retry/continue automation, or Auto-Pilot behavior.

## Recovery Flow

When a run fails:

1. Inspect the failed run details.
2. Read stdout, stderr, changed files, and related events.
3. Add an operator note.
4. Mark review required, retry one task in `one_task`, or continue one packet in `one_packet`.
5. Verify and record outcomes as factory events.

## Preflight And CI

Run local preflight before merge:

```bash
python3 scripts/nexus_preflight.py --quick
```

For packet-aware local checks, run:

```bash
python3 scripts/nexus_preflight.py --packet 34 --report /tmp/nexus-preflight-packet-034.md
```

Packet-aware preflight discovers strict packet verifier scripts under `scripts/`, runs local checks with bounded output, and can write a redacted operator report. It is checks/reporting only: it does not execute packets, run Codex, call app execution routes, auto-fix files, write Git state, trust packets, replace human review, bypass readiness, or start Auto-Pilot.

GitHub Actions runs quick strict preflight on push and pull request to `main`.

## Git And Tag Baseline Practice

Use a packet branch, verify locally, commit, fast-forward merge to `main`, verify again, tag a baseline, and push `main` plus the tag.

The dashboard Git Explorer is read-only. Operator/Codex may still perform routine git operations outside the app according to the packet workflow, but the app must not expose commit, merge, branch, tag, push, pull, fetch, reset, clean, rebase, stash, or checkout actions.

Branch Per Packet is the narrow exception for app-level git writes. It may prepare one validated packet branch at a time after clean-worktree checks. Codex operator workflow may still perform verified commit, fast-forward merge, baseline tag, and push outside the app.

The Operator Intervention Queue is record keeping only. It may create, acknowledge, resolve, dismiss, and update intervention records. It must not become a hidden execution, recovery, or Git write path.

Operator Review History is consolidated audit visibility only. It may append review events and manual notes, but it must not replace inbox conversion, readiness, trust, intervention, recovery, or draft records, and it must not become a hidden execution, trust, recovery, or Git write path.

Trusted Packet Mode is restrictive only. It may update packet trust metadata and settings, and it may block supervised packet execution for untrusted packets. It must not add autonomous execution, direct Codex execution, retry/continue automation, or Git write controls.

Factory Console Consolidation is navigation/visibility only. It may summarize existing supervised surfaces, but it must not add new run controls, new Git write controls, trust auto-marking, retry/continue automation, or Auto-Pilot unlocks.

## Sprint 3 Direction Lock

Sprint 3 focuses on supervised workflow quality: inbox conversion, packet drafting, readiness checks, review history, console consolidation, packet-aware preflight, capture hardening, and operator runbooks.

Sprint 3 must preserve explicit execution. No Sprint 3 packet should start Auto-Pilot, make Discord execute directly, make Git Explorer write to the repo, broaden app-level Git writes beyond Branch Per Packet, automate recovery, or bypass Trusted Packet Mode without explicit approval.

Packet-aware preflight does not replace the locked workflow. Human review, readiness checks, trusted packet decisions, supervised execution, recovery review, baseline tagging, and push remain explicit operator steps.

## Sprint 4 Direction Lock

Sprint 3 is complete at Packet 036. Sprint 4 is locked in `docs/SPRINT_4_PLAN.md` and focuses on production hardening, operator observability, workflow integrity, verification maturity, and onboarding quality.

Packet 037 is planning-only. It does not add runtime behavior, execution behavior, Git write behavior, retry or continue automation, trust automation, direct Discord execution, or Auto-Pilot behavior.

Sprint 4 must preserve the same supervised boundaries:

- Auto-Pilot remains locked.
- Discord remains capture-only.
- Git Explorer remains read-only.
- Branch Per Packet remains narrow.
- Trusted Packet Mode remains restrictive only.
- Operator Intervention Queue remains manual decision tracking.
- Operator Review History remains audit-only.
- Packet-aware preflight remains checks and reporting only.
- Execution remains supervised and explicit.

Packet 038 adds the Mobile Operator Notification Bridge. It may send outbound Discord alerts to the operator's phone when Nexus needs attention, but it is notification-only. Discord notifications must never include raw secrets, webhook URLs, full stdout/stderr, or execution controls, and they must not allow Discord to execute Codex, tasks, packets, Git actions, trust changes, retry/continue behavior, or Auto-Pilot.

Packet 039 adds the Server-Side Codex Job Runner. It is a local operator CLI reliability utility only. It keeps long Codex work detached from fragile SSH clients and writes status/logs under `/tmp/nexus-codex-jobs`, while preserving the app/API, Discord, Auto-Pilot, packet execution, task execution, and Git-write boundaries.

The recommended next packet is Packet 040 -- Simple Operator Flow. It should resume operator flow work only after using a server-side job runner or `tmux` for long Codex sessions.

## Safety Rules

- no force push.
- No `git reset` or `git clean` unless explicitly requested.
- No destructive DB operations.
- No raw secrets in UI, logs, prompts, reports, or events.
- No Auto-Pilot unless explicitly building or testing it.
- No execution routes unless the packet explicitly permits them.
- No raw phone SSH foreground for long Codex jobs; use `scripts/nexus_codex_job.py` or `tmux`.

## Operator Rule

Codex should do routine operator tasks: repo checks, implementation, verification, commit, merge, tag, push, and `/tmp` reports. The human should approve major or risky direction and intervene on blockers.

## Runbooks

Use the runbooks for repeatable operation:

- `docs/OPERATOR_RUNBOOK.md` for daily supervised factory operation and new-chat handoff.
- `docs/DEPLOYMENT_RUNBOOK.md` for environment, schema sync, verification, CI, baseline tagging, and safe rollback guidance.
- `docs/RECOVERY_RUNBOOK.md` for failed run inspection, review-required handling, intervention history, and recovery verification.

These runbooks are documentation only. They do not add runtime execution behavior, Git write controls, retry/continue automation, trust automation, direct Discord execution, or Auto-Pilot behavior.
