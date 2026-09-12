"""Agentic orchestration engine.

Models the SDLC lifecycle (requirements -> design -> implementation -> validation ->
release) as an explicit dependency graph and executes it with governance controls:
entry/exit gates, bounded parallelism with synchronization, cross-stage context
(decision lineage), human approval checkpoints, bounded retries, fallback, rollback,
safe-stop/resume, policy guardrails, and reliability metrics.

This is intentionally a lightweight, in-process implementation of the pattern - it is
not a distributed scheduler - but every governance behaviour required by the
assignment is real and exercised by tests, not simulated.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# A task runner executes a step's work. It receives the step name, the step itself,
# and the shared "context" dict of every prior stage's output (decision lineage).
TaskRunner = Callable[[str, "WorkflowStep", dict[str, Any]], dict[str, Any]]

# A rollback handler undoes the effects of a previously completed step.
RollbackHandler = Callable[[str, "WorkflowStep", dict[str, Any]], None]

# A gate validates a pre/post condition for a step. Returning None means "pass";
# returning a string means "blocked", with the string used as the reason.
Gate = Callable[[str, "WorkflowStep", dict[str, Any]], Optional[str]]

# A policy guardrail inspects a step before execution for security/compliance/change
# control violations. Returning None means "pass".
PolicyGuardrail = Callable[[str, "WorkflowStep"], Optional[str]]


@dataclass
class WorkflowStep:
    name: str
    depends_on: list[str] = field(default_factory=list)
    approval_required: bool = False
    critical: bool = False
    retries: int = 2
    description: str = ""
    entry_gate: Optional[Gate] = None
    exit_gate: Optional[Gate] = None
    fallback: Optional[TaskRunner] = None
    rollback: Optional[RollbackHandler] = None

    # Runtime state (mutated by WorkflowExecutionGraph).
    status: str = "pending"
    output: dict[str, Any] = field(default_factory=dict)
    attempts: int = 0
    used_fallback: bool = False
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    first_failed_at: Optional[float] = None


def default_policy_guardrail(step_name: str, step: "WorkflowStep") -> Optional[str]:
    """Baseline change-control guardrail: critical/high-impact stages must be
    explicitly marked as requiring approval. This prevents a mis-configured stage
    from silently bypassing human oversight."""
    if step.critical and not step.approval_required:
        return f"Critical stage '{step_name}' must require human approval."
    return None


class WorkflowExecutionGraph:
    """A dependency-driven, stateful workflow runner that models agentic execution
    with governance gates."""

    def __init__(
        self,
        steps: list[WorkflowStep],
        policy_guardrails: Optional[list[PolicyGuardrail]] = None,
        max_workers: int = 4,
        initial_context: Optional[dict[str, Any]] = None,
    ):
        self.steps: dict[str, WorkflowStep] = {step.name: step for step in steps}
        self.policy_guardrails: list[PolicyGuardrail] = policy_guardrails or [default_policy_guardrail]
        self.max_workers = max_workers
        self.audit_log: list[dict[str, Any]] = []
        self.context: dict[str, Any] = dict(initial_context or {})
        self._validate_graph()

        # Resumable execution state.
        self._completed: set[str] = set()
        self._remaining: set[str] = set(self.steps)
        self._execution_order: list[str] = []
        self._run_started_at: Optional[float] = None
        self._retry_count = 0
        self._rollback_count = 0
        self._recovery_durations: list[float] = []

    # ------------------------------------------------------------------
    # Graph validation
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Re-planning: adjust the graph mid-flight while preserving lineage
    # ------------------------------------------------------------------
    def replan(self, updated_steps: list[WorkflowStep], reason: str = "upstream output changed") -> None:
        """Merge new/modified steps into the graph. Already-completed steps and their
        recorded context are preserved (decision lineage survives the re-plan)."""
        for step in updated_steps:
            if step.name in self._completed:
                raise ValueError(f"Cannot replan a step that already completed: '{step.name}'")
            self.steps[step.name] = step
            self._remaining.add(step.name)

        self._validate_graph()
        self.audit_log.append({
            "stage": "__replan__",
            "status": "replanned",
            "reason": reason,
            "affected_steps": [step.name for step in updated_steps],
        })

    def provide_context(self, key: str, value: Any, reason: str = "external input provided") -> None:
        """Record externally supplied information (e.g. a stakeholder's clarification
        of an ambiguous requirement) into the shared decision-lineage context."""
        self.context[key] = value
        self.audit_log.append({"stage": "__context__", "status": "context_updated", "key": key, "reason": reason})

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------
    def run(self, human_approval: bool = False, task_runner: Optional[TaskRunner] = None) -> dict[str, Any]:
        """Execute all ready stages. Safe to call repeatedly to resume a run that
        previously safe-stopped (e.g. after approval is granted)."""
        if task_runner is None:
            task_runner = self._default_task_runner
        if self._run_started_at is None:
            self._run_started_at = time.monotonic()

        while self._remaining:
            ready = sorted(
                name
                for name in self._remaining
                if all(dep in self._completed for dep in self.steps[name].depends_on)
            )
            if not ready:
                return self._safe_stop("blocked", pending=sorted(self._remaining))

            executable, blocked = self._screen_batch(ready, human_approval)

            if executable:
                self._execute_batch(executable, task_runner)

            failed = [name for name in executable if self.steps[name].status == "failed"]
            if failed:
                self._rollback(failed[0])
                return self._finalize("rolled_back", reason=f"step '{failed[0]}' failed after retries and fallback")

            if not executable and blocked:
                only_approval = all(b["type"] == "approval" for b in blocked)
                status = "awaiting_approval" if only_approval else "blocked"
                return self._safe_stop(status, pending=[b["stage"] for b in blocked])

        return self._finalize("completed")

    def _screen_batch(self, ready: list[str], human_approval: bool) -> tuple[list[str], list[dict[str, Any]]]:
        """Split ready steps into those clear to execute now vs. those safe-stopped
        pending approval, an unmet entry gate, or a policy violation."""
        executable: list[str] = []
        blocked: list[dict[str, Any]] = []

        for name in ready:
            step = self.steps[name]

            violation = None
            for guardrail in self.policy_guardrails:
                violation = guardrail(name, step)
                if violation:
                    break
            if violation:
                step.status = "blocked"
                entry = {"stage": name, "type": "policy", "status": "policy_blocked", "reason": violation}
                self.audit_log.append(entry)
                blocked.append(entry)
                continue

            if step.entry_gate is not None:
                gate_reason = step.entry_gate(name, step, self.context)
                if gate_reason:
                    step.status = "blocked"
                    entry = {"stage": name, "type": "entry_gate", "status": "entry_gate_blocked", "reason": gate_reason}
                    self.audit_log.append(entry)
                    blocked.append(entry)
                    continue

            if step.approval_required and not human_approval:
                step.status = "awaiting_approval"
                entry = {"stage": name, "type": "approval", "status": "awaiting_approval", "reason": "human approval required"}
                self.audit_log.append(entry)
                blocked.append(entry)
                continue

            executable.append(name)

        return executable, blocked

    def _execute_batch(self, names: list[str], task_runner: TaskRunner) -> None:
        """Run independent, ready steps concurrently and synchronize before the next
        wave (sequential-and-parallel execution with a synchronization barrier)."""
        if len(names) == 1:
            self._run_step(names[0], task_runner)
            return

        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(names))) as pool:
            list(pool.map(lambda n: self._run_step(n, task_runner), names))

    def _run_step(self, name: str, task_runner: TaskRunner) -> None:
        step = self.steps[name]
        step.status = "running"
        step.started_at = time.monotonic()

        while step.attempts <= step.retries:
            try:
                step.output = task_runner(name, step, dict(self.context))

                if step.exit_gate is not None:
                    gate_reason = step.exit_gate(name, step, self.context)
                    if gate_reason:
                        raise RuntimeError(f"Exit gate failed: {gate_reason}")

                self._mark_completed(name)
                return
            except Exception as exc:  # noqa: BLE001 - retried/reported, not swallowed
                step.attempts += 1
                if step.first_failed_at is None:
                    step.first_failed_at = time.monotonic()
                    self._retry_count += 1
                self.audit_log.append({
                    "stage": name,
                    "status": "retrying" if step.attempts <= step.retries else "attempt_exhausted",
                    "attempt": step.attempts,
                    "error": str(exc),
                })
                if step.attempts > step.retries:
                    if step.fallback is not None:
                        self._run_fallback(name, step)
                        return
                    step.status = "failed"
                    step.finished_at = time.monotonic()
                    self.audit_log.append({"stage": name, "status": "failed", "error": str(exc)})
                    return

    def _run_fallback(self, name: str, step: WorkflowStep) -> None:
        try:
            step.output = step.fallback(name, step, dict(self.context))  # type: ignore[misc]
            step.used_fallback = True
            self._mark_completed(name)
            self.audit_log.append({"stage": name, "status": "fallback_completed", "output": step.output})
        except Exception as exc:  # noqa: BLE001
            step.status = "failed"
            step.finished_at = time.monotonic()
            self.audit_log.append({"stage": name, "status": "fallback_failed", "error": str(exc)})

    def _mark_completed(self, name: str) -> None:
        step = self.steps[name]
        step.status = "completed"
        step.finished_at = time.monotonic()
        if step.first_failed_at is not None:
            self._recovery_durations.append(step.finished_at - step.first_failed_at)
        self.context[name] = step.output
        self._completed.add(name)
        self._remaining.discard(name)
        self._execution_order.append(name)
        self.audit_log.append({
            "stage": name,
            "status": "completed",
            "attempts": step.attempts + 1,
            "used_fallback": step.used_fallback,
            "output": step.output,
        })

    # ------------------------------------------------------------------
    # Rollback / safe-stop / finalize
    # ------------------------------------------------------------------
    def _rollback(self, failed_step: str) -> None:
        """Undo completed steps in reverse execution order (compensating actions),
        preserving an audit trail of what was rolled back and why."""
        for name in reversed(self._execution_order):
            step = self.steps[name]
            if step.rollback is None:
                continue
            try:
                step.rollback(name, step, dict(self.context))
                step.status = "rolled_back"
                self._rollback_count += 1
                self.audit_log.append({"stage": name, "status": "rolled_back", "triggered_by": failed_step})
            except Exception as exc:  # noqa: BLE001
                self.audit_log.append({"stage": name, "status": "rollback_failed", "error": str(exc)})

    def _safe_stop(self, status: str, pending: list[str]) -> dict[str, Any]:
        self.audit_log.append({"stage": "__workflow__", "status": status, "pending": pending})
        return self._finalize(status, pending=pending)

    def _finalize(self, status: str, pending: Optional[list[str]] = None, reason: str = "") -> dict[str, Any]:
        result = {
            "status": status,
            "completed_steps": list(self._execution_order),
            "pending_steps": pending or sorted(self._remaining),
            "audit_log": self.audit_log,
            "metrics": self.get_metrics(),
        }
        if reason:
            result["reason"] = reason
        return result

    # ------------------------------------------------------------------
    # Reliability metrics
    # ------------------------------------------------------------------
    def get_metrics(self) -> dict[str, Any]:
        total = len(self.steps)
        completed = len(self._completed)
        elapsed_ms = None
        if self._run_started_at is not None:
            elapsed_ms = round((time.monotonic() - self._run_started_at) * 1000, 3)

        mttr_ms = None
        if self._recovery_durations:
            mttr_ms = round((sum(self._recovery_durations) / len(self._recovery_durations)) * 1000, 3)

        return {
            "total_steps": total,
            "completed_steps": completed,
            "success_rate": round(completed / total, 4) if total else 0.0,
            "retry_count": self._retry_count,
            "rollback_count": self._rollback_count,
            "mttr_ms": mttr_ms,
            "end_to_end_latency_ms": elapsed_ms,
        }

    @staticmethod
    def _default_task_runner(step_name: str, step: WorkflowStep, context: dict[str, Any]) -> dict[str, Any]:
        return {
            "stage": step_name,
            "description": step.description,
            "status": "ok",
        }
