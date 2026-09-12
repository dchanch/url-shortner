from app.db import reset_db
from app.scenarios import (
    build_ambiguous_workflow,
    build_brownfield_workflow,
    build_greenfield_workflow,
)
from app.services.url_shortener_service import UrlShortenerService

import pytest


@pytest.fixture(autouse=True)
def reset_database():
    reset_db()
    yield
    reset_db()


def test_greenfield_scenario_runs_end_to_end_with_approval():
    service = UrlShortenerService()
    graph, task_runner = build_greenfield_workflow(service)

    pending = graph.run(task_runner=task_runner)
    assert pending["status"] == "awaiting_approval"
    assert pending["pending_steps"] == ["release"]

    completed = graph.run(human_approval=True, task_runner=task_runner)
    assert completed["status"] == "completed"
    assert completed["completed_steps"] == [
        "requirements",
        "design",
        "implementation",
        "validation",
        "release",
    ]
    assert completed["metrics"]["success_rate"] == 1.0


def test_brownfield_scenario_retries_then_succeeds():
    service = UrlShortenerService()
    graph, task_runner = build_brownfield_workflow(service)

    result = graph.run(human_approval=True, task_runner=task_runner)
    assert result["status"] == "completed"
    assert graph.steps["implementation"].attempts == 1  # one retry before success
    assert result["metrics"]["retry_count"] == 1


def test_brownfield_scenario_rolls_back_on_regression_failure():
    service = UrlShortenerService()
    graph, task_runner = build_brownfield_workflow(service, force_regression_failure=True)

    result = graph.run(human_approval=True, task_runner=task_runner)
    assert result["status"] == "rolled_back"
    assert graph.steps["implementation"].status == "rolled_back"
    assert result["metrics"]["rollback_count"] == 1


def test_ambiguous_scenario_blocks_until_clarified_then_reruns():
    service = UrlShortenerService()
    graph, task_runner = build_ambiguous_workflow(service)

    blocked = graph.run(task_runner=task_runner)
    assert blocked["status"] == "blocked"
    assert blocked["pending_steps"] == ["design"]

    graph.provide_context(
        "clarification",
        {"custom_slug_case_sensitive": True, "analytics_retention_days": 90},
        reason="product owner clarified open questions",
    )
    completed = graph.run(human_approval=True, task_runner=task_runner)
    assert completed["status"] == "completed"
    assert completed["completed_steps"][-1] == "release"
