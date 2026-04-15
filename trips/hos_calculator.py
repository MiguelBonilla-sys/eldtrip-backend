"""
HOS (Hours of Service) Trip Calculator for property-carrying drivers.
Rules are fixed per FMCSA regulations — not configurable.

All time arithmetic uses decimal hours (float) to avoid timezone complexity.
Time values grow monotonically (e.g., 26.0 means 02:00 on day 2).
"""
from __future__ import annotations


class HOSTripCalculator:
    # FMCSA constants — federal law, never configurable
    MAX_DRIVING_HOURS = 11.0
    DRIVING_WINDOW_HOURS = 14.0
    REQUIRED_REST_HOURS = 10.0
    BREAK_REQUIRED_AFTER = 8.0
    BREAK_DURATION = 0.5
    CYCLE_LIMIT = 70.0
    CYCLE_RESET_HOURS = 34.0
    FUEL_STOP_INTERVAL_MILES = 1000.0
    FUEL_STOP_DURATION = 0.5
    PICKUP_DURATION = 1.0
    DROPOFF_DURATION = 1.0
    AVERAGE_SPEED_MPH = 55.0

    def __init__(
        self,
        total_miles: float,
        current_cycle_used: float,
        start_time_decimal: float = 6.0,
    ) -> None:
        if not (0.0 <= current_cycle_used <= self.CYCLE_LIMIT):
            raise ValueError(
                f"current_cycle_used must be between 0 and {self.CYCLE_LIMIT}"
            )
        self.total_miles = total_miles
        self.cycle_hours_used = current_cycle_used
        self.start_time_decimal = start_time_decimal

        # Monotonically increasing clock (decimal hours from epoch 0)
        self._clock: float = start_time_decimal
        # Start of current day's driving window
        self._day_window_start: float = start_time_decimal
        # Per-day accumulators
        self._driving_today: float = 0.0
        self._continuous_driving: float = 0.0
        self._miles_today: float = 0.0
        # Segments for current day (use day-relative times for display)
        self._current_day_segments: list[dict] = []
        # Per-day logical start (for display: Day 1 starts at self.start_time_decimal)
        self._day_display_start: float = start_time_decimal

        # Results
        self._log_sheets: list[dict] = []
        self._stops: list[dict] = []
        self._day_number: int = 1

    # ------------------------------------------------------------------ #
    # Helpers                                                               #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _to_hhmm(decimal_hours: float) -> str:
        """Convert monotonic decimal hours to HH:MM (mod 24)."""
        h = decimal_hours % 24.0
        hours = int(h)
        minutes = round((h - hours) * 60)
        if minutes == 60:
            hours = (hours + 1) % 24
            minutes = 0
        return f"{hours:02d}:{minutes:02d}"

    def _driving_hours_available(self) -> float:
        """Hours of driving remaining today (respects 11h cap and 14h window)."""
        drive_cap_left = self.MAX_DRIVING_HOURS - self._driving_today
        window_elapsed = self._clock - self._day_window_start
        window_left = self.DRIVING_WINDOW_HOURS - window_elapsed
        return max(0.0, min(drive_cap_left, window_left))

    def _cycle_remaining(self) -> float:
        return max(0.0, self.CYCLE_LIMIT - self.cycle_hours_used)

    def _add_segment(self, status: str, duration: float, notes: str = "") -> None:
        """Record a segment and advance the clock."""
        start_hhmm = self._to_hhmm(self._clock)
        end_hhmm = self._to_hhmm(self._clock + duration)
        self._current_day_segments.append(
            {"status": status, "start": start_hhmm, "end": end_hhmm, "notes": notes}
        )
        self._clock += duration

        if status == "driving":
            self._driving_today += duration
            self._continuous_driving += duration
            self.cycle_hours_used += duration
            self._miles_today += duration * self.AVERAGE_SPEED_MPH
        elif status == "on_duty":
            self.cycle_hours_used += duration

    def _add_stop(self, stop_type: str, duration_hours: float, notes: str = "") -> None:
        self._stops.append(
            {"type": stop_type, "duration_hours": duration_hours, "notes": notes}
        )

    def _finalize_and_start_new_day(
        self, rest_duration: float, rest_notes: str
    ) -> None:
        """Close current day with a rest segment, finalize log, begin new day."""
        # The rest period counts as off_duty for this day
        self._add_segment("off_duty", rest_duration, rest_notes)

        # Build totals from segments (durations are always positive floats)
        totals: dict[str, float] = {
            "off_duty": 0.0,
            "sleeper": 0.0,
            "driving": 0.0,
            "on_duty": 0.0,
        }
        day_duration = 0.0
        for seg in self._current_day_segments:
            # Recover duration: parse start/end considering possible midnight wrap
            sh, sm = seg["start"].split(":")
            eh, em = seg["end"].split(":")
            s_dec = int(sh) + int(sm) / 60.0
            e_dec = int(eh) + int(em) / 60.0
            if e_dec < s_dec:  # crossed midnight
                e_dec += 24.0
            dur = e_dec - s_dec
            totals[seg["status"]] += dur
            day_duration += dur

        # Pad to exactly 24h with off_duty if needed
        accounted = sum(totals.values())
        if accounted < 24.0 - 0.001:
            pad = 24.0 - accounted
            totals["off_duty"] += pad
            pad_start = self._to_hhmm(self._clock)
            pad_end = self._to_hhmm(self._clock + pad)
            self._current_day_segments.append(
                {
                    "status": "off_duty",
                    "start": pad_start,
                    "end": pad_end,
                    "notes": "Remaining off duty",
                }
            )
            self._clock += pad

        self._log_sheets.append(
            {
                "date": f"Day {self._day_number}",
                "driver_start_time": self._to_hhmm(self._day_display_start),
                "segments": list(self._current_day_segments),
                "totals": {k: round(v, 4) for k, v in totals.items()},
                "miles_today": round(self._miles_today, 1),
            }
        )

        # Start next day
        self._day_number += 1
        self._day_display_start = self._clock
        self._day_window_start = self._clock
        self._driving_today = 0.0
        self._continuous_driving = 0.0
        self._miles_today = 0.0
        self._current_day_segments = []

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def plan_trip(self) -> dict:
        """
        Calculate the full trip itinerary respecting all HOS rules.

        Returns:
            {"stops": [...], "log_sheets": [...], "total_days": int}
        """
        miles_remaining = float(self.total_miles)
        miles_since_fuel = 0.0

        # Pickup: 1h on-duty at origin
        self._add_segment("on_duty", self.PICKUP_DURATION, "Pre-trip inspection + pickup")
        self._add_stop("pickup", self.PICKUP_DURATION, "Pickup location")

        iteration_guard = 0
        max_iterations = 10_000

        while miles_remaining > 0.01:
            iteration_guard += 1
            if iteration_guard > max_iterations:
                raise RuntimeError("plan_trip exceeded maximum iterations — possible infinite loop")

            # 1. Check 70-hour cycle limit
            if self._cycle_remaining() < 0.5:
                self._add_stop("reset_34h", self.CYCLE_RESET_HOURS, "34-hour cycle reset")
                self._finalize_and_start_new_day(
                    self.CYCLE_RESET_HOURS, "34-hour cycle reset"
                )
                self.cycle_hours_used = 0.0
                continue

            # 2. Check mandatory 30-min break (before 8h continuous driving)
            if self._continuous_driving >= self.BREAK_REQUIRED_AFTER - 0.001:
                self._add_segment("off_duty", self.BREAK_DURATION, "Mandatory 30-min break")
                self._add_stop("rest_30min", self.BREAK_DURATION, "Mandatory 30-min rest break")
                self._continuous_driving = 0.0

            # 3. Check fuel stop
            if miles_since_fuel >= self.FUEL_STOP_INTERVAL_MILES - 0.1:
                self._add_segment("on_duty", self.FUEL_STOP_DURATION, "Fuel stop")
                self._add_stop("fuel", self.FUEL_STOP_DURATION, "Fuel stop")
                miles_since_fuel = 0.0

            # 4. Check if today is exhausted
            available_drive_hours = self._driving_hours_available()
            if available_drive_hours < 0.001:
                self._finalize_and_start_new_day(
                    self.REQUIRED_REST_HOURS, "10-hour mandatory rest"
                )
                continue

            # 5. How much can we drive right now?
            hours_until_break = self.BREAK_REQUIRED_AFTER - self._continuous_driving
            hours_possible = min(
                available_drive_hours,
                self._cycle_remaining(),
                hours_until_break,
            )
            if hours_possible < 0.001:
                self._finalize_and_start_new_day(
                    self.REQUIRED_REST_HOURS, "10-hour mandatory rest"
                )
                continue

            # 6. Drive a segment (capped by remaining miles AND fuel boundary)
            max_miles = hours_possible * self.AVERAGE_SPEED_MPH
            # Cap segment so we stop exactly at the 1000-mile fuel mark
            miles_until_fuel = self.FUEL_STOP_INTERVAL_MILES - miles_since_fuel
            miles_segment = min(miles_remaining, max_miles, miles_until_fuel)
            hours_segment = miles_segment / self.AVERAGE_SPEED_MPH

            self._add_segment("driving", hours_segment, "En route")
            miles_remaining -= miles_segment
            miles_since_fuel += miles_segment

        # Dropoff: 1h on-duty at destination
        self._add_segment("on_duty", self.DROPOFF_DURATION, "Post-trip inspection + dropoff")
        self._add_stop("dropoff", self.DROPOFF_DURATION, "Dropoff location")

        # Finalize last day — pad remaining hours as off_duty
        totals: dict[str, float] = {
            "off_duty": 0.0,
            "sleeper": 0.0,
            "driving": 0.0,
            "on_duty": 0.0,
        }
        for seg in self._current_day_segments:
            sh, sm = seg["start"].split(":")
            eh, em = seg["end"].split(":")
            s_dec = int(sh) + int(sm) / 60.0
            e_dec = int(eh) + int(em) / 60.0
            if e_dec < s_dec:
                e_dec += 24.0
            totals[seg["status"]] += e_dec - s_dec

        accounted = sum(totals.values())
        if accounted < 24.0 - 0.001:
            pad = 24.0 - accounted
            totals["off_duty"] += pad
            pad_start = self._to_hhmm(self._clock)
            pad_end = self._to_hhmm(self._clock + pad)
            self._current_day_segments.append(
                {
                    "status": "off_duty",
                    "start": pad_start,
                    "end": pad_end,
                    "notes": "Remaining off duty",
                }
            )
            self._clock += pad

        self._log_sheets.append(
            {
                "date": f"Day {self._day_number}",
                "driver_start_time": self._to_hhmm(self._day_display_start),
                "segments": list(self._current_day_segments),
                "totals": {k: round(v, 4) for k, v in totals.items()},
                "miles_today": round(self._miles_today, 1),
            }
        )

        return {
            "stops": self._stops,
            "log_sheets": self._log_sheets,
            "total_days": len(self._log_sheets),
        }
