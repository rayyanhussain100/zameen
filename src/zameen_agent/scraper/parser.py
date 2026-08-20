"""Parses a Zameen.com search-results page into raw listing dicts.

Strategy: try JSON-LD structured data first (more stable across frontend
redesigns than CSS class names), and fall back to CSS selectors against the
server-rendered listing cards. Both paths return the same raw-dict shape,
which normalize.normalise() then maps onto the `listings` table.

Verified against a live page (https://www.zameen.com/Houses/Lahore-1-1.html,
fetched 2026-08-18): search-results pages carry exactly one JSON-LD block, a
`BreadcrumbList` — no per-listing structured data. The 25 listing cards on
that page are plain server-rendered HTML, addressable via stable
`aria-label` attributes (Zameen hashes its CSS class names per build, e.g.
`class="a37d52f0"`, but `aria-label` values are semantic and consistent —
prefer them over classes). The CSS fallback below is therefore the primary
path for search-results pages in practice; the JSON-LD path is kept as a
defensive first pass and because listing *detail* pages (not scraped by this
pipeline yet) commonly do carry Product/Offer JSON-LD — its exact `@type`(s)
there are still unverified, see the TODO on _LISTING_JSON_LD_TYPES below.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterator

from selectolax.parser import HTMLParser, Node

RawListing = dict[str, Any]

_BASE_URL = "https://www.zameen.com"

# Trailing "-<propertyId>-<locationId>-<page>.html" segment of every listing
# detail URL, e.g. ".../..._lahore-54478282-3684-1.html" -> propertyId 54478282.
_LISTING_ID_RE = re.compile(r"-(\d+)-\d+-\d+\.html$")


def parse_search_results(html: str, page_url: str) -> list[RawListing]:
    """Parse one search-results page into a list of raw listing dicts."""
    tree = HTMLParser(html)

    listings = _parse_json_ld(tree, page_url)
    if listings:
        return listings

    return _parse_listing_cards(tree, page_url)


# --- JSON-LD path ------------------------------------------------------------


def _parse_json_ld(tree: HTMLParser, page_url: str) -> list[RawListing]:
    results: list[RawListing] = []
    for script_node in tree.css('script[type="application/ld+json"]'):
        raw_text = script_node.text()
        if not raw_text:
            continue
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            continue
        for item in _iter_json_ld_items(data):
            listing = _json_ld_item_to_raw(item, page_url)
            if listing is not None:
                results.append(listing)
    return results


def _iter_json_ld_items(data: Any) -> Iterator[dict]:
    if isinstance(data, list):
        for item in data:
            yield from _iter_json_ld_items(item)
    elif isinstance(data, dict):
        graph = data.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                yield from _iter_json_ld_items(item)
        else:
            yield data


# TODO(json-ld): unverified for Zameen.com *detail* pages (search-results
# pages, confirmed live, only emit a BreadcrumbList — see module docstring).
# If this pipeline is later pointed at detail-page URLs, inspect one and
# confirm/replace these candidate @type values and the field mapping below.
_LISTING_JSON_LD_TYPES = {"Product", "RealEstateListing", "Residence", "House", "Apartment"}


def _json_ld_item_to_raw(item: dict, page_url: str) -> RawListing | None:
    if item.get("@type") not in _LISTING_JSON_LD_TYPES:
        return None

    offers = item.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    price_spec = offers.get("priceSpecification") or {}
    address = item.get("address") or {}

    return {
        "source_url": item.get("url") or page_url,
        "external_id": item.get("sku") or item.get("productID"),
        "title": item.get("name"),
        "description": item.get("description"),
        "price_raw": offers.get("price") or price_spec.get("price"),
        "location_raw": address.get("streetAddress") or address.get("addressLocality"),
        "city": address.get("addressRegion") or address.get("addressLocality"),
        "_source": "json-ld",
        "_json_ld": item,
    }


# --- CSS fallback path --------------------------------------------------------
#
# Selectors below were read off a live search-results page (view-source,
# 2026-08-18) — not guessed. Each listing card is a `<li aria-label="Listing"
# role="article">`; fields inside it are addressable by aria-label
# regardless of the (hashed, build-specific) class names Zameen ships:
#
#   <li aria-label="Listing" role="article">
#     <a aria-label="Listing link" href="/Property/...-<id>-<locId>-1.html">
#     <h2 aria-label="Title">...</h2>
#     <span aria-label="Currency">PKR</span> <span aria-label="Price">4.65 Crore</span>
#     <div aria-label="Location">Central Park - Block A, Central Park Housing Scheme</div>
#     <span aria-label="Beds">6</span> <span aria-label="Baths">6</span> <span aria-label="Area">10 Marla</span>
#     <span aria-label="Listing creation date">Added: 7 minutes ago</span>
#
# Two caveats observed on the live page, both handled below:
#   - the search-results page also renders ~2 "featured project" cards that
#     share Title/Price aria-labels but are NOT inside an
#     `li[aria-label="Listing"]` — scoping to that container excludes them.
#   - "Listing creation date" is relative text ("Added: 7 minutes ago") with
#     no absolute-timestamp attribute, so posted_date is left unparsed
#     (raw text is preserved in the `raw` JSONB column) rather than guessed.


def _parse_listing_cards(tree: HTMLParser, page_url: str) -> list[RawListing]:
    card_nodes = tree.css('li[aria-label="Listing"]')

    results: list[RawListing] = []
    for card in card_nodes:
        listing = _parse_card(card, page_url)
        if listing is not None:
            results.append(listing)
    return results


def _text(card: Node, aria_label: str) -> str | None:
    node = card.css_first(f'[aria-label="{aria_label}"]')
    return node.text(strip=True) if node else None


def _parse_card(card: Node, page_url: str) -> RawListing | None:
    link_node = card.css_first('a[aria-label="Listing link"]')
    if link_node is None:
        return None

    href = link_node.attributes.get("href") or ""
    source_url = href if href.startswith("http") else f"{_BASE_URL}{href}"

    id_match = _LISTING_ID_RE.search(href)
    external_id = id_match.group(1) if id_match else None

    currency = _text(card, "Currency") or ""
    price = _text(card, "Price") or ""
    price_raw = f"{currency} {price}".strip() or None

    return {
        "source_url": source_url,
        "external_id": external_id,
        "title": _text(card, "Title"),
        "description": None,  # not present on search-results cards, only on detail pages
        "price_raw": price_raw,
        "location_raw": _text(card, "Location"),
        "beds_raw": _text(card, "Beds"),
        "baths_raw": _text(card, "Baths"),
        "area_raw": _text(card, "Area"),
        "posted_raw": _text(card, "Listing creation date"),
        "_source": "css",
        "_page_url": page_url,
    }
