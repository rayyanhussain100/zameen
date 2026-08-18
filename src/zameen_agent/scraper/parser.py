"""Parses a Zameen.com search-results page into raw listing dicts.

Strategy: try JSON-LD structured data first (more stable across frontend
redesigns than CSS class names), and fall back to CSS selectors against the
server-rendered listing cards. Both paths return the same raw-dict shape,
which normalize.normalise() then maps onto the `listings` table.

The exact JSON-LD @type(s) and CSS selectors Zameen.com currently uses are
NOT guessed here — they're marked as TODOs to be filled in after inspecting
a live page, per the project ground rules.
"""

from __future__ import annotations

import json
from typing import Any, Iterator

from selectolax.parser import HTMLParser, Node

RawListing = dict[str, Any]


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


# TODO(json-ld): confirm which @type(s) Zameen.com actually emits for listing
# pages/cards (candidates below are guesses based on common real-estate
# schema.org usage — verify against a live page and adjust).
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


def _parse_listing_cards(tree: HTMLParser, page_url: str) -> list[RawListing]:
    """Fallback parser for server-rendered listing cards.

    TODO(selectors): the selectors below are PLACEHOLDERS and will not match
    real markup. Before using this path, load a live Zameen.com search-results
    page, inspect the DOM (devtools), and replace:
      - the card container selector
      - title / detail-link selector
      - price selector
      - location selector
      - beds / baths / area selector(s)
    Zameen.com's frontend build hashes class names, so prefer stable
    attributes (data-*, aria-label, itemprop) over generated class names
    where available.
    """
    card_nodes = tree.css("li[aria-label='Listing']")  # TODO(selectors)

    results: list[RawListing] = []
    for card in card_nodes:
        listing = _parse_card(card, page_url)
        if listing is not None:
            results.append(listing)
    return results


def _parse_card(card: Node, page_url: str) -> RawListing | None:
    link_node = card.css_first("a[href]")  # TODO(selectors)
    title_node = card.css_first("[aria-label='Title']")  # TODO(selectors)
    price_node = card.css_first("[aria-label='Price']")  # TODO(selectors)
    location_node = card.css_first("[aria-label='Location']")  # TODO(selectors)
    features_node = card.css_first("[aria-label='Beds'], [aria-label='Area']")  # TODO(selectors)

    if link_node is None:
        return None

    href = link_node.attributes.get("href") or ""
    source_url = href if href.startswith("http") else f"https://www.zameen.com{href.lstrip('/')}"

    return {
        "source_url": source_url,
        "title": title_node.text(strip=True) if title_node else None,
        "description": None,
        "price_raw": price_node.text(strip=True) if price_node else None,
        "location_raw": location_node.text(strip=True) if location_node else None,
        "features_raw": features_node.text(strip=True) if features_node else None,
        "_source": "css",
        "_card_html": card.html,
    }
