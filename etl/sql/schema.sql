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
