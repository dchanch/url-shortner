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
            WorkflowStep("release", depends_on=["requirements"], approval_required=True, description="Release gate"),
        ]
    )

    try:
        workflow.run(human_approval=False)
        assert False, "Expected approval to be required"
    except RuntimeError as exc:
        assert "Approval required" in str(exc)
