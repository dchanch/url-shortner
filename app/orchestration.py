from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class WorkflowStep:
    name: str
    depends_on: list[str] = field(default_factory=list)
    approval_required: bool = False
    retries: int = 2
    description: str = ""
    status: str = "pending"
    output: dict[str, Any] = field(default_factory=dict)


class WorkflowExecutionGraph:
    """A dependency-driven workflow runner that models agentic execution gates."""

    def __init__(self, steps: list[WorkflowStep]):
        self.steps = {step.name: step for step in steps}
        self.audit_log: list[dict[str, Any]] = []
        self._validate_graph()

    def _validate_graph(self) -> None:
        for step in self.steps.values():
            unknown = [dep for dep in step.depends_on if dep not in self.steps]
            if unknown:
                raise ValueError(f"Step '{step.name}' depends on undefined steps: {unknown}")
        self._detect_cycles()

    def _detect_cycles(self) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def dfs(node: str) -> None:
            if node in visiting:
                raise ValueError(f"Dependency cycle detected while processing '{node}'")
            if node in visited:
                return
            visiting.add(node)
            for dep in self.steps[node].depends_on:
                dfs(dep)
            visiting.remove(node)
            visited.add(node)

        for name in self.steps:
            dfs(name)

    def run(self, human_approval: bool = False, task_runner: Optional[Callable[[str, WorkflowStep], dict[str, Any]]] = None) -> dict[str, Any]:
        if task_runner is None:
            task_runner = self._default_task_runner

        remaining = set(self.steps)
        completed: set[str] = set()
        execution_order: list[str] = []

        while remaining:
            ready = [
                name
                for name in remaining
                if all(dep in completed for dep in self.steps[name].depends_on)
            ]
            if not ready:
                pending = sorted(remaining)
                raise RuntimeError(f"Workflow is blocked; pending steps: {pending}")

            for name in sorted(ready):
                step = self.steps[name]
                if step.approval_required and not human_approval:
                    step.status = "blocked"
                    self.audit_log.append({
                        "stage": name,
                        "status": "blocked",
                        "reason": "human approval required",
                    })
                    raise RuntimeError(f"Approval required before continuing '{name}'")

                attempts = 0
                succeeded = False
                while attempts <= step.retries:
                    try:
                        step.output = task_runner(name, step)
                        step.status = "completed"
                        self.audit_log.append({
                            "stage": name,
                            "status": "completed",
                            "attempt": attempts + 1,
                            "output": step.output,
                        })
                        completed.add(name)
                        execution_order.append(name)
                        remaining.remove(name)
                        succeeded = True
                        break
                    except Exception as exc:  # pragma: no cover - defensive branch
                        attempts += 1
                        self.audit_log.append({
                            "stage": name,
                            "status": "retrying",
                            "attempt": attempts,
                            "error": str(exc),
                        })
                        if attempts > step.retries:
                            step.status = "failed"
                            self.audit_log.append({
                                "stage": name,
                                "status": "failed",
                                "error": str(exc),
                            })
                            raise RuntimeError(f"Step '{name}' failed after retries") from exc

                if not succeeded:
                    break

        return {
            "status": "completed",
            "completed_steps": execution_order,
            "audit_log": self.audit_log,
        }

    @staticmethod
    def _default_task_runner(step_name: str, step: WorkflowStep) -> dict[str, Any]:
        return {
            "stage": step_name,
            "description": step.description,
            "status": "ok",
        }
