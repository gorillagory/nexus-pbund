# Nexus Deployment Runbook

This runbook keeps deployment and verification aligned with the supervised factory workflow. It does not introduce runtime behavior.

## Environment Overview

Nexus runs locally from the repository with Python services, static dashboard assets, SQLAlchemy models, local/CI preflight scripts, and optional Discord capture settings.

Required environment examples are in `.env.example`:

```bash
GEMINI_API_KEY=your_gemini_api_key_here
OPENAI_API_KEY=your_openai_api_key_here
DISCORD_ROUTER_ENABLED=false
DISCORD_INGEST_SECRET=replace_me
DISCORD_SIGNATURE_REQUIRED=false
DISCORD_ALLOWED_GUILD_IDS=
DISCORD_ALLOWED_CHANNEL_IDS=
DISCORD_ALLOWED_AUTHOR_IDS=
DISCORD_TIMESTAMP_TOLERANCE_SECONDS=0
DISCORD_REPLAY_GUARD_ENABLED=true
```

Never commit real secret values. Public settings, dashboard status, reports, and audit events must show configured/not configured or counts only.

## Discord Capture Notes

- Discord remains capture-only.
- `DISCORD_INGEST_SECRET` is required when the router is enabled.
- `DISCORD_SIGNATURE_REQUIRED=true` requires HMAC SHA-256 signatures over the raw request body.
- Allowlist variables restrict guild, channel, and author IDs.
- Timestamp tolerance rejects stale payloads when timestamps are present.
- Replay guard rejects duplicate accepted event IDs.
- Discord cannot execute Codex, tasks, packets, Git actions, trust changes, retry/continue behavior, or Auto-Pilot.

## Schema Sync

Run schema sync after pulling a deployment that adds tables or columns:

```bash
python3 scripts/sync_factory_schema.py
```

The sync is additive. Do not run destructive database operations without explicit approval.

## Static Assets

Dashboard assets are served from `templates/` and `static/`. When changed, verify syntax:

```bash
node --check static/js/app.js
node --check static/js/settings.js
```

## Health And Verification

Before deployment or baseline tagging:

```bash
git status --short
python3 -m py_compile dashboard.py engine.py models.py scripts/nexus_preflight.py
python3 scripts/nexus_preflight.py --quick
python3 scripts/nexus_preflight.py --packet 36 --report /tmp/nexus-preflight-packet-036.md
python3 scripts/verify_factory_regression_suite.py
git diff --check
```

CI should run quick strict preflight on push and pull request to `main`.

## Baseline Tag And Push

After verification:

```bash
git switch main
git merge --ff-only factory/packet-###-safe-slug
git tag nexus-<baseline-name>-2026-05-30
git push origin main
git push origin nexus-<baseline-name>-2026-05-30
```

Do not force push. Do not use `git reset` or `git clean` as normal rollback.

## Safe Rollback Guidance

If a deployment is bad:

1. Stop and preserve logs, reports, and git status.
2. Identify the last known baseline tag.
3. Create a new corrective packet branch from an approved ref.
4. Apply a forward fix or explicit revert commit after operator approval.
5. Run quick and packet-aware preflight.
6. Fast-forward merge, tag, and push.

`git reset`, `git clean`, destructive database changes, and force push require explicit approval.

## Deployment Checklist

- Repo branch and status inspected.
- Environment variables configured without raw secret exposure.
- Schema sync run if models changed.
- Static asset syntax checked if JS changed.
- Local quick preflight passed.
- Packet-aware preflight report written when relevant.
- Regression suite passed.
- Baseline tag created and pushed.
- `docs/CHAT_HANDOFF.md` updated when baseline changes.
