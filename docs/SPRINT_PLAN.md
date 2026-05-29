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

## Sprint 2 Goal

Remote-operable supervised factory. The operator should be able to capture intent, select a trusted prompt, stage work, supervise one task or one packet, recover from failures, and understand state from the dashboard.

## Recommended Packet Roadmap

1. Prompt Vault. Complete.
2. Orchestration Inbox. Complete as Packet 022 foundation.
3. Discord Event Router. Complete as Packet 023 foundation.
4. Git Explorer.
5. Branch Per Packet.
6. Operator Intervention Queue.
7. Trusted Packet Mode.

Inbox capture rule: raw ideas are captured first, then triaged into a scoped task, work packet, document update, or explicit discard. The inbox must not execute work.

Discord router rule: Discord-originated intent is accepted only through the capture router, stored as source `discord`, and then triaged in the Orchestration Inbox. Discord must not directly start Codex, tasks, packets, or Auto-Pilot.

Local configuration:

- Set `DISCORD_ROUTER_ENABLED=true` or enable Discord Router in Settings.
- Set `DISCORD_INGEST_SECRET` or save a shared ingest secret in Settings.
- Send the shared secret in `X-Nexus-Discord-Secret`, `X-Discord-Ingest-Secret`, or `Authorization: Bearer ...`.
- Never place real secret values in docs, reports, commits, UI text, or events.

Do not build full Auto-Pilot yet. Keep the system supervised, inspectable, and reversible.
