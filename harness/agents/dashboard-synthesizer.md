# Dashboard Synthesizer

Owns the visual report.

Checklist:

- Keep the dashboard static and self-contained so `index.html` opens directly.
- Show overall score, aspect scores, gate evidence, probe results, and prioritized findings.
- Use compact tables and filters for severity/aspect.
- Distinguish passing validation from risk findings.
- Link every finding to the relevant local file path and line when known.

Required evidence:

- generated `harness/reports/audit-data.json`
- generated `harness/dashboard/index.html`
- final path to the dashboard

