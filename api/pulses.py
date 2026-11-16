"""Scheduled crowd pulses on paths (decision 022): school arrival and dismissal, and ferry arrivals.

Decision 016 leaves paths not_scored. A few places on paths get crowded on a schedule, and the schedules are
published. Within PULSE_RADIUS_M of a school or a ferry landing, path ways are `high` during a pulse window, an
`estimate`. Outside the windows they stay not_scored, never assumed quiet.

- Schools: DOE's school points plus OSM schools DOE doesn't list (etl/load_pulses.py), on DOE school days
  (etl/curated/nycps_calendar_2026_27.json). DOE publishes no bell times for most schools, so the windows are a stated
  default: arrival 7:30-8:30, dismissal 2:20-3:20 (most schools start 8:00-8:40, and the school day is 6 h 20 min).
- Ferries: SeaStreak's arrivals at East 35th St (etl/curated/seastreak_schedule.json), every arrival; NYC Ferry's GTFS
  arrivals only in the weekday commute peaks, since its boats call every few minutes all day and are mostly passing
  through (the reviewer's choice, 2026-11-03). A window runs from FERRY_BEFORE_MIN before an arrival to
  FERRY_AFTER_MIN after it.
"""

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CALENDAR_FILE = ROOT / "etl" / "curated" / "nycps_calendar_2026_27.json"
SEASTREAK_FILE = ROOT / "etl" / "curated" / "seastreak_schedule.json"

PULSE_RADIUS_M = 150
SCHOOL_ARRIVAL = (time(7, 30), time(8, 30))
SCHOOL_DISMISSAL = (time(14, 20), time(15, 20))
FERRY_BEFORE_MIN, FERRY_AFTER_MIN = 2, 8
NYC_FERRY_PEAKS = ((time(7, 0), time(10, 0)), (time(16, 0), time(19, 0)))  # weekday arrivals that count


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime
    basis: str
    # The cause in parts, for the route's `summary.crowds.pulses` (the app writes its crowd line from these, never from
    # the `basis` prose): "ferry" or "school"; the operator or the school's name; the landing (ferries only); the
    # arrival clock (ferries only); "arrival" or "dismissal" (schools only).
    cause: str = ""
    name: str = ""
    place: str | None = None
    arrival: time | None = None
    event: str | None = None


@dataclass(frozen=True)
class Calendar:
    first_day: date
    last_day: date
    no_students: dict  # date -> reason


@cache
def load_calendar(path: Path = CALENDAR_FILE) -> Calendar:
    d = json.loads(path.read_text())
    return Calendar(date.fromisoformat(d["first_day"]), date.fromisoformat(d["last_day"]),
                    {date.fromisoformat(k): v for k, v in d["no_students"].items()})


@cache
def load_seastreak(path: Path = SEASTREAK_FILE) -> dict:
    return json.loads(path.read_text())


def school_day(day: date, cal: Calendar) -> tuple[bool, str]:
    """Whether students attend on this day, and why not when they don't."""
    if day.weekday() >= 5:
        return False, "weekend"
    if not cal.first_day <= day <= cal.last_day:
        return False, "outside the school year"
    if day in cal.no_students:
        return False, cal.no_students[day]
    return True, ""


def school_windows(day: date, cal: Calendar, school: str) -> list[Window]:
    if not school_day(day, cal)[0]:
        return []
    at = lambda t: datetime.combine(day, t)
    fmt = lambda w: f"{w[0]:%H:%M}-{w[1]:%H:%M}"
    return [Window(at(SCHOOL_ARRIVAL[0]), at(SCHOOL_ARRIVAL[1]),
                   f"school arrival at {school} (window {fmt(SCHOOL_ARRIVAL)} assumed, estimate)",
                   cause="school", name=school, event="arrival"),
            Window(at(SCHOOL_DISMISSAL[0]), at(SCHOOL_DISMISSAL[1]),
                   f"school dismissal at {school} (window {fmt(SCHOOL_DISMISSAL)} assumed, estimate)",
                   cause="school", name=school, event="dismissal")]


def ferry_windows(day: date, arrivals: list[time], operator: str, landing: str) -> list[Window]:
    out = []
    for a in arrivals:
        at = datetime.combine(day, a)
        out.append(Window(at - timedelta(minutes=FERRY_BEFORE_MIN), at + timedelta(minutes=FERRY_AFTER_MIN),
                          f"{operator} arrival {a:%H:%M} at {landing} (window -{FERRY_BEFORE_MIN}/+{FERRY_AFTER_MIN} "
                          f"min assumed, estimate)", cause="ferry", name=operator, place=landing, arrival=a))
    return out


def seastreak_times(day: date, sched: dict) -> list[time]:
    """SeaStreak's arrivals at East 35th St on this day, from the timetable in effect."""
    weekend = day.weekday() >= 5
    if day < date.fromisoformat(sched["weekend_effective" if weekend else "weekday_effective"]):
        return []
    rows = sched["weekend_arrivals" if weekend else "weekday_arrivals"]
    return [time.fromisoformat(r["time"]) for r in rows if "days" not in r or day.weekday() in r["days"]]


def nyc_ferry_counts(day: date, arrival: time) -> bool:
    return day.weekday() < 5 and any(a <= arrival < b for a, b in NYC_FERRY_PEAKS)


def active_services(day: date, services, exceptions) -> set[str]:
    """GTFS service ids running on a day: calendar.txt rows (service_id, Mon..Sun flags, start, end), then
    calendar_dates.txt exceptions (service_id, date, 1 added / 2 removed)."""
    on = {sid for sid, days, start, end in services if start <= day <= end and days[day.weekday()]}
    for sid, d, kind in exceptions:
        if d == day:
            (on.add if kind == 1 else on.discard)(sid)
    return on


def gtfs_time(text: str) -> time | None:
    """A GTFS HH:MM:SS; None past midnight (service-day times of 24:00 and later belong to the next day)."""
    h, m, s = (int(x) for x in text.split(":"))
    return time(h, m, s) if h < 24 else None


def hit(at: datetime | None, windows: list[Window]) -> Window | None:
    if at is None:
        return None
    return next((w for w in windows if w.start <= at <= w.end), None)


# --- PostGIS ----------------------------------------------------------------------------------------

_SOURCES = """
SELECT w.way_id, s.id, s.kind, s.name, s.operator, s.gtfs_stop_id
FROM pulse_ways w JOIN pulse_sources s ON s.id = w.source_id
WHERE w.way_id = ANY(%s)
"""


def windows_by_way(conn, way_ids: list[int], day: date) -> dict[int, list[Window]]:
    """The pulse windows on `day` for each of these ways that has any, ferry windows first."""
    if not way_ids or not conn.execute("SELECT to_regclass('pulse_ways') IS NOT NULL").fetchone()[0]:
        return {}
    rows = conn.execute(_SOURCES, (list(way_ids),)).fetchall()
    if not rows:
        return {}
    cal, sea = load_calendar(), load_seastreak()
    by_source: dict[int, list[Window]] = {}
    stops = {r[5] for r in rows if r[4] == "NYC Ferry"}
    nyc: dict[str, list[time]] = {}
    if stops:
        services = [(sid, tuple(days), start, end) for sid, days, start, end in
                    conn.execute("SELECT service_id, days, start_date, end_date FROM ferry_services")]
        exceptions = conn.execute("SELECT service_id, day, kind FROM ferry_service_dates").fetchall()
        running = active_services(day, services, exceptions)
        for stop, arrival in conn.execute(
                "SELECT stop_id, arrival FROM ferry_arrivals WHERE stop_id = ANY(%s) AND service_id = ANY(%s)",
                (list(stops), list(running))):
            nyc.setdefault(stop, []).append(arrival)
    for _, sid, kind, name, operator, stop in rows:
        if sid in by_source:
            continue
        if kind == "school":
            by_source[sid] = school_windows(day, cal, name)
        elif operator == "SeaStreak":
            by_source[sid] = ferry_windows(day, seastreak_times(day, sea), "SeaStreak", name)
        else:
            times = sorted(t for t in nyc.get(stop, []) if nyc_ferry_counts(day, t))
            by_source[sid] = ferry_windows(day, times, "NYC Ferry", name)
    out: dict[int, list[Window]] = {}
    for way_id, sid, kind, *_ in rows:
        out.setdefault(way_id, [])
        out[way_id] += by_source[sid]
    for way_id in out:
        # ferries first, then by start; at the same start SeaStreak's larger commuter boats name the pulse
        out[way_id].sort(key=lambda w: (not w.basis.startswith(("SeaStreak", "NYC Ferry")), w.start,
                                        not w.basis.startswith("SeaStreak")))
    return {k: v for k, v in out.items() if v}
