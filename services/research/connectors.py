"""Compliant market-data connectors.

Rules every connector follows:
  * only documented, permitted access: public feeds, official APIs with the owner's key, partner APIs
    with a partner token, or the owner's own App Store Connect data. No scraping, no CAPTCHA or login
    bypass, no ignoring rate limits.
  * a connector that lacks access says so (`Unavailable`) instead of guessing.
  * fixture data is only used when AICIV_RESEARCH_MODE is "fixture", or "auto" and live access is
    unavailable; every result then carries data_mode="fixture" and a fixture:// source URL.
  * sales figures are never invented: each result states its measurement type (ranking, listing count,
    popularity proxy, review signal, or direct sales only when the platform reports actual sales).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx

FIXTURES = Path(__file__).parent / "fixtures"


class Unavailable(Exception):
    """The platform cannot be reached with the access we legitimately have."""


@dataclass
class RawResult:
    source_platform: str
    source_url: str
    collected_at: str
    region: str
    data_mode: str  # live | fixture
    coverage: str
    measurement_type: str
    items: list[dict]
    notice: str = ""
    extra: dict = field(default_factory=dict)


def research_mode() -> str:
    return os.environ.get("AICIV_RESEARCH_MODE", "auto")


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


class Connector:
    key = ""
    platform = ""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(timeout=15, headers={"user-agent": "AICivilization-Research/0.4 (+owner-authorized)"})

    def live(self, query: str, region: str) -> RawResult:
        raise Unavailable("not implemented")

    def fixture(self, query: str, region: str) -> RawResult:
        raise Unavailable("no fixture")

    def fetch(self, query: str, region: str = "US") -> RawResult:
        mode = research_mode()
        if mode == "fixture":
            return self.fixture(query, region)
        try:
            return self.live(query, region)
        except (Unavailable, httpx.HTTPError) as exc:
            if mode == "auto":
                r = self.fixture(query, region)
                r.extra["live_unavailable_reason"] = str(exc)[:300]
                return r
            raise Unavailable(str(exc)) from exc


class AppleChartsConnector(Connector):
    """Apple's public RSS chart feed (https://rss.marketingtools.apple.com). Ranks only — Apple publishes no sales here."""

    key = "apple_charts"
    platform = "apple_app_store"

    def _shape(self, entries: list[dict], query: str) -> list[dict]:
        q = query.lower()
        return [e for e in entries if q in (e.get("genre") or "").lower() or q in (e.get("name") or "").lower()]

    def live(self, query: str, region: str) -> RawResult:
        url = f"https://rss.marketingtools.apple.com/api/v2/{region.lower()}/apps/top-free/50/apps.json"
        r = self.client.get(url)
        r.raise_for_status()
        results = r.json().get("feed", {}).get("results", [])
        entries = [{"rank": i + 1, "previous_rank": None, "name": x.get("name"), "genre": ", ".join(g.get("name", "") for g in x.get("genres", [])),
                    "rating": None, "url": x.get("url")} for i, x in enumerate(results)]
        return RawResult(self.platform, url, datetime.now(timezone.utc).isoformat(), region, "live",
                         f"top 50 free apps, {region} storefront", "ranking", self._shape(entries, query),
                         extra={"chart_size": len(entries)})

    def fixture(self, query: str, region: str) -> RawResult:
        f = _fixture("apple_charts_us_top_free.json")
        return RawResult(self.platform, "fixture://apple_charts/us/top-free", f["collected_at"], f["region"], "fixture",
                         "FIXTURE: 8 hand-written chart rows", "ranking", self._shape(f["results"], query),
                         notice=f["_fixture_notice"], extra={"chart_size": 50})


class EtsyConnector(Connector):
    """Etsy Open API v3. Requires the owner's ETSY_API_KEY. Listing counts and favorites only — not shop sales."""

    key = "etsy"
    platform = "etsy"

    def live(self, query: str, region: str) -> RawResult:
        key = os.environ.get("ETSY_API_KEY")
        if not key:
            raise Unavailable("ETSY_API_KEY not configured")
        url = "https://openapi.etsy.com/v3/application/listings/active"
        r = self.client.get(url, params={"keywords": query, "limit": 25, "sort_on": "score"}, headers={"x-api-key": key})
        if r.status_code == 429:
            raise Unavailable("Etsy rate limit reached; not retrying past the platform limit")
        r.raise_for_status()
        body = r.json()
        items = [{"title": x.get("title"), "price": (x.get("price") or {}).get("amount"), "num_favorers": x.get("num_favorers")}
                 for x in body.get("results", [])]
        return RawResult(self.platform, f"{url}?keywords={query}", datetime.now(timezone.utc).isoformat(), region, "live",
                         "first 25 active listings by relevance", "listing_count", items, extra={"count": body.get("count")})

    def fixture(self, query: str, region: str) -> RawResult:
        f = _fixture("etsy_listings.json")
        return RawResult(self.platform, "fixture://etsy/listings", f["collected_at"], f["region"], "fixture",
                         "FIXTURE: 3 hand-written listings", "listing_count", f["results"], notice=f["_fixture_notice"],
                         extra={"count": f["count"]})


class DepopConnector(Connector):
    """Depop has no public API. Live access only through an authorized partner endpoint the owner configures."""

    key = "depop"
    platform = "depop"

    def live(self, query: str, region: str) -> RawResult:
        url, token = os.environ.get("DEPOP_PARTNER_API_URL"), os.environ.get("DEPOP_PARTNER_TOKEN")
        if not (url and token):
            raise Unavailable("no authorized Depop partner access configured")
        r = self.client.get(url, params={"q": query, "region": region}, headers={"authorization": f"Bearer {token}"})
        r.raise_for_status()
        return RawResult(self.platform, url, datetime.now(timezone.utc).isoformat(), region, "live", "partner feed",
                         "popularity_proxy", r.json().get("results", []))

    def fixture(self, query: str, region: str) -> RawResult:
        f = _fixture("depop_listings.json")
        return RawResult(self.platform, "fixture://depop/listings", f["collected_at"], f["region"], "fixture",
                         "FIXTURE: 2 hand-written listings", "popularity_proxy", f["results"], notice=f["_fixture_notice"])


class AppStoreConnectConnector(Connector):
    """The owner's own App Store Connect sales reports (direct sales). Needs ASC_KEY_ID, ASC_ISSUER_ID, ASC_PRIVATE_KEY_PATH."""

    key = "app_store_connect"
    platform = "app_store_connect"

    def live(self, query: str, region: str) -> RawResult:
        if not all(os.environ.get(k) for k in ("ASC_KEY_ID", "ASC_ISSUER_ID", "ASC_PRIVATE_KEY_PATH", "ASC_VENDOR_NUMBER")):
            raise Unavailable("App Store Connect API key not configured")
        import jwt  # ES256 requires the `cryptography` package

        now = int(datetime.now(timezone.utc).timestamp())
        token = jwt.encode({"iss": os.environ["ASC_ISSUER_ID"], "iat": now, "exp": now + 900, "aud": "appstoreconnect-v1"},
                           Path(os.environ["ASC_PRIVATE_KEY_PATH"]).read_text(), algorithm="ES256",
                           headers={"kid": os.environ["ASC_KEY_ID"]})
        url = "https://api.appstoreconnect.apple.com/v1/salesReports"
        r = self.client.get(url, headers={"authorization": f"Bearer {token}"},
                            params={"filter[frequency]": "DAILY", "filter[reportType]": "SALES", "filter[reportSubType]": "SUMMARY",
                                    "filter[vendorNumber]": os.environ["ASC_VENDOR_NUMBER"]})
        r.raise_for_status()
        return RawResult(self.platform, url, datetime.now(timezone.utc).isoformat(), region, "live", "owner's apps, daily summary",
                         "direct_sales", [{"raw_report_bytes": len(r.content)}])


CONNECTORS: dict[str, type[Connector]] = {c.key: c for c in (AppleChartsConnector, EtsyConnector, DepopConnector, AppStoreConnectConnector)}
