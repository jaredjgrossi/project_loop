"""Load the crowd inputs and precompute crowd levels per sidewalk way and time band (decision 016).

    uv run python -m etl.load_crowds        (after etl.load_osm and etl.build_corridors)

Follows decision 013's recommendation; the method is ported from its spike scripts. Reads the public downloads in
data/crowds/raw/ (git-ignored):
- MTA subway hourly ridership (5wq4-mkjj) and origin-destination exits (y2qv-fytt, 28vm-gjqr), Sept-Oct 2025 and
  May 2026, matching DOT's count rounds;
- NYC planimetric sidewalk polygons (52n9-sdep, 2022 imagery);
- DOT bi-annual pedestrian counts (cqsj-cfgu), for the eval only;
- DOT automated pedestrian counters (ct66-47at, locations 6up2-gnw8), Aug-Oct 2026.

Writes the tables station_flow, sidewalk_width, sidewalk_crowd, dot_ped_counts, ped_counters and counter_crowd.
Levels are estimates; nothing here is a measured crowd on a given day.
"""

import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg
import shapely
from pyproj import Transformer
from scipy.spatial import cKDTree

from api.crowds import BANDS, HIGH_PCT, MEDIUM_PCT, NEAR_SUBWAY_M, STATION_CUT_M, STATION_SIGMA_M
from etl.load import database_url

RAW = Path(__file__).resolve().parents[1] / "data" / "crowds" / "raw"
FT = 3.28084
TRANSECT_HALF_FT = 80.0
SNAP_FT = 20.0
STUB_FT = 30.0
WIDTH_CLAMP_FT = (5.0, 40.0)
COUNTER_CURRENT_DAYS = 30  # a counter is current if its last data is this close to the download
COUNTER_REACH_M = 400  # paths this close to a current counter, on the same catalog corridor, take its counts
DOT_WINDOW_HOURS = {"am": 2, "pm": 3, "md": 2}  # DOT counts are totals over 7-9am, 4-7pm and Saturday 12-2pm

to2263 = Transformer.from_crs(4326, 2263, always_xy=True)


def xy(lon, lat):
    x, y = to2263.transform(np.asarray(lon, float), np.asarray(lat, float))
    return np.column_stack([x, y])


# --- subway ------------------------------------------------------------------------------

def station_flow() -> pd.DataFrame:
    """Mean persons per hour entering plus exiting, by complex, day type and hour."""
    frames = []
    for tag, start, end in (("fall25", "2025-09-01", "2025-11-01"), ("may26", "2026-05-01", "2026-06-01")):
        e = pd.DataFrame(json.load(open(RAW / "mta" / f"entries_{tag}.json")))
        e = e.astype({"dow": int, "hh": int, "entries": float, "lat": float, "lon": float})
        days = pd.date_range(start, end, inclusive="left")
        ndow = pd.Series(days.day_of_week).map(lambda d: (d + 1) % 7).value_counts()  # Socrata dow: 0 = Sunday
        e["entries"] /= e["dow"].map(ndow)
        x = pd.DataFrame(json.load(open(RAW / "mta" / f"exits_{tag}.json")))
        x["exits"] = x["exits"].astype(float) / (2 if tag == "fall25" else 1)  # OD gives an average day per month
        x["dow"] = x["day_of_week"].map({"Sunday": 0, "Monday": 1, "Tuesday": 2, "Wednesday": 3, "Thursday": 4,
                                         "Friday": 5, "Saturday": 6})
        x = x.rename(columns={"destination_station_complex_id": "station_complex_id", "hour_of_day": "hh"})
        x["hh"] = x["hh"].astype(int)
        m = e.merge(x[["station_complex_id", "dow", "hh", "exits"]], on=["station_complex_id", "dow", "hh"], how="left")
        m["flow"] = m["entries"] + m["exits"].fillna(0)
        m["daytype"] = np.where(m["dow"].between(1, 5), "weekday", np.where(m["dow"] == 6, "saturday", "sunday"))
        frames.append(m)
    m = pd.concat(frames)
    out = (m.groupby(["station_complex_id", "station_complex", "daytype", "hh"])
           .agg(flow=("flow", "mean"), lat=("lat", "mean"), lon=("lon", "mean")).reset_index())
    return out


# --- sidewalk width ---------------------------------------------------------------------------

def sidewalk_width(conn) -> pd.DataFrame:
    """Width in feet per OSM sidewalk way: transects at 25/50/75% cut by the planimetric polygons (013)."""
    feats = json.loads((RAW / "sidewalk" / "52n9-sdep.geojson").read_text())["features"]
    polys = shapely.from_geojson([json.dumps(f["geometry"]) for f in feats])
    polys = shapely.make_valid(shapely.transform(polys, lambda c: np.column_stack(to2263.transform(c[:, 0], c[:, 1]))))
    pstatus = np.array([f["properties"].get("status") for f in feats], dtype=object)
    rows = conn.execute("""SELECT way_id, ST_AsBinary(ST_Transform(geom, 2263)) FROM osm_ways
                           WHERE tags->>'footway' = 'sidewalk'""").fetchall()
    ids = np.array([r[0] for r in rows])
    lines = shapely.from_wkb([r[1] for r in rows])
    lengths = shapely.length(lines)
    fracs = (0.25, 0.5, 0.75)
    way_idx = np.repeat(np.arange(len(lines)), len(fracs))
    d = lengths[way_idx] * np.tile(fracs, len(lines))
    eps = np.minimum(5.0, lengths[way_idx] * 0.1)
    p = shapely.line_interpolate_point(lines[way_idx], d)
    a = shapely.line_interpolate_point(lines[way_idx], np.maximum(d - eps, 0))
    b = shapely.line_interpolate_point(lines[way_idx], np.minimum(d + eps, lengths[way_idx]))
    tx, ty = shapely.get_x(b) - shapely.get_x(a), shapely.get_y(b) - shapely.get_y(a)
    n = np.hypot(tx, ty)
    n[n == 0] = 1
    nx, ny = -ty / n, tx / n
    px, py = shapely.get_x(p), shapely.get_y(p)
    transects = shapely.linestrings(np.stack([np.column_stack([px - nx * TRANSECT_HALF_FT, py - ny * TRANSECT_HALF_FT]),
                                              np.column_stack([px + nx * TRANSECT_HALF_FT, py + ny * TRANSECT_HALF_FT])],
                                             axis=1))
    tree = shapely.STRtree(polys)
    ti, pi = tree.query(transects, predicate="intersects")
    pieces = shapely.intersection(transects[ti], polys[pi])
    order = np.argsort(ti, kind="stable")
    ti_s, pieces_s = ti[order], pieces[order]
    bounds = np.searchsorted(ti_s, np.arange(len(transects) + 1))
    width = np.full(len(transects), np.nan)
    for t in range(len(transects)):
        lo, hi = bounds[t], bounds[t + 1]
        if lo == hi:
            continue
        parts = shapely.get_parts(shapely.line_merge(shapely.union_all(pieces_s[lo:hi])))
        parts = parts[shapely.get_type_id(parts) == 1]
        if len(parts) == 0:
            continue
        dist = shapely.distance(parts, p[t])
        k = int(np.argmin(dist))
        if dist[k] <= SNAP_FT:
            w = shapely.length(parts[k])
            width[t] = np.nan if w >= 2 * TRANSECT_HALF_FT - 1 else w  # transect never left the polygon: open area
    df = pd.DataFrame({"way": way_idx, "width": width})
    out = pd.DataFrame({"way_id": ids, "length_ft": lengths,
                        "width_ft": df.groupby("way")["width"].median().reindex(range(len(ids))).values})
    mid = shapely.line_interpolate_point(lines, 0.5, normalized=True)
    wi, wp = tree.query(mid, predicate="within")
    st = pd.Series(pstatus[wp], index=wi)
    out["polygon_status"] = st[~st.index.duplicated()].reindex(range(len(ids))).values
    # Corner stubs read the cross street's sidewalk: inherit the longest touching neighbor's width.
    stubs = np.where(lengths < STUB_FT)[0]
    near = shapely.STRtree(lines).query(lines[stubs], predicate="dwithin", distance=1.0)
    best: dict[int, tuple[float, float]] = {}
    for s_i, n_i in zip(stubs[near[0]], near[1]):
        if n_i != s_i and lengths[n_i] >= STUB_FT and np.isfinite(out.at[n_i, "width_ft"]):
            if lengths[n_i] > best.get(s_i, (0, 0))[0]:
                best[s_i] = (lengths[n_i], out.at[n_i, "width_ft"])
    out["width_source"] = np.where(np.isfinite(out["width_ft"]), "transect", "none")
    for s_i, (_, w) in best.items():
        out.at[s_i, "width_ft"] = w
        out.at[s_i, "width_source"] = "neighbor"
    out["width_ft"] = out["width_ft"].clip(*WIDTH_CLAMP_FT)
    return out


# --- crowd levels per sidewalk way and band ------------------------------------------------------

def sidewalk_crowd(conn, flow: pd.DataFrame, width: pd.DataFrame) -> pd.DataFrame:
    rows = conn.execute("""SELECT way_id, ST_X(ST_LineInterpolatePoint(geom, 0.5)), ST_Y(ST_LineInterpolatePoint(geom, 0.5))
                           FROM osm_ways WHERE tags->>'footway' = 'sidewalk'""").fetchall()
    ways = pd.DataFrame(rows, columns=["way_id", "lon", "lat"]).merge(width[["way_id", "width_ft"]], on="way_id")
    way_xy = xy(ways["lon"], ways["lat"])
    st = flow.groupby("station_complex_id")[["lat", "lon"]].mean()
    st_xy = xy(st["lon"], st["lat"])
    tree = cKDTree(st_xy)
    nearest_ft, _ = tree.query(way_xy)
    sigma, cut = STATION_SIGMA_M * FT, STATION_CUT_M * FT
    out = []
    for band, (daytype, hours, _) in BANDS.items():
        f = (flow[(flow["daytype"] == daytype) & flow["hh"].isin(hours)]
             .groupby("station_complex_id")["flow"].mean().reindex(st.index, fill_value=0).values)
        g = np.zeros(len(ways))
        for i, nb in enumerate(tree.query_ball_point(way_xy, cut)):
            if nb:
                dd = np.hypot(*(st_xy[nb] - way_xy[i]).T)
                g[i] = (f[nb] * np.exp(-0.5 * (dd / sigma) ** 2)).sum()
        per_ft = g / ways["width_ft"].fillna(ways["width_ft"].median()).values
        near = nearest_ft / FT <= NEAR_SUBWAY_M
        hi, md = np.percentile(per_ft[near], HIGH_PCT), np.percentile(per_ft[near], MEDIUM_PCT)
        level = np.where(~near, "low", np.where(per_ft >= hi, "high", np.where(per_ft >= md, "medium", "low")))
        basis = np.where(~near, "far from the subway (assumption)", "subway ridership within 800 m")
        out.append(pd.DataFrame({"way_id": ways["way_id"], "band": band, "volume": g.round(1), "per_ft": per_ft.round(2),
                                 "nearest_station_m": (nearest_ft / FT).round(), "level": level, "basis": basis}))
    return pd.concat(out)


# --- DOT counts (eval) and automated counters ------------------------------------------------------

def dot_counts() -> pd.DataFrame:
    d = pd.read_csv(RAW / "dot" / "cqsj-cfgu.csv")
    pt = shapely.from_wkt(d["the_geom"])
    base = pd.DataFrame({"site": d["loc"], "lon": shapely.get_x(pt), "lat": shapely.get_y(pt), "borough": d["borough"],
                         "street": d["street_nam"]})
    base["kind"] = np.where(base["borough"].str.contains("Bridge"), "bridge",
                            np.where(base["street"].str.contains("Greenway", case=False), "greenway", "street"))
    long = []
    for col in [c for c in d.columns if c.rsplit("_", 1)[-1] in ("am", "pm", "md") and c[:3] in ("may", "oct", "sep", "jun")]:
        vals = pd.to_numeric(d[col].astype(str).str.replace(",", ""), errors="coerce").replace(0, np.nan)
        rnd = col.rsplit("_", 1)[0].replace("_", "")  # "may_07" and "may26" -> "may07", "may26"
        long.append(base.assign(round=rnd, period=col.rsplit("_", 1)[1], count=vals.values))
    return pd.concat(long).dropna(subset=["count"])


def counters(conn, snapshot: date) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Current pedestrian counters and their mean people per hour by day type and hour, mapped to nearby paths."""
    meta = pd.DataFrame(json.load(open(RAW / "sensors" / "6up2-gnw8.json")))
    meta = meta[meta["travelmodes"] == "pedestrian"].drop_duplicates("id")
    meta["lastdata"] = pd.to_datetime(meta["lastdata"])
    meta["current"] = (pd.Timestamp(snapshot) - meta["lastdata"]).dt.days <= COUNTER_CURRENT_DAYS
    counts = pd.DataFrame(json.load(open(RAW / "sensors" / "ped_counts_aug_oct26.json")))
    counts = counts.astype({"dow": int, "hh": int, "counts": float})
    days = pd.date_range("2026-08-01", "2026-11-01", inclusive="left")
    ndow = pd.Series(days.day_of_week).map(lambda d: (d + 1) % 7).value_counts()
    counts["per_hour"] = counts["counts"] / counts["dow"].map(ndow)
    counts["daytype"] = np.where(counts["dow"].between(1, 5), "weekday", np.where(counts["dow"] == 6, "saturday", "sunday"))
    hourly = counts.groupby(["sensor_id", "daytype", "hh"])["per_hour"].mean().reset_index()
    cover = []
    for _, c in meta[meta["current"]].iterrows():
        ways = conn.execute(
            """WITH pt AS (SELECT ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326) AS g),
                    cor AS (SELECT id FROM corridors, pt WHERE ST_DWithin(geom::geography, pt.g::geography, 50)
                            ORDER BY geom <-> pt.g LIMIT 1)
               SELECT w.way_id FROM osm_ways w, pt
               WHERE ST_DWithin(w.geom::geography, pt.g::geography, %(reach)s)
                 AND w.highway IN ('footway', 'path', 'cycleway', 'pedestrian', 'track')
                 AND coalesce(w.tags->>'footway', '') NOT IN ('sidewalk', 'crossing')
                 AND (NOT EXISTS (SELECT 1 FROM cor) OR EXISTS (
                      SELECT 1 FROM corridors k, cor WHERE k.id = cor.id AND ST_DWithin(k.geom, w.geom, 0.0001)))""",
            {"lon": float(c["lon"]), "lat": float(c["lat"]), "reach": COUNTER_REACH_M}).fetchall()
        cover += [(w, c["id"]) for (w,) in ways]
    return meta, hourly, pd.DataFrame(cover, columns=["way_id", "sensor_id"])


SCHEMA = """
DROP TABLE IF EXISTS station_flow, sidewalk_width, sidewalk_crowd, dot_ped_counts, ped_counters, counter_crowd, counter_ways;
CREATE TABLE station_flow (complex_id text, name text, daytype text, hour int, flow double precision,
                           lat double precision, lon double precision, source text NOT NULL);
CREATE TABLE sidewalk_width (way_id bigint PRIMARY KEY, length_ft double precision, width_ft double precision,
                             width_source text, polygon_status text, source text NOT NULL);
CREATE TABLE sidewalk_crowd (way_id bigint, band text, volume double precision, per_ft double precision,
                             nearest_station_m double precision, level text, basis text, PRIMARY KEY (way_id, band));
CREATE TABLE dot_ped_counts (site int, lon double precision, lat double precision, borough text, street text, kind text,
                             round text, period text, count double precision, source text NOT NULL);
CREATE TABLE ped_counters (sensor_id text PRIMARY KEY, name text, lon double precision, lat double precision,
                           first_data timestamptz, last_data timestamptz, current boolean, source text NOT NULL);
CREATE TABLE counter_crowd (sensor_id text, daytype text, hour int, per_hour double precision, PRIMARY KEY (sensor_id, daytype, hour));
CREATE TABLE counter_ways (way_id bigint, sensor_id text, PRIMARY KEY (way_id, sensor_id));
"""


def copy(conn, table: str, df: pd.DataFrame) -> None:
    with conn.cursor().copy(f"COPY {table} ({', '.join(df.columns)}) FROM STDIN") as cp:
        for row in df.itertuples(index=False):
            cp.write_row([None if (isinstance(v, float) and np.isnan(v)) else v for v in row])


def main() -> int:
    for need in ("mta/entries_fall25.json", "sidewalk/52n9-sdep.geojson", "dot/cqsj-cfgu.csv", "sensors/6up2-gnw8.json",
                 "sensors/ped_counts_aug_oct26.json"):
        if not (RAW / need).exists():
            print(f"Missing {RAW / need}. See decision 013 for the downloads.", file=sys.stderr)
            return 1
    with psycopg.connect(database_url(), autocommit=True) as conn:
        print("Station flow ...", flush=True)
        flow = station_flow()
        print("Sidewalk widths (a few minutes) ...", flush=True)
        width = sidewalk_width(conn)
        print("Crowd levels per sidewalk way and band ...", flush=True)
        crowd = sidewalk_crowd(conn, flow, width)
        dot = dot_counts()
        meta, hourly, cover = counters(conn, date(2026, 11, 1))
        with conn.transaction():
            conn.execute(SCHEMA)
            copy(conn, "station_flow", flow.rename(columns={"station_complex_id": "complex_id", "station_complex": "name",
                                                            "hh": "hour"})[["complex_id", "name", "daytype", "hour", "flow",
                                                                            "lat", "lon"]].assign(
                source="MTA 5wq4-mkjj entries + y2qv-fytt/28vm-gjqr exits, Sep-Oct 2025 and May 2026"))
            copy(conn, "sidewalk_width", width.assign(source="NYC planimetric sidewalk 52n9-sdep (2022 imagery)"))
            copy(conn, "sidewalk_crowd", crowd)
            copy(conn, "dot_ped_counts", dot.assign(source="NYC DOT bi-annual pedestrian counts cqsj-cfgu"))
            copy(conn, "ped_counters", meta.rename(columns={"id": "sensor_id", "firstdata": "first_data",
                                                            "lastdata": "last_data"})[
                ["sensor_id", "name", "lon", "lat", "first_data", "last_data", "current"]].assign(
                source="NYC DOT automated counts ct66-47at (locations 6up2-gnw8)"))
            copy(conn, "counter_crowd", hourly.rename(columns={"hh": "hour"}))
            copy(conn, "counter_ways", cover.drop_duplicates())
            conn.execute("CREATE INDEX ON sidewalk_crowd (way_id)")
    w = width["width_ft"]
    print(f"sidewalk widths: {w.notna().mean():.1%} of ways, median {w.median():.1f} ft")
    for band in BANDS:
        c = crowd[crowd["band"] == band]["level"].value_counts(normalize=True)
        print(f"  {band:16s} " + ", ".join(f"{k} {v:.0%}" for k, v in c.items()))
    cur = meta[meta["current"]]
    print(f"pedestrian counters: {len(meta)} listed, {len(cur)} current ({', '.join(cur['name'])}); "
          f"{cover['way_id'].nunique()} path ways covered")
    return 0


if __name__ == "__main__":
    sys.exit(main())
