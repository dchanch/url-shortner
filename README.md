# URL Shortener with Agentic Orchestration

A production-style URL shortener prototype built in Python with FastAPI, SQLite persistence, and a dependency-driven workflow executor that demonstrates agentic engineering discipline.

## What this project includes

- Shortening API with unique or custom short codes
- Redirect endpoint for shortened URLs
- Analytics endpoint with click totals and recent activity
- SQLite-backed persistence
- Strict HTTP/HTTPS input validation
- Request IDs and structured request timing logs
- Configurable in-memory rate limiting for link creation
- Agentic orchestration engine with dependency graphs, parallel synchronization, bounded retry, fallback, rollback, safe-stop/resume, policy guardrails, re-planning, and reliability metrics
- Three runnable scenarios (greenfield, brownfield, ambiguous) wired to the real service
- Tests for API behavior, orchestration primitives, and scenario execution
- Architecture, setup, scenario, and final engineering summary documentation

## Quick start

1. Create a Python virtual environment and install dependencies:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Start the API:

   ```bash
   uvicorn main:app --reload
   ```

   Optional environment settings:
   - `BASE_URL`: public base URL used in generated links
   - `API_KEY`: optional API key required on link creation requests
   - `RATE_LIMIT_REQUESTS`: link-creation requests allowed per client in the window (default: `60`)
   - `RATE_LIMIT_WINDOW_SECONDS`: rate-limit window size (default: `60`)

3. Use the service:

   ```bash
   curl -X POST http://localhost:8000/api/links \
     -H 'Content-Type: application/json' \
     -d '{"long_url":"https://example.com/very/long/path"}'
   ```

4. Redirect a short URL:

   ```bash
   curl -I http://localhost:8000/<short_code>
   ```

5. Inspect analytics:

   ```bash
   curl http://localhost:8000/api/links/<short_code>/analytics
   ```

## API summary

The full OpenAPI schema is exported to [docs/openapi.json](docs/openapi.json) and is
also available live at `/docs` (Swagger UI) and `/openapi.json` when the app is running.

- POST /api/links
  - Body: {"long_url": "https://example.com", "custom_slug": "demo"}
  - Returns the short code, short URL, created timestamp, and initial click count
- GET /{short_code}
  - Redirects to the original URL and increments the click counter
- GET /api/links/{short_code}
  - Returns link metadata
- GET /api/links/{short_code}/analytics
  - Returns total clicks and recent visit events
- GET /health
  - Returns service health and basic counters

Completed requests include an `X-Request-ID` response header. Clients may provide
their own request ID for tracing; otherwise the service generates one. Link creation is rate
limited per client address and returns HTTP 429 with `Retry-After` when the limit is reached.
When `API_KEY` is configured, POST /api/links also requires the value in the `X-API-Key` header.

## Architecture overview

The prototype is divided into a few simple modules:

- main.py: FastAPI app and route definitions
- app/services/url_shortener_service.py: Business logic for shortening, redirecting, and analytics
- app/repositories/links.py: SQLite persistence for links and click events
- app/db.py: SQLite schema and connection management
- app/orchestration.py: Governed, resumable workflow graph executor for agentic execution
- app/scenarios.py: Runnable greenfield/brownfield/ambiguous scenario builders
- app/config.py: Environment and system configuration

The API validates URL schemes at the request boundary, while the service layer retains the same
validation as defense in depth. The repository layer owns SQLite access, keeping persistence
details out of routes and business logic.

## Agentic orchestration model

The orchestration layer (`app/orchestration.py`) models SDLC stages as nodes in a
dependency graph and executes them with governance controls, not just ordering:

- explicit dependency graph with entry/exit gates
- parallel execution of independent ready stages with a synchronization barrier
- cross-stage context propagation and decision lineage (`graph.context`, `provide_context`)
- human approval checkpoints that safe-stop and resume rather than crash
- bounded retries, fallback handlers, and rollback of completed stages on unrecoverable failure
- pluggable policy guardrails (critical stages must be approval-gated by default)
- an audit-grade log of every state transition
- reliability metrics: success rate, retry/rollback counts, MTTR, end-to-end latency
- dynamic re-planning that adds/changes stages mid-flight without losing completed work

See [docs/architecture.md](docs/architecture.md) for the full design and
[docs/scenarios.md](docs/scenarios.md) for how each guarantee is exercised.

## Three scenarios (runnable)

`app/scenarios.py` builds real `WorkflowExecutionGraph` instances wired to the actual
`UrlShortenerService` for all three required scenarios. Full walkthroughs with
decomposition, orchestration, and validation detail are in
[docs/scenarios.md](docs/scenarios.md); executable proof is in
[tests/test_scenarios.py](tests/test_scenarios.py).

- **Greenfield** — `build_greenfield_workflow()`: requirements → design →
  implementation → validation → release (approval-gated).
- **Brownfield** — `build_brownfield_workflow()`: adds link expiration to the
  existing system; demonstrates a retry-then-succeed migration and, with
  `force_regression_failure=True`, a rollback of the completed implementation stage.
- **Ambiguous** — `build_ambiguous_workflow()`: blocks (safe-stop) at the design
  stage until custom-slug case sensitivity and analytics retention window are
  clarified via `graph.provide_context(...)`, then resumes.

## Testing approach

The project uses pytest with FastAPI's TestClient to validate the service behavior end-to-end.
The tests cover:

- link creation, redirect behavior, and analytics updates
- custom slug validation and rate limiting
- workflow dependency ordering, parallel-batch execution, and reliability metrics
- approval gates (safe-stop and resume), entry-gate blocking, fallback, rollback, and re-planning
- all three runnable scenarios end-to-end against the real service (`tests/test_scenarios.py`)

Run:

```bash
pytest -q
```

## Risks, trade-offs, and limitations

- SQLite is ideal for a prototype but is not a production-scale distributed database.
- Click events are stored locally and are suitable for a demo, not a global analytics backend.
- The in-memory rate limiter is suitable for one process; a multi-instance deployment needs a shared store such as Redis.
- The orchestration model is intentionally lightweight; it does not include full distributed scheduling,
  multi-agent negotiation, or enterprise SIEM integrations.
- Production deployment would add authentication, abuse detection, and stronger authorization policies.
- Setting `API_KEY` enables a lightweight API-key boundary for the prototype; production identity
  and authorization should use a managed authentication provider.

## Deliverables summary

- Working prototype
- [Architecture overview](docs/architecture.md)
- [Scenario walkthroughs](docs/scenarios.md) (greenfield, brownfield, ambiguous)
- [Final engineering summary](docs/engineering-summary.md) (rationale, risks, assumptions, limitations)
- Setup instructions
- Testing approach
- Reliability and governance model
