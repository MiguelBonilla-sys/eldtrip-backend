# ELD Trip Planner — Backend

Django REST API for calculating truck routes and generating FMCSA-compliant ELD log sheets.

## Setup

```bash
uv sync
uv run python manage.py migrate
```

## Run

```bash
ORS_API_KEY=your_key uv run python manage.py runserver
```

Server: `http://localhost:8000`

## API

**POST** `/api/trips/plan/`

```json
{
  "current_location": "Chicago, IL",
  "pickup_location": "Detroit, MI",
  "dropoff_location": "Nashville, TN",
  "current_cycle_used": 20
}
```

Returns: route data + stops + daily log sheets

## Tests

```bash
uv run pytest trips/tests/ -v
```

Expected: **20/20 tests passing**

## Deployment

Render + Procfile:
```bash
gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --chdir backend
```

Environment:
- `SECRET_KEY`
- `ORS_API_KEY` (OpenRouteService)
- `ALLOWED_HOSTS`
- `CORS_ALLOWED_ORIGINS` (Vercel frontend URL)

---

See root `README.md` for full documentation.
