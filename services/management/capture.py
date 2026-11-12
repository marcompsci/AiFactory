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
FULL_WD = r"monday|tuesday|wednesday|thursday|friday|saturday|sunday"
ABBR_WD = r"mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun"  # only after "by", "on"…: "buy sun screen" isn't a date
_WD = rf"{FULL_WD}|{ABBR_WD}"
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
MONTH_RX = (r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?"
            r"|nov(?:ember)?|dec(?:ember)?")
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


def _month_day(cut, low: str, now: datetime):
    """"nov 14", "November 14th", "11/14", optionally after a weekday ("fri nov 14"). A date that doesn't exist
    ("feb 30") is left in the text, so you see it wasn't understood."""
    pat = (rf"\s(?:(?:by|on|for|due) )?(?:(?:{_WD}),? )?(?P<mon>{MONTH_RX})\.? (?P<day>\d{{1,2}})(?:st|nd|rd|th)?\b(?=\s)",
           rf"\s(?:(?:by|on|for|due) )?(?:(?:{_WD}),? )?(?P<mon>1[0-2]|0?[1-9])/(?P<day>\d{{1,2}})(?=\s)")
    for rx in pat:
        m = re.search(rx, low)
        if not m:
            continue
        mon = m.group("mon")
        month = int(mon) if mon.isdigit() else MONTHS.index(mon[:3]) + 1
        try:
            d = now.date().replace(month=month, day=int(m.group("day")))
        except ValueError:
            for year in (now.year + 1, now.year + 2, now.year + 3, now.year + 4):  # feb 29 in a later leap year
                try:
                    d = now.date().replace(year=year, month=month, day=int(m.group("day")))
                    break
                except ValueError:
                    d = None
            if d is None:
                return None
        if d < now.date():
            d = d.replace(year=d.year + 1) if not (d.month == 2 and d.day == 29) else d
        cut(re.escape(m.group(0)))
        return d
    return None


def kind_of(text: str) -> str:
    t = text.lower()
    for kind in ("code", "research", "write"):
        if re.search(KIND_WORDS[kind], t):
            return kind
    return "personal"


def parse(text: str, tz: str | None = "UTC", now: datetime | None = None) -> dict:
    """Read a typed task. Returns {title, due_at (UTC ISO or None), due_label, priority, budget_usd, kind, repeat,
    list_name, estimate_minutes}."""
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

    # V6.69 a list tag ("#echo") and V6.73 an estimate ("30m", "1.5h", "2 hours")
    out["list_name"] = None
    m = cut(r"\s#([a-z0-9][a-z0-9_-]{0,39})(?=\s)")
    if m:
        out["list_name"] = m.group(1)
    m = cut(r"\s\$\s?(\d{1,2}(?:\.\d{1,2})?)\b")
    if m:
        v = float(m.group(1))
        out["budget_usd"] = v if 0 < v <= 50 else None
    if cut(r"\s(urgent|asap|high priority|important|!!?)(?=\s)"):
        out["priority"] = "urgent"
    elif cut(r"\s(low priority|someday|whenever|no rush)(?=\s)"):
        out["priority"] = "low"
    out["estimate_minutes"] = None
    # Only a plausible length is read (and taken out of the title): "2h", "45 min", "for 2 m". A bare "m" counts only when
    # written on the number at the very end ("... 45m") or after "for"/"~", so "100m sprint" and "2 m of rope" stay words.
    for m in re.finditer(r"\s(for |~)?(\d{1,3}(?:\.\d)?)(\s?)(min|mins|minutes|m|h|hr|hrs|hour|hours)(?=\s)", low):
        unit = m.group(4)
        if unit == "m" and not m.group(1) and (m.group(3) or low[m.end():].strip()):
            continue
        v = float(m.group(2)) * (60 if unit.startswith("h") else 1)
        if 5 <= v <= 600:
            out["estimate_minutes"] = int(v)
            t = t[:m.start()] + " " + t[m.end():]
            low = t.lower()
            break

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
    m = (cut(r"\s(?:at|by|@)\s?(1[0-2]|0?[1-9])(?::([0-5]\d))?\s?(am|pm)(?=\s)")
         or cut(r"\s(1[0-2]|0?[1-9])(?::([0-5]\d))?\s?(am|pm)(?=\s)"))
    if m:
        at = time(int(m.group(1)) % 12 + (12 if m.group(3) == "pm" else 0), int(m.group(2) or 0))
    else:
        m = cut(r"\s(?:at|by)\s([01]?\d|2[0-3]):([0-5]\d)(?=\s)")
        if m:
            at = time(int(m.group(1)), int(m.group(2)))
    day = None
    soft = False  # a day said without a time ("today", "every day"): if 5pm has passed, it means the end of today
    if cut(r"\s(?:by |for )?tonight(?=\s)"):
        day, at = now.date(), at or time(20, 0)
        soft = True
    elif cut(r"\s(?:by |for )?this morning(?=\s)"):
        day, at = now.date(), at or time(11, 0)
        soft = True
    elif cut(r"\s(?:by |for |due )?(?:end of (?:the )?day|eod|today)(?=\s)"):
        day, soft = now.date(), at is None
    elif cut(r"\s(?:by |for |due )?tomorrow(?=\s)"):
        day = now.date() + timedelta(days=1)
    elif m := cut(r"\s(?:by |for |due )?(next week|end of (?:the )?week|eow)(?=\s)"):
        if m.group(1) == "next week":
            ahead = (7 - now.weekday()) % 7 or 7  # next Monday
        else:
            ahead = (4 - now.weekday()) % 7  # this Friday (today, on a Friday)
        day, soft = now.date() + timedelta(days=ahead), at is None
    elif m := cut(r"\s(?:by |on |for |due |this |next )?in (\d{1,2}) (day|days|week|weeks)(?=\s)"):
        day = now.date() + timedelta(days=int(m.group(1)) * (7 if m.group(2).startswith("week") else 1))
    else:
        day = _month_day(cut, low, now)
        if day is None:
            m = cut(rf"\s(?:(?:by|on|for|due|this|next) )?({FULL_WD})(?=\s)") or cut(rf"\s(?:by|on|for|due|this|next) ({ABBR_WD})\.?(?=\s)")
            if m:
                ahead = (_weekday_index(m.group(1)) - now.weekday()) % 7
                if ahead == 0 and (at or time(DEFAULT_HOUR, 0)) <= now.time():
                    ahead = 7  # "friday" said on a Friday evening means next Friday
                day = now.date() + timedelta(days=ahead)
    if day is None and weekly_day is not None:
        ahead = (weekly_day - now.weekday()) % 7
        day = now.date() + timedelta(days=ahead)
        if ahead == 0 and (at or time(DEFAULT_HOUR, 0)) <= now.time():
            day += timedelta(days=7)
    if day is None and at is not None:  # only a time: today if it's still ahead, otherwise tomorrow
        day = now.date() if at > now.time() else now.date() + timedelta(days=1)
    if day is None and out["repeat"] in ("daily", "weekdays"):
        day = now.date()
        if (at or time(DEFAULT_HOUR, 0)) <= now.time():
            day += timedelta(days=1)  # every day, starting with the next one still ahead
    if day is not None:
        when = datetime.combine(day, at or time(DEFAULT_HOUR, 0), tzinfo=zone)
        if soft and when <= now:
            when = datetime.combine(now.date(), time(23, 59), tzinfo=zone)  # "today" after 5pm: by the end of today
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
