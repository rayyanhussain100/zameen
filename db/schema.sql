-- Zameen Agent database schema.
--
-- Source of truth for the data model. Applied automatically by docker-compose
-- (mounted into /docker-entrypoint-initdb.d/) on first container start, or run
-- manually with: psql "$DATABASE_URL" -f db/schema.sql

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS listings (
    id              BIGSERIAL PRIMARY KEY,

    -- Provenance / dedupe key. Upserts key off source_url.
    source_url      TEXT NOT NULL UNIQUE,
    external_id     TEXT,

    -- Core listing fields.
    title           TEXT,
    description     TEXT,
    purpose         TEXT CHECK (purpose IN ('sale', 'rent')),
    property_type   TEXT,               -- e.g. house, flat, plot, farm house, commercial
    city            TEXT,
    location        TEXT,               -- neighbourhood / society / phase, free text

    -- Price. Always normalised to PKR; price_raw keeps the original display string
    -- (e.g. "1.25 Crore", "85 Lakh", "PKR 45,000") for auditing / re-parsing.
    price_pkr       NUMERIC,
    price_raw       TEXT,

    -- Area. Pakistani listings mix Marla/Kanal and sqft; normalise() converts
    -- Kanal -> Marla (1 Kanal = 20 Marla) and stores sqft separately when given.
    area_marla      NUMERIC,
    area_sqft       NUMERIC,
    area_raw        TEXT,

    bedrooms        INT,
    bathrooms       INT,
    agency          TEXT,
    posted_date     DATE,

    latitude        DOUBLE PRECISION,
    longitude       DOUBLE PRECISION,

    -- Full raw scraped record (JSON-LD blob and/or parsed card fields), so rows
    -- can be re-normalised later without re-scraping the page.
    raw             JSONB NOT NULL,

    -- gemini-embedding-001, truncated to 768 dims via output_dimensionality
    -- (MRL) — see embeddings.py. Built from title + description + location.
    embedding       vector(768),

    scraped_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Cosine-distance ANN index for semantic_search. Must match the distance
-- operator used in the query (`<=>`) and the embedding model's normalisation.
CREATE INDEX IF NOT EXISTS listings_embedding_hnsw_idx
    ON listings USING hnsw (embedding vector_cosine_ops);

-- Supporting btree indexes for the read-only SQL tool's common filters.
CREATE INDEX IF NOT EXISTS listings_purpose_idx ON listings (purpose);
CREATE INDEX IF NOT EXISTS listings_city_idx ON listings (city);
CREATE INDEX IF NOT EXISTS listings_price_idx ON listings (price_pkr);

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS listings_set_updated_at ON listings;
CREATE TRIGGER listings_set_updated_at
    BEFORE UPDATE ON listings
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();

-- Recommended (not automated here): create a read-only role for the agent's
-- SQL tool so the guardrail in tools/sql_tool.py is backed by real DB privileges,
-- not just the app-level check.
--
--   CREATE ROLE zameen_readonly LOGIN PASSWORD '<set-a-password>';
--   GRANT CONNECT ON DATABASE zameen TO zameen_readonly;
--   GRANT USAGE ON SCHEMA public TO zameen_readonly;
--   GRANT SELECT ON ALL TABLES IN SCHEMA public TO zameen_readonly;
--   ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO zameen_readonly;
