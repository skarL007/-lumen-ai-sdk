# Docs And Adoption Auditor

Owns README, examples, package READMEs, demo runnability, and adopter experience.

Checklist:

- Quickstarts must install the audited release or clearly pin a git SHA/local checkout.
- Examples that promise automatic tracking must actually activate instrumentation.
- Examples should use public API only.
- Tenant examples must use the same tenant path that the instrumentor reads.
- No-key local demo should remain the fastest proof path.
- Every example should be marked as runnable, snippet-only, or provider-key-required.

Required evidence:

- file and line references
- command or smoke result when an example is claimed runnable
- dashboard rows for example readiness

