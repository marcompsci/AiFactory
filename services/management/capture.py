"""Quick capture (V6.44): a task typed the way you'd say it.

"draft the Echo App Store blurb by Friday $1 urgent" becomes a title ("Draft the Echo App Store blurb"), a due time (this
Friday, 5pm in your time zone), a budget ($1), a priority (urgent) and a kind of work (write). Everything is worked out
by rules, not a model, so the preview you see is exactly what gets saved, and nothing leaves your server.
"""
from __future__ import annotations

import re
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_WD = r"(?:mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)(?:day)?|wednesday|thursday|tuesday|saturday"
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
DEFAULT_HOUR = 17  # a date without a time means "by the end of the working day"

KIND_WORDS = {
    "code": r"\b(fix|bug|tests?|build|refactor|implement|code|deploy|repo|pull request|pr|crash|compile|ci)\b",
    "research": r"\b(research|compare|look into|investigate|find out|find the best|best .* for|options for|alternatives|review the market)\b",
    "write": r"\b(write|draft|email|e-mail|post|blurb|outline|summari[sz]e|summary|letter|proposal|copy|description|caption|script|plan|notes|agenda|bio)\b",
}


def _zone(tz: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(tz or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def _weekday_index(word: str) -> int:
    w = word[:3]
    return [d[:3] for d in WEEKDAYS].index(w)


def kind_of(text: str) -> str:
    t = text.lower()
    for kind in ("code", "research", "write"):
        if re.search(KIND_WORDS[kind], t):
            return kind
    return "personal"


def parse(text: str, tz: str | None = "UTC", now: datetime | None = None) -> dict:
    """Read a typed task. Returns {title, due_at (UTC ISO or None), due_label, priority, budget_usd, kind, repeat}."""
    zone = _zone(tz)
    now = (now or datetime.now(timezone.utc)).astimezone(zone)
    t = " " + re.sub(r"\s+", " ", (text or "").strip()) + " "
    low = t.lower()
    out: dict = {"priority": "normal", "budget_usd": None, "repeat": "none", "due_at": None, "due_label": None}

    def cut(pattern: str) -> re.Match | None:
        nonlocal t, low
        m = re.search(pattern, low)
        if m:
            t = t[:m.start()] + " " + t[m.end():]
            low = t.lower()
        return m

    m = cut(r"\s\$\s?(\d{1,2}(?:\.\d{1,2})?)\b")
    if m:
        v = float(m.group(1))
        out["budget_usd"] = v if 0 < v <= 50 else None
    if cut(r"\s(urgent|asap|high priority|important|!!?)(?=\s)"):
        out["priority"] = "urgent"
    elif cut(r"\s(low priority|someday|whenever|no rush)(?=\s)"):
        out["priority"] = "low"

    weekly_day = None
    if cut(r"\s(every ?day|daily|each day)(?=\s)"):
        out["repeat"] = "daily"
    elif cut(r"\s(every weekday|weekdays|each weekday)(?=\s)"):
        out["repeat"] = "weekdays"
    else:
        m = cut(rf"\s(?:every|each) ({_WD})(?=\s)")
        if m:
            out["repeat"], weekly_day = "weekly", _weekday_index(m.group(1))
        elif cut(r"\s(every week|weekly|each week)(?=\s)"):
            out["repeat"] = "weekly"

    # a time of day: "at 5pm", "by 9:30am", "at 17:30", "tonight", "this morning"
    at: time | None = None
    m = cut(r"\s(?:at|by|@)\s?(\d{1,2})(?::(\d{2}))?\s?(am|pm)(?=\s)") or cut(r"\s(\d{1,2})(?::(\d{2}))?\s?(am|pm)(?=\s)")
    if m:
        h = int(m.group(1)) % 12 + (12 if m.group(3) == "pm" else 0)
        if 0 <= h <= 23 and int(m.group(2) or 0) < 60:
            at = time(h, int(m.group(2) or 0))
    else:
        m = cut(r"\s(?:at|by)\s([01]?\d|2[0-3]):([0-5]\d)(?=\s)")
        if m:
            at = time(int(m.group(1)), int(m.group(2)))
    day = None
    if cut(r"\s(?:by |for )?tonight(?=\s)"):
        day, at = now.date(), at or time(20, 0)
    elif cut(r"\s(?:by |for )?this (morning)(?=\s)"):
        day, at = now.date(), at or time(11, 0)
    elif cut(r"\s(?:by |for |due )?(?:end of (?:the )?day|eod|today)(?=\s)"):
        day = now.date()
    elif cut(r"\s(?:by |for |due )?tomorrow(?=\s)"):
        day = now.date() + timedelta(days=1)
    elif cut(r"\s(?:by |for |due )?(?:next week|end of (?:the )?week|eow)(?=\s)"):
        ahead = (4 - now.weekday()) % 7 if "end" in low or "eow" in low else (7 - now.weekday()) % 7 or 7
        day = now.date() + timedelta(days=ahead)
    else:
        m = cut(r"\s(?:by |on |for |due |this |next )?in (\d{1,2}) (day|days|week|weeks)(?=\s)")
        if m:
            n = int(m.group(1)) * (7 if m.group(2).startswith("week") else 1)
            day = now.date() + timedelta(days=n)
        else:
            m = cut(rf"\s(?:by |on |for |due |this |next )?({_WD})(?=\s)")
            if m:
                ahead = (_weekday_index(m.group(1)) - now.weekday()) % 7
                if ahead == 0 and (at is None or at <= now.time()):
                    ahead = 7
                day = now.date() + timedelta(days=ahead)
            else:
                m = (cut(r"\s(?:by |on |for |due )?(" + "|".join(MONTHS) + r")[a-z]*\.? (\d{1,2})(?:st|nd|rd|th)?(?=\s)")
                     or cut(r"\s(?:by |on |for |due )?(\d{1,2})/(\d{1,2})(?=\s)"))
                if m:
                    try:
                        month = MONTHS.index(m.group(1)[:3]) + 1 if not m.group(1).isdigit() else int(m.group(1))
                        d = now.date().replace(month=month, day=int(m.group(2)))
                        if d < now.date():
                            d = d.replace(year=d.year + 1)
                        day = d
                    except ValueError:
                        day = None
    if day is None and weekly_day is not None:
        ahead = (weekly_day - now.weekday()) % 7
        day = now.date() + timedelta(days=ahead)
    if day is None and at is not None:  # only a time: today if it's still ahead, otherwise tomorrow
        day = now.date() if at > now.time() else now.date() + timedelta(days=1)
    if day is None and out["repeat"] in ("daily", "weekdays"):
        day = now.date()
    if day is not None:
        when = datetime.combine(day, at or time(DEFAULT_HOUR, 0), tzinfo=zone)
        if out["repeat"] == "weekdays":
            while when.weekday() >= 5:
                when += timedelta(days=1)
        out["due_at"] = when.astimezone(timezone.utc).isoformat()
        out["due_label"] = label(when, now)

    title = re.sub(r"\s+", " ", t).strip(" ,.;:-")
    title = re.sub(r"\s+(by|on|at|for|due|before)$", "", title, flags=re.I).strip(" ,.;:-")
    title = re.sub(r"^(remind me to|i need to|i have to|i should|todo:?|task:?|please)\s+", "", title, flags=re.I)
    out["title"] = (title[:1].upper() + title[1:])[:160] if title else ""
    out["kind"] = kind_of(out["title"])
    return out


def label(when: datetime, now: datetime) -> str:
    """"today 5:00 PM", "tomorrow 9:00 AM", "Fri 5:00 PM", "Nov 14 5:00 PM", in the person's time zone."""
    clock = when.strftime("%I:%M %p").lstrip("0")
    days = (when.date() - now.date()).days
    if days == 0:
        return f"today {clock}"
    if days == 1:
        return f"tomorrow {clock}"
    if 1 < days < 7:
        return f"{when.strftime('%a')} {clock}"
    if days < 0:
        return f"{when.strftime('%b')} {when.day} {clock}"
    return f"{when.strftime('%b')} {when.day} {clock}"


def next_due(due_at: str | None, repeat: str, tz: str | None = "UTC", after: datetime | None = None) -> str | None:
    """When a repeating task comes round again: the next daily / weekday / weekly slot after `after` (default now),
    keeping the same time of day in the person's time zone."""
    if repeat == "none":
        return None
    zone = _zone(tz)
    after = (after or datetime.now(timezone.utc)).astimezone(zone)
    base = datetime.fromisoformat(due_at).astimezone(zone) if due_at else after.replace(hour=DEFAULT_HOUR, minute=0, second=0, microsecond=0)
    step = timedelta(days=7 if repeat == "weekly" else 1)
    nxt = base + step
    while nxt <= after or (repeat == "weekdays" and nxt.weekday() >= 5):
        nxt += step if repeat != "weekdays" else timedelta(days=1)
    return nxt.astimezone(timezone.utc).isoformat()
