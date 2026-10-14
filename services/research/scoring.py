"""Opportunity scoring with configurable weights.

Every component is a number in [0, 1] where higher is better for the opportunity (so "saturation" is
1 − competitive saturation and "policy_risk" is 1 − risk). Each component keeps the evidence it used.
Unknowns default to 0.5 with an explicit "no evidence" note rather than an optimistic guess.
Weights: AICIV_SCORE_WEIGHTS='{"demand": 2, ...}' overrides DEFAULT_WEIGHTS per component.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

COMPONENTS = ("demand", "momentum", "saturation", "differentiation", "feasibility", "production_cost",
              "monetization", "policy_risk", "owner_alignment")
DEFAULT_WEIGHTS = {"demand": 2.0, "momentum": 1.5, "saturation": 1.0, "differentiation": 1.0, "feasibility": 1.5,
                   "production_cost": 0.75, "monetization": 1.0, "policy_risk": 1.0, "owner_alignment": 1.0}
HIGH_RISK_CATEGORIES = {"finance", "medical", "health", "gambling", "kids"}
TEMPLATE_CATEGORIES = {"productivity"}  # categories App Studio has a working prototype template for


def weights() -> dict[str, float]:
    w = dict(DEFAULT_WEIGHTS)
    try:
        w.update({k: float(v) for k, v in json.loads(os.environ.get("AICIV_SCORE_WEIGHTS", "{}")).items() if k in COMPONENTS})
    except (ValueError, TypeError):
        pass
    return w


def owner_priorities() -> list[str]:
    return [p.strip().lower() for p in os.environ.get("AICIV_OWNER_PRIORITIES", "productivity,fitness,skateboarding").split(",") if p.strip()]


@dataclass
class Component:
    score: float
    evidence: list[str]


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, round(x, 4)))


def score_app_category(category: str, findings: list[dict], est_cost_usd: float) -> tuple[float, dict[str, Component], str, list[str]]:
    """Returns (total, components, confidence, risk_flags) for an app-category opportunity."""
    c: dict[str, Component] = {}
    ranked = [f for f in findings if f["measurement_type"] == "ranking"]
    entries = [e for f in ranked for e in f["metrics"].get("entries", [])]
    chart_size = max([f["metrics"].get("chart_size", 50) for f in ranked] or [50])
    n = len(entries)
    c["demand"] = Component(_clamp(n / 5), [f"{n} of the top {chart_size} free apps are in '{category}' (rank is a popularity proxy, not sales)"]
                            if ranked else ["no ranking evidence"])
    risers = [e for e in entries if e.get("previous_rank") and e["rank"] < e["previous_rank"]]
    newcomers = [e for e in entries if e.get("previous_rank") is None]
    if any("previous_rank" in e for e in entries) and any(e.get("previous_rank") is not None for e in entries):
        c["momentum"] = Component(_clamp((len(risers) + 0.5 * len(newcomers)) / max(1, n)),
                                  [f"{len(risers)} climbing, {len(newcomers)} new entries since the previous chart"])
    else:
        c["momentum"] = Component(0.5, ["no previous-rank data: momentum unknown"])
    top10 = len([e for e in entries if e["rank"] <= 10])
    c["saturation"] = Component(_clamp(1 - top10 / 3), [f"{top10} incumbents in the top 10"])
    ratings = [e["rating"] for e in entries if e.get("rating")]
    if ratings:
        avg = sum(ratings) / len(ratings)
        c["differentiation"] = Component(_clamp((4.8 - avg) / 1.0), [f"incumbent average rating {avg:.2f}: room to stand out on quality"])
    else:
        c["differentiation"] = Component(0.5, ["no rating data"])
    feasible = category.lower() in TEMPLATE_CATEGORIES
    c["feasibility"] = Component(0.85 if feasible else 0.35, ["App Studio has a tested template for this category" if feasible else "no template; custom build"])
    c["production_cost"] = Component(_clamp(1 - est_cost_usd / 10), [f"estimated build cost ${est_cost_usd:.2f} (model + compute estimate)"])
    c["monetization"] = Component(0.55 if category.lower() == "productivity" else 0.5,
                                  ["productivity apps commonly use subscriptions; no revenue data observed"])
    risky = category.lower() in HIGH_RISK_CATEGORIES
    c["policy_risk"] = Component(0.3 if risky else 0.85, ["category has elevated App Review / regulatory risk" if risky else "no special App Review category rules"])
    aligned = category.lower() in owner_priorities()
    c["owner_alignment"] = Component(0.9 if aligned else 0.4, [f"owner priorities: {', '.join(owner_priorities())}"])

    w = weights()
    total = _clamp(sum(c[k].score * w[k] for k in COMPONENTS) / sum(w.values()))
    modes = {f["data_mode"] for f in findings}
    if not findings:
        confidence = "low"
    elif all(f["confidence"] == "high" for f in findings) and len(findings) >= 2:
        confidence = "high"
    else:
        confidence = "medium" if n >= 2 else "low"
    flags = []
    if "fixture" in modes:
        flags.append("fixture_data: evidence is labeled fixture data, not live market research")
    if risky:
        flags.append("high_policy_risk_category")
    if not ranked:
        flags.append("no_demand_evidence")
    return total, c, confidence, flags
