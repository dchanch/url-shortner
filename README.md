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
- Agentic orchestration model with dependency graphs and approval gates
- Tests for API behavior and orchestration logic
- Architecture, setup, and scenario documentation

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
- app/service.py: Business logic for shortening, redirecting, and analytics
- app/db.py: SQLite schema and connection management
- app/orchestration.py: Dependency-driven workflow runner for agentic execution
- app/config.py: Environment and system configuration

The API validates URL schemes at the request boundary, while the service layer retains the same
validation as defense in depth. The repository layer owns SQLite access, keeping persistence
details out of routes and business logic.

## Agentic orchestration model

The orchestration layer models SDLC stages as nodes in a dependency graph.
Each stage can declare dependencies, retries, and approval requirements.
The runner executes only ready stages, ensures ordered progression, records audit logs,
retries failed operations, and stops for approval-gated high-impact actions.
This is a lightweight version of an agentic execution model that demonstrates:

- dependency sequencing
- cross-stage traceability
- bounded retry behavior
- approval gates
- re-planning readiness via explicit task graph structure

## Three scenarios

### 1) Greenfield scenario

A new URL shortener is created from scratch. The workflow stages are:

- requirements
- design
- implementation
- validation
- release readiness

This is represented in the orchestration graph and can be executed by the workflow runner.

### 2) Brownfield scenario

An existing shortener is enhanced to add analytics, retry protection, or a new API surface.
The existing graph can be extended by appending or modifying nodes while keeping dependencies intact.

### 3) Ambiguous scenario

If the product requirement is underspecified—for example, whether custom slugs must be unique,
where the analytics retention window should live, or whether redirects are 301 vs 307—the workflow
supports a controlled execution model where requirements must be clarified before the high-impact
release stage can pass.

## Testing approach

The project uses pytest with FastAPI's TestClient to validate the service behavior end-to-end.
The tests cover:

- link creation
- redirect behavior
- analytics updates
- custom slug validation
- workflow dependency ordering
- approval gate logic

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
- Architecture overview
- Setup instructions
- Testing approach
- Reliability and governance model
- Scenario walkthroughs
