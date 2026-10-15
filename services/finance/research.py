"""Researching alternatives to a cost (spec §6, steps 5-6).

Sources come from an allowlist. Today that is the bundled vendor catalog. It is a labeled FIXTURE: its prices are
placeholders and every finding cites `fixture://vendor-catalog/...`. When nothing matches, the result says so
and nothing is invented. Options are compared on price, compatibility, security, quality, migration cost and
three-year cost.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

CATALOG = Path(__file__).parent / "fixtures" / "vendor_catalog.json"
YEARS = 3


@lru_cache
def catalog() -> dict:
    return json.loads(CATALOG.read_text())


def category_for(vendor: str, item: str) -> str | None:
    text = f"{vendor} {item}".lower()
    for key, cat in catalog()["vendor_category"].items():
        if key in text:
            return cat
    return None


def _yearly(price_minor: int, interval: str) -> int:
    return price_minor * 12 if interval == "month" else price_minor


def research(*, vendor: str, item: str, amount_minor: int, interval: str, classification: str) -> dict:
    """Returns findings for the packet. Legally required costs are never shopped around (no evasion)."""
    if classification == "legally_required":
        return {"category": None, "data_mode": "n/a", "findings": [], "note": "Legally required: no alternatives sought. Pay it on time."}
    cat = category_for(vendor, item)
    current_yearly = _yearly(amount_minor, interval if interval != "one_time" else "year")
    if cat is None:
        # no alternatives are known, but the owner still decides on the request itself (its own terms, nothing invented)
        return {"category": None, "data_mode": "fixture", "note": "No authorized source covers this vendor or category yet. Nothing was guessed.",
                "findings": [{"vendor": vendor, "item": item, "is_requested": True, "price_minor": amount_minor, "interval": interval,
                              "yearly_minor": current_yearly, "migration_minor": 0, "three_year_minor": current_yearly * YEARS,
                              "first_year_minor": current_yearly, "compatibility": "full", "security": "not assessed",
                              "quality": "as requested", "notes": "The requested option (terms from the request itself).",
                              "source": "request", "data_mode": "request"}]}
    findings = []
    for alt in catalog()["categories"][cat]:
        same = alt["vendor"].lower() in vendor.lower() or vendor.lower() in alt["vendor"].lower()
        if alt.get("reference") and not same:
            continue  # a stand-in for "what you already have"; the request itself plays that role
        if alt.get("usage_priced") and not same:
            findings.append({"vendor": alt["vendor"], "item": alt["item"], "is_requested": False, "price_minor": None, "interval": "usage",
                             "yearly_minor": None, "migration_minor": alt["migration_minor"], "three_year_minor": None, "first_year_minor": None,
                             "compatibility": alt["compatibility"], "security": alt["security"], "quality": alt["quality"],
                             "notes": alt["notes"] + " Usage-priced: compare the effective rate on your own volume; not ranked on price here.",
                             "source": f"fixture://vendor-catalog/{cat}/{alt['vendor'].lower().replace(' ', '-')}", "data_mode": "fixture"})
            continue
        yearly = current_yearly if same else _yearly(alt["price_minor"], alt["interval"])
        migration = 0 if same else alt["migration_minor"]
        findings.append({
            "vendor": alt["vendor"], "item": alt["item"], "is_requested": same,
            "price_minor": amount_minor if same else alt["price_minor"], "interval": interval if same else alt["interval"],
            "yearly_minor": yearly, "migration_minor": migration, "three_year_minor": yearly * YEARS + migration,
            "first_year_minor": yearly + migration, "compatibility": alt["compatibility"], "security": alt["security"],
            "quality": alt["quality"], "notes": alt["notes"], "source": f"fixture://vendor-catalog/{cat}/{alt['vendor'].lower().replace(' ', '-')}",
            "data_mode": "fixture",
        })
    if not any(f["is_requested"] for f in findings):
        findings.insert(0, {"vendor": vendor, "item": item, "is_requested": True, "price_minor": amount_minor, "interval": interval,
                            "yearly_minor": current_yearly, "migration_minor": 0, "three_year_minor": current_yearly * YEARS,
                            "first_year_minor": current_yearly, "compatibility": "full", "security": "not assessed",
                            "quality": "as requested", "notes": "The requested option (terms from the request itself).",
                            "source": "request", "data_mode": "request"})
    return {"category": cat, "data_mode": "fixture", "findings": findings,
            "note": "Catalog prices are FIXTURE placeholders for development; verify current pricing before deciding."}


def recommend(packet, findings: list[dict], *, min_saving_ratio: float = 0.2) -> dict:
    """Pick the recommendation deterministically: the cheapest option over three years that is fully or partially
    compatible and has an assessed security posture, but only if it saves at least 20% of the requested option's
    three-year cost (migration included). Otherwise recommend what was requested. Contractual costs are never switched
    mid-term, and legally required costs are always paid."""
    requested = next((f for f in findings if f["is_requested"]), None)
    if packet.classification == "legally_required":
        return {"action": "pay_on_time", "summary": "Required obligation: keep paying it on time. No alternatives were sought.",
                "chosen": None, "saving_three_year_minor": 0}
    if requested is None:
        return {"action": "no_change", "summary": "Nothing to compare.", "chosen": None, "saving_three_year_minor": 0}
    viable = [f for f in findings if not f["is_requested"] and f["three_year_minor"] is not None
              and f["compatibility"] in ("full", "partial") and f["security"] != "not assessed"]
    best = min(viable, key=lambda f: f["three_year_minor"], default=None)
    saving = (requested["three_year_minor"] - best["three_year_minor"]) if best else 0
    if best and requested["three_year_minor"] > 0 and saving >= requested["three_year_minor"] * min_saving_ratio:
        caveat = " Contract: switch only when the current term ends." if packet.classification == "contractual" else ""
        compat = "" if best["compatibility"] == "full" else " Compatibility is partial: check the notes before switching."
        if packet.origin == "fee_detected":
            caveat += " Switching is your call and you make the change yourself; nothing is cancelled or moved automatically."
        return {"action": "choose_alternative", "chosen": best["vendor"], "saving_three_year_minor": saving,
                "summary": f"{best['vendor']} {best['item']} costs less over three years, migration included.{compat}{caveat}"}
    if packet.origin == "fee_detected":
        if packet.classification == "optional":
            return {"action": "avoid_fee", "chosen": None, "saving_three_year_minor": requested["three_year_minor"],
                    "summary": "Avoidable fee: ask the provider to waive it or meet the waiver condition. Nothing is cancelled automatically."}
        return {"action": "keep", "chosen": None, "saving_three_year_minor": 0,
                "summary": "No cheaper compatible option found in authorized sources: keep it."}
    return {"action": "buy_requested", "chosen": requested["vendor"], "saving_three_year_minor": 0,
            "summary": "No alternative saves enough to justify switching: buy what was requested."}
