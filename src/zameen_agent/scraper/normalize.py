"""Maps raw scraped listing dicts onto the `listings` table shape.

Handles the two bits of Pakistani real-estate-listing text that don't parse
with plain float(): prices quoted in Crore/Lakh, and areas quoted in
Marla/Kanal. Unparsable values are left as None rather than guessed.
"""

from __future__ import annotations

import re
from typing import Any

from zameen_agent.scraper.parser import RawListing

CRORE = 10_000_000
LAKH = 100_000
ARAB = 1_000_000_000

# 1 Kanal = 20 Marla (fixed everywhere). Marla <-> sqft is regionally variable
# (225 sqft/marla in some areas, 272.25 in others) so we deliberately do NOT
# cross-convert Marla and sqft — each is only populated when given directly
# in that unit.
MARLA_PER_KANAL = 20

_PRICE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(arab|crore|lakh|lac)?", re.IGNORECASE)
_AREA_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(marla|kanal|sq\.?\s*ft|square\s*feet|sq\.?\s*yd|square\s*yards?)",
    re.IGNORECASE,
)
_BEDS_RE = re.compile(r"(\d+)\s*bed", re.IGNORECASE)
_BATHS_RE = re.compile(r"(\d+)\s*bath", re.IGNORECASE)

_RENT_HINTS = ("/month", "per month", "monthly")

_PROPERTY_TYPE_KEYWORDS = {
    "house": "house",
    "flat": "flat",
    "apartment": "flat",
    "upper portion": "portion",
    "lower portion": "portion",
    "farm house": "farm house",
    "room": "room",
    "penthouse": "flat",
    "plot": "plot",
    "land": "plot",
    "shop": "commercial",
    "office": "commercial",
    "warehouse": "commercial",
    "factory": "commercial",
    "building": "commercial",
}


def parse_price_pkr(raw: str | None) -> float | None:
    """Parse a PKR price string, handling Crore/Lakh/Arab suffixes.

    Examples: "1.25 Crore" -> 12_500_000.0, "85 Lakh" -> 8_500_000.0,
    "PKR 45,000" -> 45_000.0.
    """
    if not raw:
        return None
    text = str(raw).strip().lower().replace(",", "")
    match = _PRICE_RE.search(text)
    if not match:
        return None
    number = float(match.group(1))
    unit = (match.group(2) or "").lower()
    if unit == "crore":
        return number * CRORE
    if unit in ("lakh", "lac"):
        return number * LAKH
    if unit == "arab":
        return number * ARAB
    return number


def parse_area(raw: str | None) -> dict[str, float | None]:
    """Parse an area string into {area_marla, area_sqft}. Kanal is converted
    to Marla; sqft/sq yd are stored as sqft. Only one of the two fields is
    populated, depending on the unit found."""
    result: dict[str, float | None] = {"area_marla": None, "area_sqft": None}
    if not raw:
        return result
    text = str(raw).strip().lower().replace(",", "")
    match = _AREA_RE.search(text)
    if not match:
        return result

    value = float(match.group(1))
    unit = match.group(2).lower()

    if "marla" in unit:
        result["area_marla"] = value
    elif "kanal" in unit:
        result["area_marla"] = value * MARLA_PER_KANAL
    elif "yd" in unit or "yard" in unit:
        result["area_sqft"] = value * 9  # 1 sq yard = 9 sq ft
    else:
        result["area_sqft"] = value

    return result


def infer_purpose(raw: RawListing, *, default: str | None = None) -> str | None:
    """Best-effort sale-vs-rent detection from price text (e.g. ".../Month").
    Prefer passing purpose explicitly from the search URL/page context when
    known — this is only a fallback."""
    price_text = (raw.get("price_raw") or "").lower()
    if any(hint in price_text for hint in _RENT_HINTS):
        return "rent"
    return default


def infer_property_type(title: str | None) -> str | None:
    """Lightweight keyword heuristic over the listing title. Not authoritative
    — refine once real Zameen.com category taxonomy/markup is inspected."""
    if not title:
        return None
    lowered = title.lower()
    for keyword, property_type in _PROPERTY_TYPE_KEYWORDS.items():
        if keyword in lowered:
            return property_type
    return None


def _parse_int(pattern: re.Pattern, text: str | None) -> int | None:
    if not text:
        return None
    match = pattern.search(text)
    return int(match.group(1)) if match else None


def normalise(raw: RawListing, *, purpose: str | None = None) -> dict[str, Any]:
    """Map a raw scraped listing dict (from parser.py) onto `listings` columns.

    `purpose` should be supplied by the caller when known (e.g. derived from
    which search URL was scraped — "Homes for Sale" vs "Homes for Rent");
    falls back to a text heuristic otherwise.
    """
    title = raw.get("title")
    features_text = raw.get("features_raw") or ""

    area = parse_area(raw.get("features_raw") or raw.get("area_raw"))

    return {
        "source_url": raw["source_url"],
        "external_id": raw.get("external_id"),
        "title": title,
        "description": raw.get("description"),
        "purpose": infer_purpose(raw, default=purpose),
        "property_type": raw.get("property_type") or infer_property_type(title),
        "city": raw.get("city"),
        "location": raw.get("location_raw"),
        "price_pkr": parse_price_pkr(raw.get("price_raw")),
        "price_raw": raw.get("price_raw"),
        "area_marla": area["area_marla"],
        "area_sqft": area["area_sqft"],
        "area_raw": raw.get("area_raw") or raw.get("features_raw"),
        "bedrooms": _parse_int(_BEDS_RE, features_text),
        "bathrooms": _parse_int(_BATHS_RE, features_text),
        "agency": raw.get("agency"),
        "posted_date": raw.get("posted_date"),
        "latitude": raw.get("latitude"),
        "longitude": raw.get("longitude"),
        "raw": raw,
    }
