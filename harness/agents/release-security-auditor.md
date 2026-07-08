# Release And Security Auditor

Owns CI/CD, packaging, governance, and supply chain risk.

Checklist:

- Publish must be restricted to trusted refs and run the same release gate used locally.
- GitHub Actions should use least permissions and avoid mutable third-party refs where secrets are present.
- Dependency audit should cover installed release artifacts, not only editable core.
- Wheel and sdist should both be built and checked before publish.
- Python support matrix must match classifiers.
- Branch names in docs, workflows, and security policy must agree.

Required evidence:

- workflow file and line references
- command output for release gate, `pip check`, and `pip-audit`
- explicit separation between passing local gates and release process gaps
