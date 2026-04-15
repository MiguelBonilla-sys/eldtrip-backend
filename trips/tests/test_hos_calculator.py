"""
Unit tests for HOSTripCalculator.
Tests are written FIRST (TDD RED phase) before the implementation.
All HOS rules are from FMCSA property-carrying driver regulations.
"""
import pytest
from trips.hos_calculator import HOSTripCalculator


class TestSingleDayTrip:
    def test_trip_within_single_day(self):
        """300 miles at 55 mph = ~5.45h driving — fits in one day."""
        calc = HOSTripCalculator(total_miles=300, current_cycle_used=0)
        result = calc.plan_trip()
        assert len(result["log_sheets"]) == 1

    def test_log_sheet_has_required_keys(self):
        calc = HOSTripCalculator(total_miles=200, current_cycle_used=0)
        result = calc.plan_trip()
        log = result["log_sheets"][0]
        assert "date" in log
        assert "segments" in log
        assert "totals" in log
        assert "miles_today" in log

    def test_log_totals_sum_to_24(self):
        """Every log sheet must account for exactly 24 hours."""
        calc = HOSTripCalculator(total_miles=400, current_cycle_used=10)
        result = calc.plan_trip()
        for log in result["log_sheets"]:
            total = sum(log["totals"].values())
            assert abs(total - 24.0) < 0.01, (
                f"Log totals sum to {total}, expected 24.0. Totals: {log['totals']}"
            )

    def test_log_totals_sum_to_24_multi_day(self):
        """Each day in a multi-day trip must sum to 24h."""
        calc = HOSTripCalculator(total_miles=1200, current_cycle_used=0)
        result = calc.plan_trip()
        assert len(result["log_sheets"]) > 1
        for i, log in enumerate(result["log_sheets"]):
            total = sum(log["totals"].values())
            assert abs(total - 24.0) < 0.01, (
                f"Day {i + 1} totals sum to {total}, expected 24.0"
            )


class TestHOSBreaks:
    def test_30min_break_inserted_before_8h(self):
        """550 miles ≈ 10h driving — must trigger the mandatory 30-min break."""
        calc = HOSTripCalculator(total_miles=550, current_cycle_used=0)
        result = calc.plan_trip()
        stops = result["stops"]
        assert any(s["type"] == "rest_30min" for s in stops), (
            f"Expected a rest_30min stop. Got stops: {[s['type'] for s in stops]}"
        )

    def test_no_break_needed_under_8h(self):
        """400 miles ≈ 7.3h driving — no mandatory 30-min break needed."""
        calc = HOSTripCalculator(total_miles=400, current_cycle_used=0)
        result = calc.plan_trip()
        stops = result["stops"]
        assert not any(s["type"] == "rest_30min" for s in stops), (
            "Unexpected rest_30min stop for a short trip"
        )

    def test_11h_driving_cap_per_day(self):
        """No single log sheet should show more than 11h of driving."""
        calc = HOSTripCalculator(total_miles=900, current_cycle_used=0)
        result = calc.plan_trip()
        for log in result["log_sheets"]:
            assert log["totals"]["driving"] <= 11.0 + 0.01, (
                f"Driving hours exceeded 11h: {log['totals']['driving']}"
            )

    def test_14h_window_respected(self):
        """Driving + on_duty cannot exceed 14h in the driving window."""
        calc = HOSTripCalculator(total_miles=800, current_cycle_used=0)
        result = calc.plan_trip()
        for log in result["log_sheets"]:
            active = log["totals"]["driving"] + log["totals"]["on_duty"]
            assert active <= 14.0 + 0.01, (
                f"Active time exceeded 14h window: {active}"
            )


class TestCycleManagement:
    def test_cycle_limit_respected(self):
        """With 65h used, only 5h remain before 34h reset is required."""
        calc = HOSTripCalculator(total_miles=800, current_cycle_used=65)
        result = calc.plan_trip()
        assert any(s["type"] == "reset_34h" for s in result["stops"]), (
            f"Expected reset_34h stop. Got: {[s['type'] for s in result['stops']]}"
        )

    def test_cycle_reset_allows_continuation(self):
        """After a 34h reset, the trip should continue and complete."""
        calc = HOSTripCalculator(total_miles=800, current_cycle_used=68)
        result = calc.plan_trip()
        # Should complete (stops include reset, but trip finishes)
        assert any(s["type"] == "dropoff" for s in result["stops"])

    def test_no_reset_when_cycle_has_headroom(self):
        """With only 20h used and a short trip, no reset needed."""
        calc = HOSTripCalculator(total_miles=300, current_cycle_used=20)
        result = calc.plan_trip()
        assert not any(s["type"] == "reset_34h" for s in result["stops"])


class TestFuelStops:
    def test_fuel_stop_every_1000_miles(self):
        """2200 miles should produce at least 2 fuel stops."""
        calc = HOSTripCalculator(total_miles=2200, current_cycle_used=0)
        result = calc.plan_trip()
        fuel_stops = [s for s in result["stops"] if s["type"] == "fuel"]
        assert len(fuel_stops) >= 2, (
            f"Expected >= 2 fuel stops, got {len(fuel_stops)}"
        )

    def test_no_fuel_stop_under_1000_miles(self):
        """Under 1000 miles should not require a fuel stop."""
        calc = HOSTripCalculator(total_miles=800, current_cycle_used=0)
        result = calc.plan_trip()
        fuel_stops = [s for s in result["stops"] if s["type"] == "fuel"]
        assert len(fuel_stops) == 0, (
            f"Unexpected fuel stops for 800 mile trip: {len(fuel_stops)}"
        )


class TestPickupDropoff:
    def test_pickup_on_duty_present(self):
        """First stop should always be a pickup (1h on-duty)."""
        calc = HOSTripCalculator(total_miles=300, current_cycle_used=0)
        result = calc.plan_trip()
        assert result["stops"][0]["type"] == "pickup"

    def test_dropoff_on_duty_present(self):
        """Last stop should always be a dropoff (1h on-duty)."""
        calc = HOSTripCalculator(total_miles=300, current_cycle_used=0)
        result = calc.plan_trip()
        assert result["stops"][-1]["type"] == "dropoff"

    def test_pickup_duration_is_1h(self):
        """Pickup must be exactly 1 hour."""
        calc = HOSTripCalculator(total_miles=300, current_cycle_used=0)
        result = calc.plan_trip()
        pickup = result["stops"][0]
        assert pickup["duration_hours"] == 1.0

    def test_dropoff_duration_is_1h(self):
        """Dropoff must be exactly 1 hour."""
        calc = HOSTripCalculator(total_miles=300, current_cycle_used=0)
        result = calc.plan_trip()
        dropoff = result["stops"][-1]
        assert dropoff["duration_hours"] == 1.0


class TestSegmentStructure:
    def test_segments_have_required_keys(self):
        calc = HOSTripCalculator(total_miles=300, current_cycle_used=0)
        result = calc.plan_trip()
        for log in result["log_sheets"]:
            for seg in log["segments"]:
                assert "status" in seg
                assert "start" in seg
                assert "end" in seg
                assert "notes" in seg

    def test_segment_status_values_are_valid(self):
        valid_statuses = {"off_duty", "sleeper", "driving", "on_duty"}
        calc = HOSTripCalculator(total_miles=600, current_cycle_used=0)
        result = calc.plan_trip()
        for log in result["log_sheets"]:
            for seg in log["segments"]:
                assert seg["status"] in valid_statuses, (
                    f"Invalid segment status: {seg['status']}"
                )

    def test_time_format_is_hhmm(self):
        """Segment times must be in HH:MM format."""
        import re
        pattern = re.compile(r"^\d{2}:\d{2}$")
        calc = HOSTripCalculator(total_miles=400, current_cycle_used=0)
        result = calc.plan_trip()
        for log in result["log_sheets"]:
            for seg in log["segments"]:
                assert pattern.match(seg["start"]), f"Invalid start time: {seg['start']}"
                assert pattern.match(seg["end"]), f"Invalid end time: {seg['end']}"
