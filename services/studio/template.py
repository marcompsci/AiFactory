"""App Studio's prototype template: a small, working focus-and-streaks app.

The template is real software — a tested Python core plus an accessible, installable web preview that
mirrors the same rules in JavaScript. The opportunity spec fills in the name, tagline and enabled features.
Generated prototypes say plainly that they came from this template.
"""
from __future__ import annotations

import html
import json
import re

FEATURES = {
    "focus_sessions": "Timed focus sessions with a configurable length",
    "streaks": "Daily streaks that survive a single missed day only if you use a freeze",
    "daily_goal": "A daily goal in focused minutes with progress",
}

CORE = '''"""Core rules for {name}. Pure functions; no network, no storage, no analytics."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

MIN_SESSION_MINUTES = 5
MAX_SESSION_MINUTES = 120


@dataclass
class Tracker:
    daily_goal_minutes: int = 60
    freezes: int = 1
    sessions: dict[date, int] = field(default_factory=dict)  # day -> focused minutes

    def log_session(self, day: date, minutes: int) -> int:
        if not MIN_SESSION_MINUTES <= minutes <= MAX_SESSION_MINUTES:
            raise ValueError(f"sessions must be {{MIN_SESSION_MINUTES}}-{{MAX_SESSION_MINUTES}} minutes")
        self.sessions[day] = self.sessions.get(day, 0) + minutes
        return self.sessions[day]

    def progress(self, day: date) -> float:
        return min(1.0, self.sessions.get(day, 0) / self.daily_goal_minutes)

    def goal_met(self, day: date) -> bool:
        return self.sessions.get(day, 0) >= self.daily_goal_minutes

    def streak(self, today: date) -> int:
        """Consecutive goal days ending today (or yesterday), bridging gaps with available freezes."""
        freezes = self.freezes
        count = 0
        day = today if self.goal_met(today) else today - timedelta(days=1)
        while True:
            if self.goal_met(day):
                count += 1
            elif freezes > 0 and count > 0:
                freezes -= 1
            else:
                break
            day -= timedelta(days=1)
        return count
'''

TESTS = '''from datetime import date, timedelta

import pytest

from app.core import Tracker

D = date(2026, 10, 14)


def test_log_and_progress():
    t = Tracker(daily_goal_minutes=50)
    t.log_session(D, 25)
    assert t.progress(D) == 0.5
    t.log_session(D, 25)
    assert t.goal_met(D) and t.progress(D) == 1.0


@pytest.mark.parametrize("bad", [0, 4, 121])
def test_session_bounds(bad):
    with pytest.raises(ValueError):
        Tracker().log_session(D, bad)


def test_streak_counts_consecutive_days():
    t = Tracker(daily_goal_minutes=30, freezes=0)
    for i in range(3):
        t.log_session(D - timedelta(days=i), 30)
    assert t.streak(D) == 3


def test_streak_survives_today_not_done_yet():
    t = Tracker(daily_goal_minutes=30, freezes=0)
    t.log_session(D - timedelta(days=1), 30)
    assert t.streak(D) == 1


def test_freeze_bridges_one_gap():
    t = Tracker(daily_goal_minutes=30, freezes=1)
    t.log_session(D, 30)
    t.log_session(D - timedelta(days=2), 30)
    assert t.streak(D) == 2
    t.freezes = 0
    assert t.streak(D) == 1


def test_progress_caps_at_one():
    t = Tracker(daily_goal_minutes=10)
    t.log_session(D, 60)
    assert t.progress(D) == 1.0
'''

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name}</title>
<link rel="manifest" href="manifest.webmanifest">
<style>
  :root {{ color-scheme: light dark; --accent: #0a7d5a; }}
  body {{ font: 17px/1.5 system-ui, sans-serif; margin: 0; padding: 24px; max-width: 30rem; margin-inline: auto; }}
  h1 {{ font-size: 1.6rem; margin: 0 0 4px; }}
  p.tag {{ margin: 0 0 24px; opacity: .75; }}
  .ring {{ font-size: 3rem; font-variant-numeric: tabular-nums; margin: 8px 0; }}
  button {{ font: inherit; padding: 12px 18px; border-radius: 12px; border: 0; background: var(--accent); color: white; min-height: 44px; }}
  label {{ display: block; margin: 16px 0 6px; }}
  input {{ font: inherit; padding: 8px; width: 6rem; }}
  progress {{ width: 100%; height: 14px; }}
  :focus-visible {{ outline: 3px solid var(--accent); outline-offset: 2px; }}
</style>
</head>
<body>
<main>
  <h1>{name}</h1>
  <p class="tag">{tagline}</p>
  <section aria-labelledby="today-h">
    <h2 id="today-h">Today</h2>
    <label for="minutes">Session length in minutes</label>
    <input id="minutes" type="number" min="5" max="120" value="25" inputmode="numeric">
    <p><button id="log" type="button">Log a focus session</button></p>
    <label for="bar">Daily goal progress</label>
    <progress id="bar" max="1" value="0"></progress>
    <p class="ring" aria-live="polite"><span id="streak">0</span> day streak</p>
    <p id="error" role="alert"></p>
  </section>
  <ul>{feature_items}</ul>
  <p><small>Prototype generated by App Studio from the focus-tracker template. No accounts, no tracking; data stays on this device.</small></p>
</main>
<script>
  const GOAL = 60, today = new Date().toISOString().slice(0, 10);
  const store = (() => {{ try {{ return JSON.parse(localStorage.getItem("sessions") || "{{}}"); }} catch {{ return {{}}; }} }})();
  function render() {{
    document.getElementById("bar").value = Math.min(1, (store[today] || 0) / GOAL);
    let s = 0, d = new Date();
    if ((store[today] || 0) < GOAL) d.setDate(d.getDate() - 1);
    while ((store[d.toISOString().slice(0, 10)] || 0) >= GOAL) {{ s++; d.setDate(d.getDate() - 1); }}
    document.getElementById("streak").textContent = s;
  }}
  document.getElementById("log").addEventListener("click", () => {{
    const m = Number(document.getElementById("minutes").value);
    const err = document.getElementById("error");
    if (!(m >= 5 && m <= 120)) {{ err.textContent = "Sessions must be 5 to 120 minutes."; return; }}
    err.textContent = "";
    store[today] = (store[today] || 0) + m;
    try {{ localStorage.setItem("sessions", JSON.stringify(store)); }} catch {{}}
    render();
  }});
  render();
</script>
</body>
</html>
"""

ICON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024"><rect width="1024" height="1024" fill="#0a7d5a"/><circle cx="512" cy="512" r="300" fill="none" stroke="#fff" stroke-width="80"/><path d="M512 300v220l140 90" stroke="#fff" stroke-width="70" fill="none" stroke-linecap="round"/></svg>"""


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "prototype"


def render(spec: dict) -> dict[str, str]:
    """Return {relative_path: content} for the prototype described by `spec`."""
    name = spec["app_name"][:30]
    tagline = spec.get("tagline", "Focus in short sessions and keep your streak.")[:80]
    features = [f for f in spec.get("features", []) if f in FEATURES] or list(FEATURES)
    feature_items = "".join(f"<li>{html.escape(FEATURES[f])}</li>" for f in features)
    readme = (f"# {name}\n\n{tagline}\n\nGenerated by App Studio from the focus-tracker template for opportunity "
              f"`{spec.get('opportunity_id', '')}`.\n\n## Features\n" + "".join(f"- {FEATURES[f]}\n" for f in features)
              + "\n## Run\n\n- Tests: `python -m pytest`\n- Preview: open `index.html` in a browser\n\n"
              "## Known limitations\n\n- Web prototype only; an App Store build needs an Xcode project and signing.\n"
              "- Data is stored on the device only.\n")
    metadata = {"name": name, "subtitle": tagline[:30], "category": spec.get("category", "Productivity"),
                "keywords": ",".join(spec.get("keywords", ["focus", "streak", "timer", "habit"]))[:100],
                "age_rating": "4+", "privacy_policy": "PRIVACY.md", "icon": "icon.svg", "features": features}
    return {
        "app/__init__.py": "",
        "app/core.py": CORE.format(name=name),
        "tests/test_core.py": TESTS,
        "index.html": PAGE.format(name=html.escape(name), tagline=html.escape(tagline), feature_items=feature_items),
        "manifest.webmanifest": json.dumps({"name": name, "short_name": name[:12], "start_url": "index.html", "display": "standalone",
                                            "icons": [{"src": "icon.svg", "sizes": "any", "type": "image/svg+xml"}]}, indent=2),
        "icon.svg": ICON,
        "README.md": readme,
        "PRIVACY.md": f"# {name} privacy\n\n{name} collects no personal data, has no accounts and sends nothing over the network. "
                      "Focus history is stored only in this device's browser storage.\n",
        "store/metadata.json": json.dumps(metadata, indent=2),
        "pyproject.toml": '[tool.pytest.ini_options]\npythonpath = ["."]\ntestpaths = ["tests"]\n',
    }
