"""Minimal client for sauto.cz (Czech Republic) car listings.

Unlike otomoto.pl/standvirtual.com (embedded __NEXT_DATA__ scraping),
sauto.cz has a genuine JSON REST API (https://www.sauto.cz/api/v1/...),
discovered by inspecting the site's own requests:

- GET /api/v1/items/search -- paginated listing search. Make+model is one
  combined param, `manufacturer_model_seo`, either "<make-seo>" (whole make)
  or "<make-seo>:<model-seo>" (colon-separated, NOT a URL path segment).
  Year range is `vehicle_age_from`/`vehicle_age_to` (plain years, despite the
  "vehicle_age" name). `price_from`/`price_to` and `tachometer_from`/`_to`
  (mileage, km) also work. Category 838 = "Osobní" (passenger cars).
- GET /api/v1/items/filter_page -- returns the full filter codebook,
  including the enumerable list of valid models (as `children` of the
  matched make in the `manufacturer_cb` component) when queried with a make.
  This gives real make/model enumeration, unlike the best-effort slug
  guessing needed for otomoto/standvirtual.

IMPORTANT: like otomoto/standvirtual, `items/search` silently ignores an
unrecognized `manufacturer_model_seo` value instead of erroring (falling
back to the whole make, or the whole catalog) -- so this module always
resolves make/model against the filter_page codebook *before* querying
items/search, rather than trying to detect the fallback after the fact.
"""
from __future__ import annotations

import re
import statistics
import time
import unicodedata

import httpx

BASE_URL = "https://www.sauto.cz/api/v1"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
CATEGORY_PERSONAL_CARS = 838
PAGE_SIZE = 40


def slugify(value: str) -> str:
    """Best-effort sauto.cz seo_name conversion (e.g. "Řada 1" -> "rada-1")."""
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


class SautoError(RuntimeError):
    pass


def _get(path: str, params: dict, client: httpx.Client) -> dict:
    resp = client.get(
        f"{BASE_URL}{path}",
        params=params,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json", "Accept-Language": "cs"},
    )
    if resp.status_code in (403, 429):
        raise SautoError(f"sauto.cz returned {resp.status_code} (blocked/rate-limited) for {path}")
    resp.raise_for_status()
    return resp.json()


def _find_component(filters_blob, name: str):
    if isinstance(filters_blob, dict):
        if filters_blob.get("name") == name and "options" in filters_blob:
            return filters_blob
        for v in filters_blob.values():
            found = _find_component(v, name)
            if found:
                return found
    elif isinstance(filters_blob, list):
        for v in filters_blob:
            found = _find_component(v, name)
            if found:
                return found
    return None


def _resolve_make(make: str, client: httpx.Client) -> dict:
    """Look up a make by name or seo slug via filter_page's manufacturer_cb codebook."""
    make_slug = slugify(make)
    data = _get(
        "/items/filter_page",
        {"category_id": CATEGORY_PERSONAL_CARS, "operating_lease": "false", "manufacturer_model_seo": make_slug},
        client,
    )
    comp = _find_component(data, "manufacturer_cb")
    if comp is None:
        raise SautoError("Could not find manufacturer_cb codebook in filter_page response")
    for option in comp["options"]:
        if option.get("seo_name") == make_slug or slugify(option.get("name", "")) == make_slug:
            return option
    raise SautoError(
        f"make '{make}' (slug '{make_slug}') not found in sauto.cz's manufacturer list. "
        f"Use list_makes_models to see valid make names."
    )


def _resolve_model(make_option: dict, model: str) -> dict:
    model_slug = slugify(model)
    children = make_option.get("children", [])
    for child in children:
        if child.get("seo_name") == model_slug or slugify(child.get("name", "")) == model_slug:
            return child
    available = ", ".join(c["seo_name"] for c in children[:20])
    raise SautoError(
        f"model '{model}' (slug '{model_slug}') not found under make '{make_option['name']}' "
        f"on sauto.cz. Available models include: {available}{'...' if len(children) > 20 else ''}. "
        f"Use list_makes_models to see the full list."
    )


def list_makes_models(make: str, model: str | None = None) -> dict:
    """Resolve a make (and optionally model) against sauto.cz's real filter codebook.

    Unlike otomoto-pl/standvirtual-pt's best-effort guess validation, this
    enumerates sauto's actual valid model list for the make.
    """
    with httpx.Client(timeout=20) as client:
        make_option = _resolve_make(make, client)
        result = {
            "make_seo_name": make_option["seo_name"],
            "make_display_name": make_option["name"],
            "available_models": [
                {"seo_name": c["seo_name"], "name": c["name"]} for c in make_option.get("children", [])
            ],
        }
        if model is not None:
            try:
                model_option = _resolve_model(make_option, model)
                result["model_seo_name"] = model_option["seo_name"]
                result["model_display_name"] = model_option["name"]
                result["valid"] = True
            except SautoError as e:
                result["valid"] = False
                result["error"] = str(e)
        else:
            result["valid"] = True
        return result


def _manufacturer_model_seo(make: str, model: str | None, client: httpx.Client) -> str:
    make_option = _resolve_make(make, client)
    if model is None:
        return make_option["seo_name"]
    model_option = _resolve_model(make_option, model)
    return f"{make_option['seo_name']}:{model_option['seo_name']}"


def _item_to_listing(item: dict) -> dict:
    manufacturing_date = item.get("manufacturing_date")
    year = int(manufacturing_date[:4]) if manufacturing_date else None
    return {
        "id": item.get("id"),
        "title": item.get("name"),
        "price_czk": None if item.get("price_by_agreement") else item.get("price"),
        "currency": "CZK",
        "year": year,
        "mileage_km": item.get("tachometer"),
        "fuel_type": (item.get("fuel_cb") or {}).get("name"),
        "gearbox": (item.get("gearbox_cb") or {}).get("name"),
        "region": (item.get("locality") or {}).get("region"),
        "seller_name": (item.get("premise") or {}).get("name"),
    }


def search_listings(
    make: str,
    model: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    page: int = 1,
) -> dict:
    """Search sauto.cz (Czech Republic) listings for one page (up to 40 results)."""
    with httpx.Client(timeout=20) as client:
        mm_seo = _manufacturer_model_seo(make, model, client)
        params = {
            "limit": PAGE_SIZE,
            "offset": (page - 1) * PAGE_SIZE,
            "manufacturer_model_seo": mm_seo,
            "category_id": CATEGORY_PERSONAL_CARS,
            "operating_lease": "false",
        }
        if year_from:
            params["vehicle_age_from"] = year_from
        if year_to:
            params["vehicle_age_to"] = year_to
        data = _get("/items/search", params, client)

    return {
        "manufacturer_model_seo": mm_seo,
        "total_count": data["pagination"]["total"],
        "page": page,
        "page_size": PAGE_SIZE,
        "listings": [_item_to_listing(r) for r in data.get("results", [])],
    }


def price_analysis(
    make: str,
    model: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    max_listings: int = 100,
) -> dict:
    """Aggregate price stats (CZK and EUR) over up to `max_listings` sauto.cz results."""
    max_pages = max(1, (max_listings + PAGE_SIZE - 1) // PAGE_SIZE)
    all_items: list[dict] = []
    total_count = None
    mm_seo = None

    with httpx.Client(timeout=20) as client:
        mm_seo = _manufacturer_model_seo(make, model, client)
        for page in range(max_pages):
            params = {
                "limit": PAGE_SIZE,
                "offset": page * PAGE_SIZE,
                "manufacturer_model_seo": mm_seo,
                "category_id": CATEGORY_PERSONAL_CARS,
                "operating_lease": "false",
            }
            if year_from:
                params["vehicle_age_from"] = year_from
            if year_to:
                params["vehicle_age_to"] = year_to
            data = _get("/items/search", params, client)
            total_count = data["pagination"]["total"]
            results = data.get("results", [])
            if not results:
                break
            all_items.extend(_item_to_listing(r) for r in results)
            if len(all_items) >= max_listings or len(results) < PAGE_SIZE:
                break
            time.sleep(0.3)

    all_items = all_items[:max_listings]
    prices_czk = sorted(l["price_czk"] for l in all_items if l["price_czk"])

    if not prices_czk:
        return {
            "manufacturer_model_seo": mm_seo,
            "site_total_count": total_count,
            "sampled_count": 0,
            "note": "No listings with a parseable price were found for this query.",
        }

    def pct(p: float) -> float:
        idx = min(len(prices_czk) - 1, max(0, round(p * (len(prices_czk) - 1))))
        return prices_czk[idx]

    rate = get_eur_czk_rate()
    stats_czk = {
        "min": prices_czk[0],
        "p25": pct(0.25),
        "median": statistics.median(prices_czk),
        "avg": round(statistics.mean(prices_czk), 2),
        "p75": pct(0.75),
        "max": prices_czk[-1],
    }
    stats_eur = {k: round(v * rate, 2) if rate else None for k, v in stats_czk.items()}

    return {
        "manufacturer_model_seo": mm_seo,
        "site_total_count": total_count,
        "sampled_count": len(prices_czk),
        "eur_czk_rate_used": rate,
        "eur_czk_rate_source": "https://api.frankfurter.dev (ECB reference rate)" if rate else None,
        "price_czk": stats_czk,
        "price_eur": stats_eur,
    }


_rate_cache: dict = {}


def get_eur_czk_rate(ttl_seconds: int = 3600) -> float | None:
    """1 CZK in EUR, via the free Frankfurter (ECB) API. Cached in-process."""
    now = time.time()
    if _rate_cache.get("value") and now - _rate_cache.get("ts", 0) < ttl_seconds:
        return _rate_cache["value"]
    try:
        resp = httpx.get(
            "https://api.frankfurter.dev/v1/latest",
            params={"base": "CZK", "symbols": "EUR"},
            timeout=10,
        )
        resp.raise_for_status()
        rate = resp.json()["rates"]["EUR"]
        _rate_cache.update(value=rate, ts=now)
        return rate
    except Exception:
        return _rate_cache.get("value")
