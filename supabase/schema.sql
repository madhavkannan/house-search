-- Run this once in the Supabase SQL editor before the first screener run.
-- Project: https://app.supabase.com → SQL Editor → New query

-- Listings: written by the Python screener, read by the Next.js web app
CREATE TABLE IF NOT EXISTS listings (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source        TEXT NOT NULL,           -- 'propertyguru' | '99co'
  source_id     TEXT NOT NULL,
  url           TEXT NOT NULL,
  project_name  TEXT,
  address       TEXT,
  postal_code   TEXT,
  district      TEXT,
  price         INTEGER,
  bedrooms      INTEGER,
  bathrooms     INTEGER,
  size_sqft     REAL,
  tenure        TEXT,
  image_url     TEXT,
  shelter_status TEXT DEFAULT 'unverified',
  nearby_schools TEXT[],
  nearby_mrt     TEXT[],
  geocode_ok    BOOLEAN DEFAULT FALSE,
  lat           REAL,
  lng           REAL,
  first_seen_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(source, source_id)
);

-- Feed index
CREATE INDEX IF NOT EXISTS idx_listings_first_seen ON listings(first_seen_at DESC);

-- Shared favorites: one table, no per-user auth needed (2 users, shared list)
CREATE TABLE IF NOT EXISTS favorites (
  listing_id UUID PRIMARY KEY REFERENCES listings(id) ON DELETE CASCADE,
  favorited_at TIMESTAMPTZ DEFAULT NOW()
);

-- Disable RLS (private tool; URL is the only access control)
ALTER TABLE listings DISABLE ROW LEVEL SECURITY;
ALTER TABLE favorites DISABLE ROW LEVEL SECURITY;
