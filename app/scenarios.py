"""Runnable demonstrations of the three required scenarios (greenfield, brownfield,
ambiguous), each expressed as a real WorkflowExecutionGraph wired to the actual
UrlShortenerService rather than canned strings. Each builder returns
`(graph, task_runner)`; call `graph.run(task_runner=task_runner, ...)` to execute.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from app.orchestration import WorkflowExecutionGraph, WorkflowStep
from app.services.url_shortener_service import UrlShortenerService

StageRunner = Callable[[str, WorkflowStep, dict[str, Any]], dict[str, Any]]


def _dispatch(runners: dict[str, StageRunner]) -> StageRunner:
    """Build a task_runner that routes each stage to its own handler, falling back
    to a no-op success for stages with no side effects (requirements/design)."""

    def runner(name: str, step: WorkflowStep, context: dict[str, Any]) -> dict[str, Any]:
        handler = runners.get(name)
        if handler is None:
            return {"stage": name, "description": step.description, "status": "ok"}
        return handler(name, step, context)

    return runner


# ---------------------------------------------------------------------------
# Scenario 1: Greenfield - build the shortener core from scratch
# ---------------------------------------------------------------------------
def build_greenfield_workflow(
    service: Optional[UrlShortenerService] = None,
) -> tuple[WorkflowExecutionGraph, StageRunner]:
    service = service or UrlShortenerService()

    def implementation(name: str, step: WorkflowStep, context: dict[str, Any]) -> dict[str, Any]:
        record = service.create_link("https://example.com/greenfield-demo")
        return {"short_code": record["short_code"], "short_url": record["short_url"]}

    def validation(name: str, step: WorkflowStep, context: dict[str, Any]) -> dict[str, Any]:
        impl = context["implementation"]
        if service.get_link(impl["short_code"]) is None:
            raise RuntimeError("Created link could not be retrieved during validation.")
        resolved = service.resolve_link(impl["short_code"])
        if resolved is None or resolved["click_count"] < 1:
            raise RuntimeError("Redirect did not register a click during validation.")
        return {"verified": True, "click_count": resolved["click_count"]}

    steps = [
        WorkflowStep(
            "requirements",
            description="Shorten URLs, redirect with click tracking, expose analytics.",
        ),
        WorkflowStep(
            "design",
            depends_on=["requirements"],
            description="REST API surface, SQLite schema, rate limiting, request tracing.",
        ),
        WorkflowStep(
            "implementation",
            depends_on=["design"],
            description="Create a link end-to-end through the service layer.",
        ),
        WorkflowStep(
            "validation",
            depends_on=["implementation"],
            description="Verify persistence, redirect behavior, and click tracking.",
        ),
        WorkflowStep(
            "release",
            depends_on=["validation"],
            approval_required=True,
            critical=True,
            description="Release readiness gate for a new public API surface.",
        ),
    ]
    graph = WorkflowExecutionGraph(steps)
    return graph, _dispatch({"implementation": implementation, "validation": validation})


# ---------------------------------------------------------------------------
# Scenario 2: Brownfield - add link expiration to the existing shortener
# ---------------------------------------------------------------------------
def build_brownfield_workflow(
    service: Optional[UrlShortenerService] = None,
    *,
    force_regression_failure: bool = False,
) -> tuple[WorkflowExecutionGraph, StageRunner]:
    """Models enhancing the existing system with link expiration. The first
    implementation attempt fails (simulated migration timeout) to exercise bounded
    retries; setting `force_regression_failure=True` exercises the rollback path."""
    service = service or UrlShortenerService()
    attempts = {"count": 0}

    def impact_analysis(name: str, step: WorkflowStep, context: dict[str, Any]) -> dict[str, Any]:
        return {
            "impacted_modules": [
                "app/api/routes.py",
                "app/services/url_shortener_service.py",
                "app/repositories/links.py",
                "app/db.py",
            ],
            "change": "Add an optional expires_at column to support time-boxed short links.",
        }

    def implementation(name: str, step: WorkflowStep, context: dict[str, Any]) -> dict[str, Any]:
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise RuntimeError("Schema migration timed out applying 'expires_at' column.")
        record = service.create_link("https://example.com/brownfield-demo")
        return {"short_code": record["short_code"], "migration_attempt": attempts["count"]}

    def implementation_rollback(name: str, step: WorkflowStep, context: dict[str, Any]) -> None:
        # Compensating action: the demo link created by the rolled-out change is not
        # promoted; a real migration rollback would drop the added column here.
        return None

    def regression_tests(name: str, step: WorkflowStep, context: dict[str, Any]) -> dict[str, Any]:
        if force_regression_failure:
            raise RuntimeError("Regression suite detected redirects ignoring link expiry.")
        impl = context["implementation"]
        if service.get_link(impl["short_code"]) is None:
            raise RuntimeError("Link created during implementation is missing.")
        return {"regression_status": "passed"}

    steps = [
        WorkflowStep(
            "impact_analysis",
            description="Identify impacted modules/services/data flows for the new feature.",
        ),
        WorkflowStep(
            "design",
            depends_on=["impact_analysis"],
            description="Add nullable expires_at column; redirect path checks expiry.",
        ),
        WorkflowStep(
            "implementation",
            depends_on=["design"],
            description="Apply schema change and implement expiry check.",
            retries=2,
            rollback=implementation_rollback,
        ),
        WorkflowStep(
            "regression_tests",
            depends_on=["implementation"],
            description="Run regression suite against existing redirect/analytics behavior.",
            retries=0,
        ),
        WorkflowStep(
            "release",
            depends_on=["regression_tests"],
            approval_required=True,
            critical=True,
            description="Release readiness gate for a change to existing redirect behavior.",
        ),
    ]
    graph = WorkflowExecutionGraph(steps)
    return graph, _dispatch(
        {
            "impact_analysis": impact_analysis,
            "implementation": implementation,
            "regression_tests": regression_tests,
        }
    )


# ---------------------------------------------------------------------------
# Scenario 3: Ambiguous - custom slug case sensitivity + analytics retention
# ---------------------------------------------------------------------------
def build_ambiguous_workflow(
    service: Optional[UrlShortenerService] = None,
    *,
    clarification: Optional[dict[str, Any]] = None,
) -> tuple[WorkflowExecutionGraph, StageRunner]:
    """Models an underspecified requirement: should custom slugs be case-sensitive,
    and what is the analytics retention window? The 'design' stage's entry gate
    blocks progress (safe-stop) until both decisions are supplied via
    `graph.provide_context('clarification', {...})`."""
    service = service or UrlShortenerService()
    required_decisions = {"custom_slug_case_sensitive", "analytics_retention_days"}

    def design_entry_gate(name: str, step: WorkflowStep, context: dict[str, Any]) -> Optional[str]:
        clarified = context.get("clarification", {})
        missing = required_decisions - clarified.keys()
        if missing:
            return f"Ambiguous requirement: need a product decision on {sorted(missing)}."
        return None

    def design(name: str, step: WorkflowStep, context: dict[str, Any]) -> dict[str, Any]:
        return dict(context["clarification"])

    def implementation(name: str, step: WorkflowStep, context: dict[str, Any]) -> dict[str, Any]:
        record = service.create_link("https://example.com/ambiguous-demo")
        return {"short_code": record["short_code"], "decisions_applied": context["design"]}

    def validation(name: str, step: WorkflowStep, context: dict[str, Any]) -> dict[str, Any]:
        impl = context["implementation"]
        if service.get_link(impl["short_code"]) is None:
            raise RuntimeError("Implementation output could not be validated.")
        return {"verified": True}

    steps = [
        WorkflowStep(
            "requirements",
            description="Normalize ambiguous ask into explicit open decisions requiring clarification.",
        ),
        WorkflowStep(
            "design",
            depends_on=["requirements"],
            entry_gate=design_entry_gate,
            description="Resolve ambiguity into a concrete, testable design decision.",
        ),
        WorkflowStep(
            "implementation",
            depends_on=["design"],
            description="Implement per the clarified decision.",
        ),
        WorkflowStep(
            "validation",
            depends_on=["implementation"],
            description="Verify implementation matches the clarified decision.",
        ),
        WorkflowStep(
            "release",
            depends_on=["validation"],
            approval_required=True,
            critical=True,
            description="Release readiness gate.",
        ),
    ]
    graph = WorkflowExecutionGraph(steps, initial_context={"clarification": clarification or {}})
    return graph, _dispatch({"design": design, "implementation": implementation, "validation": validation})
