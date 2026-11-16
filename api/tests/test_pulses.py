from datetime import date, datetime, time

import pytest

from api.pulses import (
    CALENDAR_FILE, SEASTREAK_FILE, Window, active_services, ferry_windows, hit, load_calendar, load_seastreak,
    nyc_ferry_counts, school_day, school_windows, seastreak_times,
)

CAL = load_calendar(CALENDAR_FILE)
SEA = load_seastreak(SEASTREAK_FILE)


def test_school_days_follow_the_doe_calendar():
    assert school_day(date(2026, 11, 4), CAL) == (True, "")  # an ordinary Wednesday
    assert school_day(date(2026, 11, 3), CAL) == (False, "Election Day, school in session remotely")
    assert school_day(date(2026, 11, 7), CAL)[0] is False  # Saturday
    assert school_day(date(2026, 9, 9), CAL)[0] is False  # before the first day
    assert school_day(date(2027, 6, 29), CAL)[0] is False  # after the last day
    assert school_day(date(2026, 12, 30), CAL)[0] is False  # winter recess


def test_school_windows_are_arrival_and_dismissal_on_school_days_only():
    w = school_windows(date(2026, 11, 4), CAL, "P.S. 281 - The River School")
    assert [(x.start.time(), x.end.time()) for x in w] == [(time(7, 30), time(8, 30)), (time(14, 20), time(15, 20))]
    assert all("estimate" in x.basis or "assumed" in x.basis for x in w)
    assert school_windows(date(2026, 11, 3), CAL, "any") == []


def test_ferry_windows_run_from_two_minutes_before_to_eight_after_each_arrival():
    w = ferry_windows(date(2026, 11, 4), [time(8, 0)], "SeaStreak", "East 35th St")
    assert (w[0].start, w[0].end) == (datetime(2026, 11, 4, 7, 58), datetime(2026, 11, 4, 8, 8))
    assert "SeaStreak" in w[0].basis and "08:00" in w[0].basis


def test_seastreak_times_by_day():
    wed, thu, sat = seastreak_times(date(2026, 11, 4), SEA), seastreak_times(date(2026, 11, 5), SEA), \
        seastreak_times(date(2026, 11, 7), SEA)
    assert time(8, 0) in wed and time(21, 40) in wed and time(22, 25) not in wed
    assert time(22, 25) in thu and time(21, 40) not in thu
    assert sat[0] == time(10, 15) and time(8, 0) not in sat
    assert seastreak_times(date(2026, 9, 1), SEA) == []  # before the timetable took effect


def test_nyc_ferry_arrivals_count_only_in_weekday_peaks():
    wed = date(2026, 11, 4)
    assert nyc_ferry_counts(wed, time(8, 5)) and nyc_ferry_counts(wed, time(17, 30))
    assert not nyc_ferry_counts(wed, time(10, 30)) and not nyc_ferry_counts(wed, time(19, 0))
    assert not nyc_ferry_counts(date(2026, 11, 7), time(8, 5))  # Saturday


def test_active_gtfs_services_use_calendar_and_exceptions():
    services = [("1", (1, 1, 1, 1, 1, 0, 0), date(2026, 11, 2), date(2027, 12, 31)),
                ("2", (0, 0, 0, 0, 0, 1, 1), date(2026, 11, 2), date(2027, 12, 31))]
    exceptions = [("1", date(2026, 11, 26), 2), ("2", date(2026, 11, 26), 1)]  # Thanksgiving runs the weekend service
    assert active_services(date(2026, 11, 4), services, exceptions) == {"1"}
    assert active_services(date(2026, 11, 7), services, exceptions) == {"2"}
    assert active_services(date(2026, 11, 26), services, exceptions) == {"2"}
    assert active_services(date(2026, 10, 1), services, exceptions) == set()


def test_hit_finds_the_window_covering_a_moment():
    w = [Window(datetime(2026, 11, 4, 7, 58), datetime(2026, 11, 4, 8, 8), "ferry"),
         Window(datetime(2026, 11, 4, 7, 30), datetime(2026, 11, 4, 8, 30), "school")]
    assert hit(datetime(2026, 11, 4, 8, 5), w).basis == "ferry"  # the first listed wins
    assert hit(datetime(2026, 11, 4, 8, 20), w).basis == "school"
    assert hit(datetime(2026, 11, 4, 9, 0), w) is None and hit(None, w) is None


@pytest.mark.parametrize("path", [CALENDAR_FILE, SEASTREAK_FILE])
def test_curated_schedules_carry_sources_trust_and_review_dates(path):
    import json

    d = json.loads(path.read_text())
    assert d["trust"] == "listed" and date.fromisoformat(d["checked_on"]) < date.fromisoformat(d["review_by"])
    srcs = [d["source"]] if "source" in d else list(d["sources"].values())
    assert srcs and all(s.startswith("https://") for s in srcs)


def test_windows_carry_the_cause_in_parts_for_the_crowd_line():
    f = ferry_windows(date(2026, 11, 4), [time(8, 0)], "SeaStreak", "East 35th St")[0]
    assert (f.cause, f.name, f.place, f.arrival, f.event) == ("ferry", "SeaStreak", "East 35th St", time(8, 0), None)
    arrival, dismissal = school_windows(date(2026, 11, 4), CAL, "United Nations International School")
    assert (arrival.cause, arrival.name, arrival.place, arrival.arrival, arrival.event) == \
        ("school", "United Nations International School", None, None, "arrival")
    assert dismissal.event == "dismissal"
