# ELD Trip Planner — Backend API

Django REST API that calculates truck routes according to FMCSA (Federal Motor Carrier Safety Administration) Hours of Service regulations and generates FMCSA-compliant Electronic Logging Device (ELD) log sheets.

## 🎯 What This Solves

This backend handles the **business logic** for the assessment requirements:

**Input** → Trip details (current location, pickup, dropoff, current cycle hours used)
**Processing** → 
- Geocode locations using OpenRouteService
- Calculate optimal route with distance and duration
- Generate HOS-compliant itinerary with mandatory breaks and fuel stops
- Create daily log sheets that sum exactly 24 hours per day

**Output** → JSON response containing route data, stop locations, and pre-filled log sheet data

## 🏗️ Architecture

### Core Components

**1. HOS Calculator** (`trips/hos_calculator.py`)
- Implements FMCSA regulations as non-negotiable rules
- Splits multi-day trips into individual calendar days
- Inserts mandatory 30-minute breaks before 8 cumulative driving hours
- Enforces 11-hour daily driving cap
- Enforces 14-hour driving window
- Manages 70-hour/8-day cycle with 34-hour reset
- Inserts fuel stops every 1,000 miles
- Allocates 1 hour pickup and 1 hour dropoff time

**2. OpenRouteService Client** (`trips/ors_client.py`)
- Geocodes location names to latitude/longitude
- Calculates route using HGV (heavy goods vehicle) profile
- Returns polyline (for map display), total distance, and waypoints
- Includes automatic retry logic and in-memory cache

**3. REST Endpoint** (`trips/views.py`)
- Validates incoming trip request data
- Chains ORS geocoding + routing + HOS calculation
- Returns comprehensive JSON response with route + stops + log sheets

**4. Tests** (`trips/tests/test_hos_calculator.py`)
- 20/20 tests covering all HOS rules
- Validates daily totals = 24 hours
- Tests cycle management, breaks, fuel stops, endpoint allocation

## 📋 API Endpoint

### POST `/api/trips/plan/`

**Request**:
```json
{
  "current_location": "Chicago, IL",
  "pickup_location": "Detroit, MI",
  "dropoff_location": "Nashville, TN",
  "current_cycle_used": 20
}
```

**Response**:
```json
{
  "route": {
    "total_miles": 861.2,
    "duration_hours": 15.7,
    "polyline": [[lat, lng], [lat, lng], ...],
    "origin": {"lat": 41.88, "lng": -87.63, "display_name": "Chicago, Illinois"},
    "pickup": {"lat": 42.33, "lng": -83.05, "display_name": "Detroit, Michigan"},
    "dropoff": {"lat": 36.16, "lng": -86.78, "display_name": "Nashville, Tennessee"}
  },
  "stops": [
    {"type": "pickup", "duration_hours": 1.0, "notes": "Pickup location"},
    {"type": "driving", "duration_hours": 11.0, "notes": "Driving segment"},
    {"type": "rest_30min", "duration_hours": 0.5, "notes": "Mandatory break"},
    {"type": "driving", "duration_hours": 4.7, "notes": "Driving segment"},
    {"type": "fuel", "duration_hours": 0.5, "notes": "Fuel stop"},
    {"type": "dropoff", "duration_hours": 1.0, "notes": "Dropoff location"}
  ],
  "log_sheets": [
    {
      "date": "Day 1",
      "driver_start_time": "06:00",
      "segments": [
        {"status": "on_duty", "start": "06:00", "end": "07:00", "notes": "Pickup"},
        {"status": "driving", "start": "07:00", "end": "18:00", "notes": "En route"},
        {"status": "on_duty", "start": "18:00", "end": "18:30", "notes": "Rest break"},
        {"status": "off_duty", "start": "18:30", "end": "06:00", "notes": "Rest"}
      ],
      "totals": {"off_duty": 11.5, "sleeper": 0.0, "driving": 11.0, "on_duty": 1.5},
      "miles_today": 600.0
    },
    {
      "date": "Day 2",
      "driver_start_time": "06:00",
      "segments": [
        {"status": "on_duty", "start": "06:00", "end": "07:00", "notes": "Dropoff"},
        {"status": "driving", "start": "07:00", "end": "11:42", "notes": "En route"},
        {"status": "on_duty", "start": "11:42", "end": "12:00", "notes": "Fuel stop"},
        {"status": "off_duty", "start": "12:00", "end": "06:00", "notes": "Rest"}
      ],
      "totals": {"off_duty": 18.0, "sleeper": 0.0, "driving": 4.7, "on_duty": 1.3},
      "miles_today": 261.2
    }
  ],
  "total_days": 2
}
```

**Error Codes**:
- `400` — Validation error (missing required fields)
- `502` — OpenRouteService API unavailable
- `500` — HOS calculation error

## ⚙️ FMCSA Hours of Service Rules

These are **federal regulations** — hardcoded, non-configurable, and auditable:

| Rule | Value | Why |
|------|-------|-----|
| Max driving per day | 11 hours | Driver fatigue safety limit |
| Driving window | 14 hours | Can't drive before 10h continuous rest |
| Mandatory break | 30 min | After 8 cumulative hours driving |
| Cycle limit | 70 hours | Within any 8 calendar days |
| Cycle reset | 34 hours | Continuous off-duty/sleeper time |
| Fuel stops | Every 1,000 miles | Practical refueling frequency |
| Pickup duration | 1 hour | Standard loading time |
| Dropoff duration | 1 hour | Standard unloading time |

**Guarantees**:
- ✅ Each daily log sheet totals exactly 24 hours
- ✅ All driving hours respect the 11-hour cap
- ✅ All driving windows respect the 14-hour window
- ✅ All mandatory breaks are inserted
- ✅ 70-hour cycle is tracked and enforced
- ✅ Fuel stops are placed every ~1,000 miles

## 🚀 Local Development

### Prerequisites
- Python 3.11+
- [UV package manager](https://docs.astral.sh/uv/) (faster than pip)
- OpenRouteService API key (free tier at https://openrouteservice.org)

### Setup

```bash
# Install dependencies
uv sync

# Initialize database
uv run python manage.py migrate

# Run development server
ORS_API_KEY=your_key uv run python manage.py runserver
```

Server: `http://localhost:8000`

### Testing

```bash
# Run all tests
uv run pytest trips/tests/ -v

# Run with coverage
uv run pytest trips/tests/ --cov=trips --cov-report=html
```

Expected: **20/20 tests passing**

Test categories:
- `TestSingleDayTrip` — Single-day itinerary structure and 24h totals
- `TestHOSBreaks` — 30-min breaks, 11h cap, 14h window enforcement
- `TestCycleManagement` — 70h cycle tracking, 34h reset insertion
- `TestFuelStops` — Fuel stop placement every 1,000 miles
- `TestPickupDropoff` — 1h pickup first, 1h dropoff last
- `TestSegmentStructure` — Log sheet format validation

### Project Structure

```
backend/
├── manage.py                       # Django CLI
├── Procfile                        # Render deployment
├── pyproject.toml                  # UV dependencies
├── .env.example                    # Template env vars
├── db.sqlite3                      # Local database
├── config/
│   ├── settings.py                 # Django config + CORS
│   ├── urls.py                     # Route definitions
│   └── wsgi.py                     # WSGI entry point
└── trips/
    ├── models.py                   # Django models
    ├── views.py                    # REST endpoints
    ├── serializers.py              # Request/response validation
    ├── urls.py                     # Trip routes
    ├── hos_calculator.py           # HOS business logic (500+ lines)
    ├── ors_client.py               # OpenRouteService integration
    └── tests/
        └── test_hos_calculator.py  # 20 comprehensive tests
```

## 🔧 Environment Variables

Create `.env` file in backend root:

```bash
# Django
SECRET_KEY=your-secret-key-here
DEBUG=False
ALLOWED_HOSTS=localhost,127.0.0.1

# Database
# (SQLite used locally; configurable for production)

# OpenRouteService
ORS_API_KEY=your-openrouteservice-api-key

# CORS (for development)
CORS_ALLOWED_ORIGINS=http://localhost:5173,http://localhost:3000
```

## 🌐 Deployment on Render

### Setup Steps

1. Create Render account and connect GitHub repo
2. Create "Web Service" from `eldtrip-backend` repository
3. Configure build and start commands
4. Add environment variables

### Build & Start Commands

**Build**:
```bash
uv sync && uv run python manage.py migrate
```

**Start**:
```bash
gunicorn config.wsgi:application --bind 0.0.0.0:$PORT
```

### Environment Variables (Render Dashboard)

| Variable | Example | Notes |
|----------|---------|-------|
| `SECRET_KEY` | `django-insecure-a1b2c3d4...` | Generate with `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"` |
| `DEBUG` | `False` | Always False in production |
| `ALLOWED_HOSTS` | `eldtrip-api.onrender.com` | Your Render domain |
| `ORS_API_KEY` | `5b3ce3597851110001cf...` | Get from OpenRouteService dashboard |
| `CORS_ALLOWED_ORIGINS` | `https://eldtrip-frontend.vercel.app` | Your Vercel frontend URL |

**Result**: Backend API at `https://eldtrip-api.onrender.com`

## 📦 Dependencies

Managed by UV in `pyproject.toml`:

**Production**:
- `django>=5.0` — Web framework
- `djangorestframework>=3.15` — REST API toolkit
- `django-cors-headers>=4.3` — Cross-origin requests (Vercel → Render)
- `requests>=2.31` — HTTP client for OpenRouteService
- `gunicorn>=22.0` — WSGI application server (Render)
- `whitenoise>=6.7` — Static file serving + compression
- `python-dotenv>=1.0` — Environment variable loading

**Development**:
- `pytest>=8.0` — Test runner
- `pytest-django>=4.8` — Django test fixtures

## 🔐 Security

- ✅ API keys loaded from `.env`, never hardcoded
- ✅ CORS configured to allow only Vercel frontend
- ✅ HTTPS enforced in production
- ✅ SECRET_KEY regenerated for production
- ✅ DEBUG mode disabled in production
- ✅ Input validation on all endpoints
- ✅ No sensitive data in error messages

## 📚 Key Files Explained

### hos_calculator.py (500+ lines)

**Class**: `HOSTripCalculator`

**Constructor**:
```python
def __init__(self, total_miles: float, current_cycle_used: float, start_time_decimal: float = 6.0):
    self.total_miles = total_miles
    self.current_cycle_used = current_cycle_used
    self.start_time_decimal = start_time_decimal  # 6.0 = 6:00 AM
    self.average_speed = 55.0  # Conservative estimate
    self.total_driving_hours = total_miles / self.average_speed
```

**Core Constants** (FMCSA regulations, hardcoded, non-negotiable):
```python
MAX_DRIVING_HOURS = 11.0          # Federal limit per calendar day
DRIVING_WINDOW_HOURS = 14.0        # From start of workday
REQUIRED_REST_HOURS = 10.0         # Before resuming driving
BREAK_REQUIRED_AFTER = 8.0         # Cumulative driving hours
BREAK_DURATION = 0.5               # 30 minutes
FUEL_STOP_DURATION = 0.5           # 30 minutes
CYCLE_LIMIT = 70.0                 # In any 8 calendar days
CYCLE_RESET_HOURS = 34.0           # Continuous off-duty/sleeper
FUEL_STOP_INTERVAL_MILES = 1000.0  # Maximum between refuelings
```

**Main Method**: `plan_trip()`
```python
def plan_trip(self):
    """
    Orchestrates the entire trip planning algorithm.
    
    Returns:
        dict: {
            "stops": [{"type": str, "duration_hours": float, "notes": str}, ...],
            "log_sheets": [{"date": str, "segments": [...], "totals": {...}}, ...],
            "total_days": int
        }
    """
    # 1. Calculate daily driving needs
    # 2. Check and apply mandatory breaks
    # 3. Check and apply fuel stops
    # 4. Check and apply cycle resets
    # 5. Generate log sheets (24h totals guaranteed)
    # 6. Return complete itinerary
```

**Key Internal Methods**:

1. **`_split_into_days()`** — Divides total distance into daily chunks respecting 11h cap
2. **`_insert_mandatory_breaks()`** — Adds 30-min breaks when approaching 8h driving
3. **`_insert_fuel_stops()`** — Places 30-min fuel stops every 1,000 miles
4. **`_check_and_apply_cycle_reset()`** — Inserts 34h reset when cycle ≥ 70h
5. **`_generate_log_sheets()`** — Creates daily FMCSA-compliant logs (each = 24.0h exactly)
6. **`_convert_decimal_time_to_hhmm()`** — Converts monotonic decimal hours (e.g., 6.5) to "06:30"

**Time Tracking**: Uses monotonic decimal hours (not datetime objects)
- Day 1 runs 6.0 to 30.0 (midnight = 24.0, 6am next day = 30.0)
- Simplifies calculations and prevents timezone issues

### ors_client.py (150+ lines)

**Purpose**: Encapsulates all OpenRouteService API communication

**Key Functions**:

1. **`geocode(location: str) -> dict`**
   ```python
   # Input: "Chicago, IL"
   # Output: {"lat": 41.8781, "lng": -87.6298, "display_name": "Chicago, Illinois, USA"}
   # Includes in-memory caching to prevent duplicate API calls
   ```

2. **`get_route(origin: dict, pickup: dict, dropoff: dict) -> dict`**
   ```python
   # Uses HGV (heavy goods vehicle) routing profile
   # Returns: {
   #   "total_miles": 542.3,
   #   "duration_hours": 8.3,
   #   "polyline": [[lat, lng], [lat, lng], ...],
   #   "waypoints": [{"distance": 0}, {"distance": 200}, ...]
   # }
   ```

**Error Handling**:
- Automatic retry on HTTP 429 (rate limit) and 5xx errors
- Raises `ORSError` with descriptive message on failure
- Client code catches and converts to HTTP 502

**Caching**: In-memory dict (process lifetime)
- Key: `f"{location.lower()}"`
- Prevents redundant API calls for same location
- Sufficient for MVP; consider Redis for multi-process production

### views.py (80+ lines)

**Endpoint**: `POST /api/trips/plan/`

**Request Pipeline**:
```python
def plan_trip(request):
    # 1. Validate JSON with TripRequestSerializer
    serializer = TripRequestSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    # 2. Extract validated data
    data = serializer.validated_data
    
    # 3. Geocode locations
    origin = geocode(data['current_location'])
    pickup = geocode(data['pickup_location'])
    dropoff = geocode(data['dropoff_location'])
    
    # 4. Get route
    route = get_route(origin, pickup, dropoff)
    
    # 5. Calculate HOS-compliant itinerary
    calculator = HOSTripCalculator(
        total_miles=route['total_miles'],
        current_cycle_used=data['current_cycle_used'],
        start_time_decimal=6.0  # 6:00 AM start
    )
    result = calculator.plan_trip()
    
    # 6. Combine and return
    response = {
        "route": route,
        "stops": result['stops'],
        "log_sheets": result['log_sheets'],
        "total_days": result['total_days']
    }
    return Response(response)
```

**Error Responses**:
- `400` → Invalid request (missing/bad fields)
- `502` → OpenRouteService API down
- `500` → HOS calculation error (should not happen if inputs valid)

## ❌ What We Didn't Do (and Why)

| Approach | Why Not | What We Did Instead |
|----------|---------|---------------------|
| HOS logic on frontend | Not auditable, can't validate accuracy | All calculations on backend, testable, secure |
| Google Maps | Costs money, requires credit card | Free Leaflet + OpenStreetMap (frontend handles display) |
| Simple distance/time calculation | Ignores federal regulations | Implemented full FMCSA rules engine |
| Fixed start time (e.g., 00:00) | Unrealistic for drivers | Configurable start time (default 06:00) |
| Database for route caching | Overengineering MVP | Stateless API, each request is independent |

## 📞 Support

See root `README.md` for full project documentation and frontend setup.

---

**Last Updated**: April 14, 2026  
**Status**: ✅ Live on Render, 20/20 tests passing
