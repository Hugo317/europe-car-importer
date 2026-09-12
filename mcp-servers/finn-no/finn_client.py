"""Minimal client for finn.no (Norway) car listings.

finn.no (like blocket.se -- same Schibsted "mobility" marketplace platform,
see ../blocket-se/blocket_client.py) has no separate JSON API call for search
results in the plain-HTTP page load: the full search response (matched
listings under "docs", the complete make/series/model taxonomy tree under
"filters", and paging/total-count info under "metadata") is dehydrated
react-query state, base64-encoded inside one of several
<script type="application/json"> tags with no id attribute on the search
results page itself. This module fetches that page with plain HTTP and
decodes that blob directly -- no headless browser needed (confirmed via
Playwright that finn.no serves the same HTML to a plain `curl` as to a real
browser; unlike AS24, no anti-bot blocking observed so far).

The make/series/model filter tree is present in full (~127 makes) regardless
of which filters are applied to the request that returned it, so a single
unfiltered fetch is enough to resolve any make/model into finn's numeric
"variant" taxonomy code (format "0.<make_id>" for a make, "1.<make_id>.<series_id>"
for a series, "2.<make_id>.<series_id>.<model_id>" for a specific model/trim,
e.g. BMW 120d = "2.749.7967.2000...") before querying listings -- avoiding
otomoto/standvirtual's "unrecognized filter silently dropped" trap entirely,
since an unresolvable make/model raises here before any listings request.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
import statistics
import time
import unicodedata

import httpx

BASE_URL = "https://www.finn.no"
SEARCH_PATH = "/mobility/search/car"
CURRENCY = "NOK"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
PAGE_SIZE = 49

_SCRIPT_JSON_RE = re.compile(
    r'<script type="application/json"[^>]*>(.*?)</script>', re.S
)


class FinnError(RuntimeError):
    pass


def _normalize(value: str) -> str:
    """Fold accents/case/punctuation and the Norwegian "-serie" vs English
    "-series" naming difference so e.g. "1 Series" matches finn's "1-Serie"."""
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = value.lower().replace("series", "serie")
    return re.sub(r"[^a-z0-9]", "", value)


def _fetch_search_data(params: dict, client: httpx.Client) -> dict:
    resp = client.get(
        f"{BASE_URL}{SEARCH_PATH}",
        params=params,
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    )
    if resp.status_code in (403, 429):
        raise FinnError(
            f"finn.no returned {resp.status_code} (blocked/rate-limited) for params={params}"
        )
    resp.raise_for_status()

    best_data = None
    for raw in _SCRIPT_JSON_RE.findall(resp.text):
        raw = raw.strip()
        if len(raw) < 1000:
            continue
        try:
            decoded = base64.b64decode(raw, validate=True)
            payload = json.loads(decoded)
        except (binascii.Error, ValueError, json.JSONDecodeError):
            continue
        queries = payload.get("queries")
        if not isinstance(queries, list):
            continue
        for q in queries:
            key0 = (q.get("queryKey") or [{}])[0]
            if key0.get("scope") == "search":
                data = q.get("state", {}).get("data")
                if isinstance(data, dict) and "docs" in data:
                    best_data = data
    if best_data is None:
        raise FinnError(
            f"Could not find embedded search-result JSON in finn.no response for params={params} "
            "(page structure may have changed)"
        )
    return best_data


def _taxonomy(client: httpx.Client) -> list[dict]:
    """The full make/series/model tree, from the "variant" filter of an
    unfiltered search (present regardless of applied filters)."""
    data = _fetch_search_data({}, client)
    for f in data.get("filters", []):
        if f.get("name") == "variant":
            return f.get("filter_items", [])
    raise FinnError("Could not find the 'variant' (make/model) filter in finn.no's taxonomy response")


def _resolve_make(make: str, taxonomy: list[dict]) -> dict:
    target = _normalize(make)
    for item in taxonomy:
        if _normalize(item["display_name"]) == target:
            return item
    for item in taxonomy:
        if target in _normalize(item["display_name"]):
            return item
    available = ", ".join(i["display_name"] for i in taxonomy[:25])
    raise FinnError(
        f"make '{make}' not found in finn.no's make list. Examples: {available}... "
        f"Use list_makes_models to see the full list."
    )


def _flatten(items: list[dict], depth: int = 0) -> list[tuple[int, dict]]:
    out = []
    for item in items:
        out.append((depth, item))
        out.extend(_flatten(item.get("filter_items", []), depth + 1))
    return out


def _resolve_model(make_item: dict, model: str) -> dict:
    target = _normalize(model)
    flat = _flatten(make_item.get("filter_items", []))
    # Prefer the deepest (most specific, e.g. a leaf trim like "120d") exact match.
    exact = [(d, i) for d, i in flat if _normalize(i["display_name"]) == target]
    if exact:
        return sorted(exact, key=lambda x: -x[0])[0][1]
    partial = [(d, i) for d, i in flat if target in _normalize(i["display_name"])]
    if partial:
        return sorted(partial, key=lambda x: -x[0])[0][1]
    available = ", ".join(i["display_name"] for _, i in flat[:25])
    raise FinnError(
        f"model '{model}' not found under make '{make_item['display_name']}' on finn.no. "
        f"Available include: {available}{'...' if len(flat) > 25 else ''}. "
        f"Use list_makes_models to see the full list."
    )


def _resolve_variant_code(make: str, model: str | None, client: httpx.Client) -> tuple[str, dict, dict | None]:
    taxonomy = _taxonomy(client)
    make_item = _resolve_make(make, taxonomy)
    if model is None:
        return make_item["value"], make_item, None
    model_item = _resolve_model(make_item, model)
    return model_item["value"], make_item, model_item


def list_makes_models(make: str, model: str | None = None) -> dict:
    """Resolve a make (and optionally model) against finn.no's real taxonomy tree."""
    with httpx.Client(timeout=20) as client:
        taxonomy = _taxonomy(client)
        make_item = _resolve_make(make, taxonomy)
        result = {
            "make_display_name": make_item["display_name"],
            "make_variant_code": make_item["value"],
            "available_series": [
                {"name": s["display_name"], "variant_code": s["value"]}
                for s in make_item.get("filter_items", [])
            ],
        }
        if model is not None:
            try:
                model_item = _resolve_model(make_item, model)
                result["model_display_name"] = model_item["display_name"]
                result["model_variant_code"] = model_item["value"]
                result["valid"] = True
            except FinnError as e:
                result["valid"] = False
                result["error"] = str(e)
        else:
            result["valid"] = True
        return result


def _doc_to_listing(doc: dict) -> dict:
    price = doc.get("price") or {}
    mileage = doc.get("mileage")
    mileage_unit = doc.get("mileage_unit")
    mileage_km = mileage
    if mileage is not None and mileage_unit == "SCANDINAVIAN_MILE":
        mileage_km = mileage * 10
    return {
        "id": doc.get("id"),
        "title": doc.get("heading") or doc.get("facade_title"),
        "url": doc.get("canonical_url"),
        "price": price.get("amount"),
        "currency": price.get("currency_code", CURRENCY),
        "year": doc.get("year"),
        "mileage_km": mileage_km,
        "fuel_type": doc.get("fuel"),
        "gearbox": doc.get("transmission"),
        "make": doc.get("make"),
        "series": doc.get("series"),
        "model": doc.get("model"),
        "model_specification": doc.get("model_specification"),
        "location": doc.get("location"),
        "seller_name": doc.get("organisation_name"),
        "dealer_segment": doc.get("dealer_segment"),
    }


def _search_params(variant_code: str, year_from: int | None, year_to: int | None, page: int) -> dict:
    params: dict[str, str] = {"variant": variant_code}
    if year_from:
        params["year_from"] = str(year_from)
    if year_to:
        params["year_to"] = str(year_to)
    if page > 1:
        params["page"] = str(page)
    return params


def search_listings(
    make: str,
    model: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    page: int = 1,
) -> dict:
    """Search finn.no (Norway) car listings for one page (up to ~49 results)."""
    with httpx.Client(timeout=20) as client:
        variant_code, make_item, model_item = _resolve_variant_code(make, model, client)
        params = _search_params(variant_code, year_from, year_to, page)
        data = _fetch_search_data(params, client)
    metadata = data.get("metadata", {})
    return {
        "make_display_name": make_item["display_name"],
        "model_display_name": model_item["display_name"] if model_item else None,
        "variant_code": variant_code,
        "total_count": metadata.get("result_size", {}).get("match_count"),
        "page": page,
        "page_size": PAGE_SIZE,
        "listings": [_doc_to_listing(d) for d in data.get("docs", [])],
    }


def price_analysis(
    make: str,
    model: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    max_listings: int = 100,
) -> dict:
    """Aggregate price stats (NOK and EUR) over up to `max_listings` finn.no results."""
    max_pages = max(1, (max_listings + PAGE_SIZE - 1) // PAGE_SIZE)
    all_listings: list[dict] = []
    total_count = None
    make_item = model_item = None
    variant_code = None

    with httpx.Client(timeout=20) as client:
        variant_code, make_item, model_item = _resolve_variant_code(make, model, client)
        for page in range(1, max_pages + 1):
            params = _search_params(variant_code, year_from, year_to, page)
            data = _fetch_search_data(params, client)
            total_count = data.get("metadata", {}).get("result_size", {}).get("match_count")
            docs = data.get("docs", [])
            if not docs:
                break
            all_listings.extend(_doc_to_listing(d) for d in docs)
            if len(all_listings) >= max_listings or len(docs) < PAGE_SIZE:
                break
            time.sleep(0.3)  # be polite between paginated requests

    all_listings = all_listings[:max_listings]
    prices_nok = sorted(l["price"] for l in all_listings if l["price"])

    base = {
        "make_display_name": make_item["display_name"],
        "model_display_name": model_item["display_name"] if model_item else None,
        "variant_code": variant_code,
        "site_total_count": total_count,
    }
    if not prices_nok:
        return {**base, "sampled_count": 0, "note": "No listings with a parseable price were found for this query."}

    def pct(p: float) -> float:
        idx = min(len(prices_nok) - 1, max(0, round(p * (len(prices_nok) - 1))))
        return prices_nok[idx]

    rate = get_eur_nok_rate()
    stats_nok = {
        "min": prices_nok[0],
        "p25": pct(0.25),
        "median": statistics.median(prices_nok),
        "avg": round(statistics.mean(prices_nok), 2),
        "p75": pct(0.75),
        "max": prices_nok[-1],
    }
    stats_eur = {k: round(v * rate, 2) if rate else None for k, v in stats_nok.items()}

    return {
        **base,
        "sampled_count": len(prices_nok),
        "eur_nok_rate_used": rate,
        "eur_nok_rate_source": "https://api.frankfurter.dev (ECB reference rate)" if rate else None,
        "price_nok": stats_nok,
        "price_eur": stats_eur,
    }


_rate_cache: dict = {}


def get_eur_nok_rate(ttl_seconds: int = 3600) -> float | None:
    """1 NOK in EUR, via the free Frankfurter (ECB) API. Cached in-process."""
    now = time.time()
    if _rate_cache.get("value") and now - _rate_cache.get("ts", 0) < ttl_seconds:
        return _rate_cache["value"]
    try:
        resp = httpx.get(
            "https://api.frankfurter.dev/v1/latest",
            params={"base": "NOK", "symbols": "EUR"},
            timeout=10,
        )
        resp.raise_for_status()
        rate = resp.json()["rates"]["EUR"]
        _rate_cache.update(value=rate, ts=now)
        return rate
    except Exception:
        return _rate_cache.get("value")
