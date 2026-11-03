-- Source tables. Every row keeps where it came from (source_dataset_id,
-- source_row_id, source_updated_at), when we loaded it (loaded_at), and the
-- untouched source row (raw). Geometry is stored in SRID 4326; project to
-- EPSG:2263 (feet) for distance and area math.

CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS parks (
    id                 bigserial PRIMARY KEY,
    source_dataset_id  text        NOT NULL,
    source_row_id      text,
    source_updated_at  timestamptz,
    loaded_at          timestamptz NOT NULL,
    raw                jsonb       NOT NULL,
    source_key         text,
    name               text,
    borough            text,
    typecategory       text,
    subcategory        text,
    park_class         text,
    jurisdiction       text,
    address            text,
    acres              double precision,
    waterfront         boolean,
    acquisition_date   date,
    geom_was_invalid   boolean     NOT NULL DEFAULT false, -- source polygon needed ST_MakeValid
    geom               geometry(MultiPolygon, 4326) NOT NULL
);
ALTER TABLE parks ADD COLUMN IF NOT EXISTS geom_was_invalid boolean NOT NULL DEFAULT false;
CREATE INDEX IF NOT EXISTS parks_geom_idx ON parks USING gist (geom);

CREATE TABLE IF NOT EXISTS drinking_fountains (
    id                 bigserial PRIMARY KEY,
    source_dataset_id  text        NOT NULL,
    source_row_id      text,
    source_updated_at  timestamptz,
    loaded_at          timestamptz NOT NULL,
    raw                jsonb       NOT NULL,
    source_key         text,
    fountain_type      text,
    position           text,
    borough            text,
    park_id            text,
    property_name      text,
    description        text,
    feature_status     text,
    usable             boolean     NOT NULL,
    skip_reason        text,
    geom               geometry(Point, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS drinking_fountains_geom_idx ON drinking_fountains USING gist (geom);

CREATE TABLE IF NOT EXISTS public_restrooms (
    id                 bigserial PRIMARY KEY,
    source_dataset_id  text        NOT NULL,
    source_row_id      text,
    source_updated_at  timestamptz,
    loaded_at          timestamptz NOT NULL,
    raw                jsonb       NOT NULL,
    facility_name      text,
    location_type      text,
    operator           text,
    status             text,
    open_schedule      text,
    hours_of_operation text,
    accessibility      text,
    restroom_type      text,
    changing_stations  text,
    additional_notes   text,
    website            text,
    lat                double precision NOT NULL,
    lon                double precision NOT NULL,
    geom               geometry(Point, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS public_restrooms_geom_idx ON public_restrooms USING gist (geom);

-- Street and path geometry from the NYC OpenStreetMap extract (one row per OSM way).
-- Used for grid-angle estimation now, and for corridors, greenways and crossings later.
CREATE TABLE IF NOT EXISTS osm_ways (
    way_id             bigint      PRIMARY KEY,
    source_dataset_id  text        NOT NULL,
    source_row_id      text        NOT NULL,
    source_updated_at  timestamptz,           -- when Geofabrik's snapshot was taken
    loaded_at          timestamptz NOT NULL,
    highway            text        NOT NULL,
    name               text,
    tags               jsonb       NOT NULL,
    geom               geometry(LineString, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS osm_ways_geom_idx ON osm_ways USING gist (geom);
CREATE INDEX IF NOT EXISTS osm_ways_highway_idx ON osm_ways (highway);

-- OSM natural=coastline ways (tidal shoreline, which in NYC includes the East and Harlem Rivers): waterfront share.
CREATE TABLE IF NOT EXISTS osm_coastline (
    way_id             bigint      PRIMARY KEY,
    source_dataset_id  text        NOT NULL,
    source_row_id      text        NOT NULL,
    source_updated_at  timestamptz,
    loaded_at          timestamptz NOT NULL,
    geom               geometry(LineString, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS osm_coastline_geom_idx ON osm_coastline USING gist (geom);

-- OSM park areas (leisure=park or nature_reserve): park anchors for the generator (decision 012). Unlike Parks
-- Properties they include Hudson River Park, Brooklyn Bridge Park and Governors Island.
CREATE TABLE IF NOT EXISTS osm_parks (
    area_id            bigint      PRIMARY KEY,  -- osmium area id (from a closed way or a multipolygon relation)
    source_dataset_id  text        NOT NULL,
    source_row_id      text        NOT NULL,
    source_updated_at  timestamptz,
    loaded_at          timestamptz NOT NULL,
    name               text,
    leisure            text        NOT NULL,
    geom               geometry(MultiPolygon, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS osm_parks_geom_idx ON osm_parks USING gist (geom);

-- Routes as shown to a runner, and what the runner said about them (decision 014). generated_routes keeps the parsed
-- request, the route's metric vector and dimensions, its stretches, and the generation timing, so a rating can be
-- traced to exactly what was scored.
CREATE TABLE IF NOT EXISTS generated_routes (
    id            text        PRIMARY KEY,
    created_at    timestamptz NOT NULL DEFAULT now(),
    constraints   jsonb       NOT NULL,           -- RunConstraints as parsed and shown back
    rank          integer     NOT NULL,
    method        text        NOT NULL,
    kind          text        NOT NULL,           -- loop | out_and_back | lollipop
    label         text        NOT NULL,
    score         double precision NOT NULL,
    metrics       jsonb       NOT NULL,           -- Candidate.metric_vector()
    dimensions    jsonb       NOT NULL,           -- ranking dimensions with status measured / estimate / not_scored
    stretches     jsonb       NOT NULL,           -- api/segments.py features
    elevation     jsonb,                          -- api/elevation.py profile (estimate)
    timing        jsonb,
    geom          geometry(LineString, 4326) NOT NULL
);
CREATE TABLE IF NOT EXISTS route_feedback (
    id             serial      PRIMARY KEY,
    route_id       text        NOT NULL REFERENCES generated_routes(id),
    created_at     timestamptz NOT NULL DEFAULT now(),
    ran_it         boolean     NOT NULL,
    rating         smallint    CHECK (rating BETWEEN 1 AND 5),
    ran_at         timestamptz,
    issues         text[]      NOT NULL DEFAULT '{}',
    stretch_issues jsonb       NOT NULL DEFAULT '[]',
    note           text        CHECK (char_length(note) <= 500),
    CHECK ((ran_it AND rating IS NOT NULL) OR (NOT ran_it AND rating IS NULL))
);
CREATE INDEX IF NOT EXISTS route_feedback_route_idx ON route_feedback (route_id);

-- "Crowded" reports, for the route or a stretch, with the crowd level shown there and the hour run (decision 016).
-- Kept to calibrate crowd levels later. No location beyond the stretch's name and index.
CREATE TABLE IF NOT EXISTS crowd_reports (
    id            serial      PRIMARY KEY,
    route_id      text        NOT NULL REFERENCES generated_routes(id),
    reported_at   timestamptz NOT NULL DEFAULT now(),
    stretch       integer,                        -- NULL: the whole route
    stretch_name  text,
    level_shown   text,                           -- low | medium | high, NULL when not scored
    band          text,
    hour          smallint    CHECK (hour BETWEEN 0 AND 23),
    weekday       smallint    CHECK (weekday BETWEEN 0 AND 6)   -- Monday = 0
);

-- "Closed or blocked" reports on a stretch (decision 017), with the stretch's geometry from the route as shown, so a
-- reviewer can confirm one into closures. A report never closes a path by itself.
CREATE TABLE IF NOT EXISTS closure_reports (
    id            serial      PRIMARY KEY,
    route_id      text        NOT NULL REFERENCES generated_routes(id),
    reported_at   timestamptz NOT NULL DEFAULT now(),
    stretch       integer,                        -- NULL: the whole route (can't be confirmed: no place)
    stretch_name  text,
    ran_at        timestamptz,
    note          text,
    status        text        NOT NULL DEFAULT 'reported' CHECK (status IN ('reported', 'confirmed', 'rejected')),
    closure_id    integer,                        -- closures.id once confirmed
    geom          geometry(LineString, 4326)
);

-- Known closures (decision 017): no route may pass through an applied one (api/closures.py). corridor_gap rows are
-- rebuilt by etl/build_closures.py from the corridor catalog, including the gaps it did not apply and why; curated rows
-- are reloaded from routing/curated_closures.geojson; report rows come from confirmed closure_reports and are kept.
CREATE TABLE IF NOT EXISTS closures (
    id                 serial      PRIMARY KEY,
    kind               text        NOT NULL,
    name               text        NOT NULL,
    reason             text        NOT NULL,
    source             text        NOT NULL,
    trust              text        NOT NULL CHECK (trust IN ('verified', 'listed', 'seasonal_or_closed')),
    applied            boolean     NOT NULL,
    not_applied_reason text,
    in_router          boolean     NOT NULL DEFAULT false,  -- given to GraphHopper as an impassable area
    corridor_gap_id    integer,                             -- corridor_gaps.id (no FK: the catalog is rebuilt)
    report_id          integer     REFERENCES closure_reports(id),
    link_m             double precision,                    -- length of the missing link
    walkable_along_m   double precision,                    -- longest walkable OSM way inside the strip
    active_until       date,                                -- NULL: until removed
    curated_id         text,                                -- routing/curated_closures.geojson feature id
    checked_on         date,                                -- curated: when the sources were last checked
    review_by          date,                                -- curated: check again by then (the eval fails after)
    created_at         timestamptz NOT NULL DEFAULT now(),
    geom               geometry(Polygon, 4326),             -- NULL when the link is too short to draw
    CHECK (NOT applied OR geom IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS closures_geom_idx ON closures USING gist (geom);
ALTER TABLE closures ADD COLUMN IF NOT EXISTS curated_id text;
ALTER TABLE closures ADD COLUMN IF NOT EXISTS checked_on date;
ALTER TABLE closures ADD COLUMN IF NOT EXISTS review_by date;
ALTER TABLE closures DROP CONSTRAINT IF EXISTS closures_kind_check;
ALTER TABLE closures ADD CONSTRAINT closures_kind_check CHECK (kind IN ('corridor_gap', 'curated', 'report'));
