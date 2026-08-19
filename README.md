# 3D Bin Packing Backend

A runnable Django 5.2 LTS backend for the university 3D bin-packing project described in `BACKEND_DESIGN.md` and `FRONTEND_DESIGN.md`.

## Included

- Email-first custom user model with Argon2 hashing
- JWT access/refresh authentication, refresh rotation, and blacklist-based logout
- Hashed, expiring, single-use email verification and password-reset tokens
- Owner-scoped projects, one-container MVP API, box types, presets, jobs, layouts, exports, and notifications
- Four registry-based algorithms: First Fit Decreasing, Shelf/Layer, Best-Fit Extreme Point, and seeded GRASP Extreme Point
- Celery + Redis asynchronous packing jobs with progress, cancellation, polling, and WebSocket events
- Server-side layout validation for bounds, overlap, quantities, orientations, weight, and optional basic stacking/load-bearing rules
- Authoritative metrics and unplaced counts
- CSV/PDF exports and frontend-uploaded PNG storage
- PostgreSQL, Redis, Django, and Celery Docker Compose stack
- Database migrations, five seeded container presets, and automated tests

## Quick start with Docker

Requirements: Docker with the Compose plugin.

```bash
cp .env.example .env
docker compose up --build
```

The API is then available at `http://localhost:8000/api/v1/`. The web container applies migrations and seeds the presets during its first start.

Create an administrator in a second terminal:

```bash
docker compose exec web python manage.py createsuperuser
```

Run tests:

```bash
docker compose exec web python manage.py test --settings=config.test_settings
```

Stop the stack without deleting database/Redis data:

```bash
docker compose down
```

## Local development without Docker

Python 3.12+ is recommended.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

The default non-Docker database is SQLite. For background jobs and WebSockets, also run Redis and then:

```bash
celery -A config worker -l INFO
daphne -b 0.0.0.0 -p 8000 config.asgi:application
```

Development email uses the console backend. Verification and reset links appear in the web process logs. Set a real email backend before deployment.

## API map

All paths are below `/api/v1`. Resources owned by another user return `404`.

| Area | Endpoints |
| --- | --- |
| Authentication | `POST /auth/register`, `/auth/login`, `/auth/logout`, `/auth/token/refresh` |
| Account | `GET/PATCH /auth/me`, `POST /auth/password/change` |
| Email verification | `POST /auth/verify-email`, `/auth/resend-verification` |
| Password reset | `POST /auth/password/reset`, `/auth/password/reset/confirm` |
| Projects | `GET/POST /projects`, `GET/PATCH/DELETE /projects/{id}` |
| Container | `GET/PUT/PATCH /projects/{id}/container`, `GET /container-presets` |
| Boxes | `GET/POST /projects/{id}/boxes`, `GET/PATCH/DELETE /projects/{id}/boxes/{box_id}`, `POST /projects/{id}/boxes/bulk` |
| Algorithms | `GET /algorithms` |
| Jobs | `GET/POST /projects/{id}/packing-jobs`, `GET /packing-jobs/{id}`, `POST /packing-jobs/{id}/cancel` |
| Layouts | `GET/POST /projects/{id}/layouts`, `GET/PATCH/DELETE /layouts/{id}` |
| Exports | `POST /layouts/{id}/export`, `GET /layouts/{id}/artifacts` |
| Notifications | `GET /notifications`, `POST /notifications/{id}/read` |

Use `Authorization: Bearer <access-token>` for authenticated REST requests. Unverified users can sign in and configure projects, but cannot run packing jobs or create exports.

### Example: submit a packing job

```http
POST /api/v1/projects/PROJECT_UUID/packing-jobs
Authorization: Bearer ACCESS_TOKEN
Content-Type: application/json

{
  "algorithm": "ffd_extreme_point",
  "parameters": {
    "allow_rotation_global": true,
    "respect_weight": true,
    "respect_stacking": false,
    "candidate_limit": 5000
  }
}
```

The response is `202 Accepted`. Poll `GET /api/v1/packing-jobs/{job_id}` or subscribe to the notification socket.

## WebSocket notifications

Connect to:

```text
ws://localhost:8000/ws/notifications/?token=ACCESS_TOKEN
```

Messages use this stable shape:

```json
{
  "event": "packing_job.updated",
  "payload": {
    "job_id": "uuid",
    "status": "succeeded",
    "progress": 100,
    "layout_id": "uuid"
  }
}
```

Use the short-lived access token only, use `wss://` in production, and configure the reverse proxy not to log query strings.

## Placement contract

Application coordinates are always X = length, Y = width/depth, Z = height/up. Positions describe a box's minimum corner. `size_mm` is post-rotation and authoritative for rendering.

Supported orientations map the original `(L, W, H)` values to `(X, Y, Z)`:

| Code | X | Y | Z |
| --- | --- | --- | --- |
| `LWH` | L | W | H |
| `LHW` | L | H | W |
| `WLH` | W | L | H |
| `WHL` | W | H | L |
| `HLW` | H | L | W |
| `HWL` | H | W | L |

For manual layout writes, send the complete contract:

```json
{
  "name": "My layout",
  "is_saved": true,
  "respect_stacking": false,
  "placements": {
    "placements": [
      {
        "box_id": "box-type-uuid",
        "instance_index": 0,
        "position_mm": {"x": 0, "y": 0, "z": 0},
        "size_mm": {"length": 400, "width": 300, "height": 200},
        "orientation": "LWH"
      }
    ],
    "unplaced": []
  }
}
```

The server discards client-provided unplaced counts, validates every placement, and returns authoritative `placements` and `metrics`.

## Export behavior

- `csv`: generated server-side from placements.
- `pdf`: generated server-side as a compact metrics/placement report.
- `png`: submit multipart form data containing `format=png` and an `image` captured by the frontend WebGL canvas.

## Error format

API errors use:

```json
{
  "error": {
    "code": "validation_error",
    "message": "The request could not be completed.",
    "details": {"field": ["Specific problem."]}
  }
}
```

## Important MVP notes

- The schema deliberately keeps `Container.project` as a foreign key for future multi-container support. The v1 API expects exactly one container.
- Stacking is optional. Its current load calculation distributes each directly supported box's weight by support overlap area; full recursive load propagation is a future enhancement.
- Job cancellation is cooperative. The worker checks state between box placements; Celery revoke is non-terminating to avoid corrupting a transaction.
- Uploaded/generated artifacts use Django storage. Replace local media storage with an S3-compatible backend for production.
- Before a public launch, add production email, object storage, centralized logs/metrics, stricter proxy rate limits, secrets management, data-retention tooling, and a professional PIPEDA/privacy review.

## Useful commands

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test --settings=config.test_settings
ruff check . && ruff format --check .
python manage.py shell
```

## Adding an algorithm

Create a runner in `packing/algorithms/` and register it with `registry.register(...)`. A runner receives the immutable input snapshot, validated parameter values, a cancellation callback, and a progress callback. Because `GET /algorithms` reads the registry, the frontend discovers the new option without a hard-coded list.

## Algorithm choices

- **First Fit Decreasing (Extreme Point):** fast deterministic baseline that accepts the first feasible candidate.
- **Shelf / Layer:** fastest option for regular cartons and simple row/layer arrangements.
- **Best Fit Extreme Point:** evaluates feasible candidate/orientation combinations and scores compactness, surface contact, and residual space.
- **GRASP Extreme Point:** repeats randomized best-fit constructions, using a deterministic seed, and retains the result with the greatest packed volume and count. More iterations improve exploration but increase runtime.

The advanced algorithms are inspired by extreme-point constructive heuristics and Greedy Randomized Adaptive Search Procedures. They remain bounded heuristics rather than exact solvers, so they can run inside the existing cancellable Celery task.
