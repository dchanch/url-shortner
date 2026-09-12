# Final Engineering Summary

## Plan and rationale

The prototype was decomposed into two cooperating layers:

1. **Product layer** — a small, real URL shortener (FastAPI + SQLite) covering
   creation, redirect, analytics, health, rate limiting, and request tracing. This
   exists so the orchestration layer has genuine work to coordinate rather than
   simulated stages.
2. **Orchestration layer** (`app/orchestration.py`, `app/scenarios.py`) — the
   assignment's "critical differentiator." Rather than a linear script that calls
   functions in order, it is a dependency graph executor with explicit governance
   primitives: entry/exit gates, wave-based parallel execution with a
   synchronization barrier, bounded retry, fallback, rollback, safe-stop/resume,
   pluggable policy guardrails, an append-only audit log, reliability metrics, and
   mid-flight re-planning that preserves decision lineage.

Design priority order was: (1) correctness and safety of the orchestration
primitives (rollback/fallback/safe-stop must never silently corrupt state or crash
the process), (2) fidelity to the assignment's explicit governance list, (3)
realism — every scenario calls the real service layer instead of returning canned
data, so validation stages can actually fail.

## Artifacts produced

- Working prototype: [`main.py`](../main.py), [`app/`](../app)
- Orchestration engine: [`app/orchestration.py`](../app/orchestration.py)
- Three runnable scenarios: [`app/scenarios.py`](../app/scenarios.py)
- API/schema definition: [`docs/openapi.json`](openapi.json) (exported from the live FastAPI app)
- Architecture overview: [`docs/architecture.md`](architecture.md)
- Scenario walkthroughs: [`docs/scenarios.md`](scenarios.md)
- Tests: [`tests/test_app.py`](../tests/test_app.py) (API + orchestration primitives),
  [`tests/test_scenarios.py`](../tests/test_scenarios.py) (end-to-end scenarios)
- Setup instructions and API summary: [`README.md`](../README.md)

## Risks, trade-offs, and validation performed

- **In-process orchestration only.** Parallel execution uses a thread pool within a
  single process; there is no distributed scheduler, durable job queue, or
  cross-process state store. State lives in the `WorkflowExecutionGraph` instance,
  so a process restart loses in-flight (not-yet-completed) workflow state. A
  production version would persist `steps`/`context`/`audit_log` to durable storage
  keyed by a workflow-run id.
- **Rollback is best-effort and application-defined.** The engine guarantees
  rollback handlers are *invoked* in reverse order with the shared context, but it
  cannot guarantee arbitrary side effects are truly undoable — that correctness is
  the responsibility of each `rollback` handler the caller supplies. Validated via
  `test_workflow_rolls_back_completed_steps_on_unrecoverable_failure` and
  `test_brownfield_scenario_rolls_back_on_regression_failure`.
- **Policy guardrails are a pluggable list, not a policy engine.** Only one baseline
  guardrail ships (critical stages must require approval); a real deployment would
  integrate an actual policy/compliance service (e.g. OPA) rather than in-process
  Python callables. Validated via `test_default_policy_guardrail_blocks_critical_steps_without_approval`.
- **Metrics are per-run, in-memory, and not exported.** `get_metrics()` computes
  success rate, retry/rollback counts, MTTR, and end-to-end latency for a single
  `WorkflowExecutionGraph` instance; there is no aggregation across runs or export to
  a metrics backend (e.g. Prometheus). Validated via `test_workflow_reports_reliability_metrics`.
- **SQLite and the in-memory rate limiter are single-process.** Documented in
  [README.md](../README.md#risks-trade-offs-and-limitations); unchanged by this work.
- **Ambiguity handling depends on the caller supplying `clarification` via
  `provide_context`.** The engine cannot resolve ambiguity itself — it only
  guarantees the workflow cannot silently proceed past an unresolved entry gate.
  Validated via `test_workflow_entry_gate_blocks_until_clarification_provided` and
  `test_ambiguous_scenario_blocks_until_clarified_then_reruns`.

## Assumptions

- "Human approval" is modeled as a boolean flag passed to `run()`; a real system
  would tie this to an actual identity-verified approval action (e.g. a reviewed PR
  merge or a ticketing system webhook).
- 307 (temporary) redirects are used so link updates remain effective without client
  caching; this was called out in the README as a resolved ambiguity for the
  greenfield/original scope.
- The assignment's "MTTR" is interpreted at the workflow-step level (time between a
  step's first failure and its eventual successful completion), since there is no
  running production system with independent incident timestamps to measure against.

## Limitations

- No UI; interaction is via HTTP API, pytest, and direct Python calls into
  `app/scenarios.py`.
- No multi-agent negotiation, distributed tracing backend, or SIEM integration —
  explicitly out of scope for a prototype, as stated in the README.
- Approval, guardrail, and metrics primitives are demonstrated with realistic but
  synthetic stage logic (e.g. a simulated migration timeout in the brownfield
  scenario) rather than wired to a real CI/CD system.
