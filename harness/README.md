# LumenAI Audit Harness

This harness turns the LumenAI SDK clone into a repeatable audit workspace.

It provides:

- executable validation gates for tests, lint, typing, dependency health, release gate, and focused probes
- a consolidated dashboard at `harness/dashboard/index.html`
- reusable Codex context, agent role files, a local skill, and an MCP stdio server config
- generated evidence in `harness/reports/audit-data.json`

## Commands

```powershell
# Fast audit: tests, ruff, mypy, pip check, pip-audit, probes, dashboard
.\harness\scripts\run-audit.ps1

# Full audit: includes scripts/release_gate.py
.\harness\scripts\run-audit.ps1 -Full
```

## Layout

- `context/`: concise project map and audit operating rules.
- `agents/`: role prompts for specialized audit passes.
- `skills/lumen-ai-audit/`: local Codex skill for future LumenAI audit runs.
- `mcp/`: stdio MCP server and config exposing context, findings, and report data.
- `probes/`: focused repro scripts for runtime edge cases.
- `scripts/`: audit collection and dashboard generation.
- `reports/`: generated JSON and screenshot output.
- `dashboard/`: generated visual dashboard.

## Scope

The harness captures the current risk profile and makes future fixes measurable.

## Remote CI Note

When GitHub Actions runners are unavailable, the full local harness is the
temporary release evidence. Keep the PR as draft or clearly mark the remote CI
blocker until Actions can start jobs again.
