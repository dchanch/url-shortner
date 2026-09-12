import pytest
from fastapi.testclient import TestClient

from app.db import reset_db
from app.api.routes import FixedWindowRateLimiter
from app.orchestration import WorkflowExecutionGraph, WorkflowStep
from main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_database():
    reset_db()
    yield
    reset_db()


def test_create_short_link_and_redirect():
    response = client.post(
        "/api/links",
        json={"long_url": "https://example.com/very/long/path"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["original_url"] == "https://example.com/very/long/path"
    assert payload["short_code"]
    assert payload["short_url"].endswith(payload["short_code"])

    redirect_response = client.get(f"/{payload['short_code']}", follow_redirects=False)
    assert redirect_response.status_code == 307
    assert redirect_response.headers["location"] == "https://example.com/very/long/path"

    analytics = client.get(f"/api/links/{payload['short_code']}/analytics")
    assert analytics.status_code == 200
    analytics_payload = analytics.json()
    assert analytics_payload["total_clicks"] >= 1


def test_custom_slug_is_enforced():
    response = client.post(
        "/api/links",
        json={"long_url": "https://example.com", "custom_slug": "abc"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["short_code"] == "abc"

    duplicate = client.post(
        "/api/links",
        json={"long_url": "https://other.example.com", "custom_slug": "abc"},
    )
    assert duplicate.status_code == 400
    assert duplicate.json()["detail"] == "The short code 'abc' is already taken."


def test_invalid_url_is_rejected_by_request_validation():
    response = client.post("/api/links", json={"long_url": "javascript:alert(1)"})
    assert response.status_code == 422


def test_request_id_is_returned_for_traceability():
    response = client.get("/health", headers={"X-Request-ID": "test-request-id"})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "test-request-id"


def test_rate_limiter_blocks_requests_in_same_window():
    limiter = FixedWindowRateLimiter(limit=1, window_seconds=60)
    assert limiter.check("test-client") is None
    assert limiter.check("test-client") is not None


def test_workflow_orchestration_dependencies():
    workflow = WorkflowExecutionGraph(
        [
            WorkflowStep("requirements", description="Capture requirements"),
            WorkflowStep("design", depends_on=["requirements"], description="Design the solution"),
            WorkflowStep("implementation", depends_on=["design"], description="Implement the build"),
            WorkflowStep("validation", depends_on=["implementation"], description="Validate the output"),
        ]
    )

    result = workflow.run()
    assert result["status"] == "completed"
    assert result["completed_steps"] == [
        "requirements",
        "design",
        "implementation",
        "validation",
    ]


def test_workflow_requires_approval_for_high_impact_task():
    workflow = WorkflowExecutionGraph(
        [
            WorkflowStep("requirements", description="Capture requirements"),
            WorkflowStep(
                "release",
                depends_on=["requirements"],
                approval_required=True,
                critical=True,
                description="Release gate",
            ),
        ]
    )

    result = workflow.run(human_approval=False)
    assert result["status"] == "awaiting_approval"
    assert result["pending_steps"] == ["release"]
    assert result["completed_steps"] == ["requirements"]

    resumed = workflow.run(human_approval=True)
    assert resumed["status"] == "completed"
    assert resumed["completed_steps"] == ["requirements", "release"]


def test_workflow_supports_fallback_when_retries_are_exhausted():
    def flaky_runner(name, step, context):
        if name == "implementation":
            raise RuntimeError("simulated failure")
        return {"stage": name, "status": "ok"}

    def implementation_fallback(name, step, context):
        return {"stage": name, "status": "degraded", "used_fallback": True}

    workflow = WorkflowExecutionGraph(
        [
            WorkflowStep("requirements", description="Capture requirements"),
            WorkflowStep(
                "implementation",
                depends_on=["requirements"],
                retries=1,
                fallback=implementation_fallback,
                description="Implement the build",
            ),
        ]
    )

    result = workflow.run(task_runner=flaky_runner)
    assert result["status"] == "completed"
    assert workflow.steps["implementation"].used_fallback is True
    assert result["metrics"]["retry_count"] == 1


def test_workflow_rolls_back_completed_steps_on_unrecoverable_failure():
    rolled_back = []

    def runner(name, step, context):
        if name == "validation":
            raise RuntimeError("validation failed with no fallback")
        return {"stage": name}

    def rollback(name, step, context):
        rolled_back.append(name)

    workflow = WorkflowExecutionGraph(
        [
            WorkflowStep("requirements", description="Capture requirements"),
            WorkflowStep(
                "implementation",
                depends_on=["requirements"],
                rollback=rollback,
                description="Implement the build",
            ),
            WorkflowStep(
                "validation",
                depends_on=["implementation"],
                retries=0,
                description="Validate the output",
            ),
        ]
    )

    result = workflow.run(task_runner=runner)
    assert result["status"] == "rolled_back"
    assert rolled_back == ["implementation"]
    assert workflow.steps["implementation"].status == "rolled_back"
    assert result["metrics"]["rollback_count"] == 1


def test_workflow_entry_gate_blocks_until_clarification_provided():
    def gate(name, step, context):
        return None if "answer" in context else "clarification needed"

    workflow = WorkflowExecutionGraph(
        [
            WorkflowStep("requirements", description="Capture ambiguous requirement"),
            WorkflowStep(
                "design",
                depends_on=["requirements"],
                entry_gate=gate,
                description="Resolve ambiguity",
            ),
        ]
    )

    blocked = workflow.run()
    assert blocked["status"] == "blocked"
    assert blocked["pending_steps"] == ["design"]

    workflow.provide_context("answer", "case-sensitive")
    resumed = workflow.run()
    assert resumed["status"] == "completed"


def test_workflow_replan_adds_steps_while_preserving_completed_lineage():
    workflow = WorkflowExecutionGraph(
        [
            WorkflowStep("requirements", description="Capture requirements"),
            WorkflowStep("design", depends_on=["requirements"], description="Design"),
        ]
    )
    workflow.run()
    assert workflow.context["requirements"]["stage"] == "requirements"

    workflow.replan(
        [WorkflowStep("retention_policy", depends_on=["design"], description="Add retention job")],
        reason="analytics retention window was clarified after design completed",
    )
    result = workflow.run()
    assert result["status"] == "completed"
    assert "retention_policy" in result["completed_steps"]
    assert workflow.context["requirements"]["stage"] == "requirements"


def test_default_policy_guardrail_blocks_critical_steps_without_approval():
    workflow = WorkflowExecutionGraph(
        [WorkflowStep("release", critical=True, approval_required=False, description="Release")]
    )
    result = workflow.run()
    assert result["status"] == "blocked"
    assert result["pending_steps"] == ["release"]


def test_workflow_reports_reliability_metrics():
    workflow = WorkflowExecutionGraph(
        [
            WorkflowStep("requirements", description="Capture requirements"),
            WorkflowStep("design", depends_on=["requirements"], description="Design"),
        ]
    )
    result = workflow.run()
    metrics = result["metrics"]
    assert metrics["total_steps"] == 2
    assert metrics["success_rate"] == 1.0
    assert metrics["end_to_end_latency_ms"] is not None
