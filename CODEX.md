# LumenAI SDK Codex Context

This clone is prepared for audit work under `harness/`.

Fast paths:

- Run the audit harness: `.\harness\scripts\run-audit.ps1`
- Run the full release-grade harness: `.\harness\scripts\run-audit.ps1 -Full`
- Open the dashboard: `harness\dashboard\index.html`
- Read the project context: `harness\context\project-context.md`
- Use project agent roles from `harness\agents\`
- Use the local skill from `harness\skills\lumen-ai-audit\SKILL.md`
- Configure MCP from `harness\mcp\lumen-audit.mcp.json`

Current environment note:

- On this machine, the PATH `python.exe` can resolve to the Microsoft Store alias.
- Prefer `.venv\Scripts\python.exe`; otherwise use the Python 3.12 executable under `%LOCALAPPDATA%\Programs\Python\Python312\python.exe`.
- The repo base branch is `LumenAI`.
