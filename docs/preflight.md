# Nexus Preflight

Run the no-token local checks before merging:

```bash
python3 scripts/nexus_preflight.py --quick
python3 scripts/nexus_preflight.py
python3 scripts/nexus_preflight.py --quick --strict-clean
```

GitHub Actions runs the quick strict preflight on every push and pull request.
