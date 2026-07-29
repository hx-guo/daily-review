"""Publication-date rules.

Four dates travel with every paper: preprint (arXiv v1), accepted (journal),
published (journal) and ingested (this site's run date). The archive axis uses
the earliest of the three academic dates; the news axis uses `ingested`.

Everything here is pure — HTTP lives in `gdr.datesource` — so the rules stay
testable without the network. Sources disagree wildly on format (ISO from AAS,
"3 June 2026" from Springer, `2026-07-00` from ADS, a scheduled future issue
month from Elsevier), so parsing is deliberately conservative: anything not
recognised becomes an empty string rather than a guessed date.
"""
from __future__ import annotations

import re

_MONTHS = {name.lower(): n for n, name in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], start=1)}

_ISO_RE = re.compile(r"^(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?$")
_LONG_RE = re.compile(r"^(\d{1,2})\s+([A-Za-z]+)\.?\s+(\d{4})$")
_LONG_US_RE = re.compile(r"^([A-Za-z]+)\.?\s+(\d{1,2}),\s*(\d{4})$")


def _build(year: int, month: int | None, day: int | None) -> tuple[str, str]:
    if not year:
        return "", ""
    if month:
        if day:
            return f"{year:04d}-{month:02d}-{day:02d}", "day"
        return f"{year:04d}-{month:02d}", "month"
    return f"{year:04d}", "year"


def parse_partial_date(value) -> tuple[str, str]:
    """Return (date, precision) for anything a source might hand us.

    Accepts Crossref `date-parts` ([[2026, 7, 8]] or [2026, 7]), ISO strings with
    or without month/day, ADS's `2026-07-00`, and the English long forms Springer
    and Pleiades deposit. Unrecognised input returns ("", "").
    """
    if isinstance(value, (list, tuple)):
        parts = value[0] if value and isinstance(value[0], (list, tuple)) else value
        nums = [int(p) for p in list(parts)[:3] if isinstance(p, (int, float)) and int(p)]
        if not nums:
            return "", ""
        return _build(nums[0], nums[1] if len(nums) > 1 else None,
                      nums[2] if len(nums) > 2 else None)
    text = str(value or "").strip()
    if not text:
        return "", ""
    m = _ISO_RE.match(text)
    if m:
        year, month, day = (int(g) if g else 0 for g in m.groups())
        return _build(year, month or None, day or None)
    m = _LONG_RE.match(text)
    if m:
        day, name, year = m.group(1), m.group(2).lower(), m.group(3)
        if name in _MONTHS:
            return _build(int(year), _MONTHS[name], int(day))
    m = _LONG_US_RE.match(text)
    if m:
        name, day, year = m.group(1).lower(), m.group(2), m.group(3)
        if name in _MONTHS:
            return _build(int(year), _MONTHS[name], int(day))
    return "", ""


def sort_value(date: str) -> str:
    """Pad a coarse date so dates of different precision can be compared."""
    date = (date or "").strip()
    if not date:
        return ""
    parts = date.split("-")
    year = parts[0]
    month = parts[1] if len(parts) > 1 else "01"
    day = parts[2] if len(parts) > 2 else "01"
    return f"{year}-{month}-{day}"


def earliest(*dates: str) -> str:
    """Earliest non-empty date, returned at its ORIGINAL precision."""
    known = [d for d in dates if (d or "").strip()]
    if not known:
        return ""
    return min(known, key=sort_value)


def pick_published(*, online=None, printed=None, created=None,
                   ads_pubdate=None) -> dict:
    """Choose the journal publication date and record where it came from.

    Priority is online > print > Crossref record creation > ADS pubdate, with one
    correction: Elsevier deposits a SCHEDULED issue date (e.g. 2026-08) that is
    later than the day the article actually appeared, so a print date after
    `created` is dropped in favour of `created`.
    """
    online_d, online_p = parse_partial_date(online)
    print_d, print_p = parse_partial_date(printed)
    created_d, created_p = parse_partial_date(created)
    ads_d, ads_p = parse_partial_date(ads_pubdate)
    if online_d:
        return {"date": online_d, "precision": online_p, "source": "crossref-online"}
    if print_d and (not created_d or sort_value(print_d) <= sort_value(created_d)):
        return {"date": print_d, "precision": print_p, "source": "crossref-print"}
    if created_d:
        return {"date": created_d, "precision": created_p, "source": "crossref-created"}
    if print_d:
        return {"date": print_d, "precision": print_p, "source": "crossref-print"}
    if ads_d:
        return {"date": ads_d, "precision": ads_p, "source": "ads-pubdate"}
    return {"date": "", "precision": "", "source": ""}


def archive_date(dates: dict) -> str:
    """The archive axis: earliest of preprint / accepted / published, at day
    precision so it can key a calendar day. `ingested` never participates."""
    return sort_value(earliest(dates.get("preprint", ""),
                               dates.get("accepted", ""),
                               dates.get("published", "")))
