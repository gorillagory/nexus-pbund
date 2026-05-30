# Nexus Sprint Plan

## Current State

Nexus is in Supervised Factory Alpha.

Completed capabilities:

- Supervised packet runner.
- Run One Task.
- Factory Console visibility.
- Recovery controls and audit notes.
- Local and CI preflight.
- No-token regression harness.
- CI status ingestion without GitHub API credentials.
- Operator UX polish.
- Packet 022 Orchestration Inbox foundation for supervised idea capture and triage.
- Packet 023 Discord Event Router foundation for authenticated Discord capture into the inbox.
- Packet 024 Git Explorer foundation for read-only repository visibility.
- Packet 025 Branch Per Packet foundation for supervised packet branch preparation.
- Packet 026 Operator Intervention Queue foundation for human review and decision tracking.
- Packet 027 Trusted Packet Mode foundation for reviewed packet trust metadata and restrictive execution gating.

## Sprint 2 Goal

Remote-operable supervised factory. The operator should be able to capture intent, select a trusted prompt, stage work, supervise one task or one packet, recover from failures, and understand state from the dashboard.

## Recommended Packet Roadmap

1. Prompt Vault. Complete.
2. Orchestration Inbox. Complete as Packet 022 foundation.
3. Discord Event Router. Complete as Packet 023 foundation.
4. Git Explorer. Complete as Packet 024 foundation.
5. Branch Per Packet. Complete as Packet 025 foundation.
6. Operator Intervention Queue. Complete as Packet 026 foundation.
7. Trusted Packet Mode. Complete as Packet 027 foundation.

Inbox capture rule: raw ideas are captured first, then triaged into a scoped task, work packet, document update, or explicit discard. The inbox must not execute work.

Discord router rule: Discord-originated intent is accepted only through the capture router, stored as source `discord`, and then triaged in the Orchestration Inbox. Discord must not directly start Codex, tasks, packets, or Auto-Pilot.

Git Explorer rule: dashboard Git inspection is read-only. It may show branch, status, commits, baseline tags, changed files, diff stat, and bounded redacted diff previews. It must not expose git write actions. Branch Per Packet remains Packet 025.

Branch Per Packet rule: the app may only prepare a validated `factory/packet-###-safe-slug` branch from clean `main` after explicit operator confirmation. It must not commit, merge, push, pull, fetch, reset, clean, rebase, stash, tag, delete branches, or expose arbitrary checkout.

Operator Intervention Queue rule: the queue records human review items, blockers, recommended actions, and operator notes. It may acknowledge, resolve, dismiss, and update queue records only. It must not execute tasks, run packets, run Codex, retry or continue failed runs, recover automatically, perform Git actions, or start Auto-Pilot.

Trusted Packet Mode rule: operators may mark reviewed packets trusted or revoke trust with explicit confirmation and a recorded reason. Enabling Trusted Packet Mode does not execute automatically and does not unlock Auto-Pilot. When enabled, supervised packet execution is restricted to packets with `trust_status=trusted`.

Local configuration:

- Set `DISCORD_ROUTER_ENABLED=true` or enable Discord Router in Settings.
- Set `DISCORD_INGEST_SECRET` or save a shared ingest secret in Settings.
- Send the shared secret in `X-Nexus-Discord-Secret`, `X-Discord-Ingest-Secret`, or `Authorization: Bearer ...`.
- Never place real secret values in docs, reports, commits, UI text, or events.

Do not build full Auto-Pilot yet. Keep the system supervised, inspectable, and reversible.
