# Scenario Walkthroughs

Each scenario below is a real, runnable `WorkflowExecutionGraph` (see
[`app/scenarios.py`](../app/scenarios.py)) wired to the actual `UrlShortenerService` —
none of these outputs are canned. Executable proof is in
[`tests/test_scenarios.py`](../tests/test_scenarios.py).

## 1. Greenfield: build the shortener core

**Requirement (as given):** "Build a URL shortener service from scratch with core
APIs, analytics, and reliability features."

**Decomposition** (`build_greenfield_workflow`):

| Stage            | Depends on     | Notes                                                                           |
| ---------------- | -------------- | ------------------------------------------------------------------------------- |
| `requirements`   | —              | Normalize the ask: shorten URLs, redirect with click tracking, expose analytics |
| `design`         | requirements   | REST surface, SQLite schema, rate limiting, request tracing                     |
| `implementation` | design         | Calls `UrlShortenerService.create_link` for real                                |
| `validation`     | implementation | Re-reads the link, redirects it, asserts the click counter incremented          |
| `release`        | validation     | `approval_required=True`, `critical=True` — human sign-off gate                 |

**Orchestration:** stages run strictly in sequence (each depends on the previous),
demonstrating the simplest legal path through the dependency graph. `release` is
critical and approval-gated, so the first `graph.run()` call safe-stops with
`status="awaiting_approval"` after completing `validation`; a second call with
`human_approval=True` resumes and completes without re-running prior stages.

**Validation:** the `validation` stage is a real functional check (retrieve the
persisted link, hit the redirect path, confirm the click counter moved), not a stub.

## 2. Brownfield: add link expiration to the existing shortener

**Requirement (as given):** "enhancements, refactors, bug fixes" to an existing
system.

**Codebase reasoning:** the `impact_analysis` stage enumerates the real modules
touched by adding link expiration: `app/api/routes.py`, `app/services/url_shortener_service.py`,
`app/repositories/links.py`, and `app/db.py` (schema).

**Decomposition:** `impact_analysis → design → implementation → regression_tests → release`.

**Orchestration and failure handling:**

- `implementation` simulates a first-attempt migration timeout, then succeeds on
  retry — exercising the bounded-retry control (`retries=2`) with a real
  attempt counter surfaced in `graph.steps["implementation"].attempts` and in
  `metrics.retry_count`.
- Calling `build_brownfield_workflow(force_regression_failure=True)` makes
  `regression_tests` fail with zero retries. Because there's no fallback for that
  stage, the graph triggers **rollback**: the `implementation` stage's rollback
  handler runs, `implementation.status` becomes `rolled_back`, and the run result is
  `status="rolled_back"` with `metrics.rollback_count == 1`. This demonstrates
  compensating-action rollback, not just a failed run.

**Validation:** `regression_tests` re-reads the link created during `implementation`
to confirm the enhancement didn't break existing read paths.

## 3. Ambiguous: custom slug case sensitivity + analytics retention

**Requirement (as given, deliberately underspecified):** "should custom slugs be
case-sensitive, and how long should analytics be retained?" — the assignment brief
never states this, so the system must not guess silently.

**Decomposition:** `requirements → design → implementation → validation → release`.

**Orchestration:** the `design` stage has an `entry_gate` that checks whether both
open decisions (`custom_slug_case_sensitive`, `analytics_retention_days`) are present
in the shared context. Calling `graph.run()` before either decision is supplied
safe-stops with `status="blocked"` and `pending_steps=["design"]` — the workflow
never proceeds past an ambiguous requirement.

A human/product-owner decision is then recorded explicitly and auditably:

```python
graph.provide_context(
    "clarification",
    {"custom_slug_case_sensitive": True, "analytics_retention_days": 90},
    reason="product owner clarified open questions",
)
graph.run(human_approval=True, task_runner=task_runner)  # now completes
```

This is logged in `graph.audit_log` as a `context_updated` entry with the reason,
giving a durable decision-lineage record of _why_ the ambiguity was resolved the way
it was — distinct from a normal approval gate.

**Re-planning:** if, after clarification, a new dependent obligation appears (e.g. a
scheduled purge job for the retention window), it can be added mid-flight without
disturbing already-completed stages:

```python
graph.replan(
    [WorkflowStep("retention_purge_job", depends_on=["design"], description="Schedule purge job")],
    reason="analytics retention window was clarified after design completed",
)
```

`replan()` refuses to touch steps that already completed, so earlier decision
lineage in `graph.context` is untouched (see
`test_workflow_replan_adds_steps_while_preserving_completed_lineage` in
[`tests/test_app.py`](../tests/test_app.py)).
