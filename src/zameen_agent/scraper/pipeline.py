"""Fetch a Zameen.com search-results URL, parse, normalise, embed, and upsert
into Postgres.

Usage:
    python -m zameen_agent.scraper.pipeline "<search-url>" --purpose sale
    # or, if installed: zameen-scrape "<search-url>" --purpose rent
"""

from __future__ import annotations

import argparse
import logging
import re
from urllib.parse import urlparse

from psycopg.types.json import Jsonb

from zameen_agent.db import get_connection
from zameen_agent.embeddings import embed_texts, listing_embedding_text
from zameen_agent.scraper.client import PoliteHTTPClient
from zameen_agent.scraper.normalize import normalise
from zameen_agent.scraper.parser import parse_search_results

logger = logging.getLogger(__name__)

# Zameen.com's search-results URLs are namespaced by category, e.g.
# https://www.zameen.com/Houses/Lahore-1-1.html. Verified against a live
# page (2026-08-18) — "Homes" is a mixed category (houses + flats +
# portions, etc.) so it's deliberately left unmapped rather than guessed.
_URL_CATEGORY_TO_PROPERTY_TYPE = {
    "houses": "house",
    "flats": "flat",
    "plots": "plot",
    "farmhouses": "farm house",
    "upperportions": "portion",
    "lowerportions": "portion",
    "rooms": "room",
    "shops": "commercial",
    "offices": "commercial",
    "warehouses": "commercial",
    "factories": "commercial",
    "commercial": "commercial",
}


def _infer_property_type_from_url(search_url: str) -> str | None:
    path_segments = urlparse(search_url).path.strip("/").split("/")
    if not path_segments or not path_segments[0]:
        return None
    category = path_segments[0].lower().replace(" ", "").replace("_", "")
    return _URL_CATEGORY_TO_PROPERTY_TYPE.get(category)


# Second path segment is "<City>-<locationId>-<page>.html", e.g.
# "/Houses/Lahore-1-1.html" -> city "Lahore". Verified against a live URL
# (2026-08-18); multi-word cities (if underscore-joined, per robots.txt city
# names like "Rahim_Yar_Khan") are turned back into spaces on a best-effort
# basis.
_CITY_SEGMENT_RE = re.compile(r"^([A-Za-z_]+)-\d")


def _infer_city_from_url(search_url: str) -> str | None:
    path_segments = urlparse(search_url).path.strip("/").split("/")
    if len(path_segments) < 2:
        return None
    match = _CITY_SEGMENT_RE.match(path_segments[1])
    if not match:
        return None
    return match.group(1).replace("_", " ")

_UPSERT_SQL = """
INSERT INTO listings (
    source_url, external_id, title, description, purpose, property_type,
    city, location, price_pkr, price_raw, area_marla, area_sqft, area_raw,
    bedrooms, bathrooms, agency, posted_date, latitude, longitude, raw, embedding
) VALUES (
    %(source_url)s, %(external_id)s, %(title)s, %(description)s, %(purpose)s, %(property_type)s,
    %(city)s, %(location)s, %(price_pkr)s, %(price_raw)s, %(area_marla)s, %(area_sqft)s, %(area_raw)s,
    %(bedrooms)s, %(bathrooms)s, %(agency)s, %(posted_date)s, %(latitude)s, %(longitude)s, %(raw)s, %(embedding)s
)
ON CONFLICT (source_url) DO UPDATE SET
    external_id   = EXCLUDED.external_id,
    title         = EXCLUDED.title,
    description   = EXCLUDED.description,
    purpose       = EXCLUDED.purpose,
    property_type = EXCLUDED.property_type,
    city          = EXCLUDED.city,
    location      = EXCLUDED.location,
    price_pkr     = EXCLUDED.price_pkr,
    price_raw     = EXCLUDED.price_raw,
    area_marla    = EXCLUDED.area_marla,
    area_sqft     = EXCLUDED.area_sqft,
    area_raw      = EXCLUDED.area_raw,
    bedrooms      = EXCLUDED.bedrooms,
    bathrooms     = EXCLUDED.bathrooms,
    agency        = EXCLUDED.agency,
    posted_date   = EXCLUDED.posted_date,
    latitude      = EXCLUDED.latitude,
    longitude     = EXCLUDED.longitude,
    raw           = EXCLUDED.raw,
    embedding     = EXCLUDED.embedding
"""


def scrape_search_url(
    search_url: str, *, purpose: str | None = None, property_type: str | None = None
) -> int:
    """Fetch one search-results page, parse+normalise+embed its listings, and
    upsert them into Postgres. Returns the number of listings written.

    The full raw record (JSON-LD item or parsed card fields) is stored in the
    `raw` JSONB column, so rows can be re-normalised later — via normalize.py
    changes — without re-fetching the page.

    `property_type`, if not given, is inferred from the search URL's category
    segment (e.g. "/Houses/..." -> "house").
    """
    with PoliteHTTPClient() as client:
        response = client.get(search_url)

    raw_listings = parse_search_results(response.text, search_url)
    if not raw_listings:
        logger.warning("No listings parsed from %s", search_url)
        return 0

    resolved_property_type = property_type or _infer_property_type_from_url(search_url)
    resolved_city = _infer_city_from_url(search_url)
    rows = [
        normalise(
            raw, purpose=purpose, property_type=resolved_property_type, city=resolved_city
        )
        for raw in raw_listings
    ]

    embedding_texts = [
        listing_embedding_text(row["title"], row["description"], row["location"]) for row in rows
    ]
    embeddings = embed_texts(embedding_texts, task_type="RETRIEVAL_DOCUMENT")

    with get_connection() as conn:
        with conn.cursor() as cur:
            for row, embedding in zip(rows, embeddings):
                params = dict(row)
                params["raw"] = Jsonb(params["raw"])
                params["embedding"] = embedding
                cur.execute(_UPSERT_SQL, params)

    logger.info("Upserted %d listings from %s", len(rows), search_url)
    return len(rows)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(
        description="Scrape a Zameen.com search-results URL into Postgres."
    )
    parser.add_argument("search_url", help="Zameen.com search-results URL to scrape")
    parser.add_argument(
        "--purpose",
        choices=["sale", "rent"],
        default=None,
        help="Sale/rent hint used when it can't be inferred from listing text "
        "(e.g. pass explicitly based on which search URL you're scraping)",
    )
    parser.add_argument(
        "--property-type",
        default=None,
        help="Override property type instead of inferring it from the URL's "
        "category segment (e.g. Houses -> house)",
    )
    args = parser.parse_args()
    scrape_search_url(args.search_url, purpose=args.purpose, property_type=args.property_type)


if __name__ == "__main__":
    main()
