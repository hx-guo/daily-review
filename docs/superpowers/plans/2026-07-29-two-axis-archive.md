# 双轴归档与修订历史 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把编辑决策从"一天一份综述"下沉到"一篇论文一条决策"，由此得到收录日 / 归档日两条时间轴、可回看的历史版本，并让补录只为新论文付费。

**Architecture:** 每篇论文携带四个日期（预印本 / 接收 / 刊出 / 收录）和一条一次性生成的 `decision`；数据按**收录日**分文件存储（`data/ingest/<date>.json`），正常路径只追加不改写；日级综述 `compose_review()` 变成纯函数，两条轴和任意历史版本都只是对同一批决策的不同分组。

**Tech Stack:** Python 3.11、pytest、Jinja2、requests、feedparser、Crossref / ADS / arXiv REST API。

**设计文档：** `docs/superpowers/specs/2026-07-29-two-axis-archive-revision-design.md`（每个任务的取舍理由都在那里，遇到判断不了的细节回去查）。

## Global Constraints

- **全程在分支 `feat/two-axis-archive` 上做，Task 13 之前绝不合并进 main。** 仓库的 GH Actions cron 每天北京时间 10:00 从 main 跑完整流水线并自动部署；main 上出现"新代码 + 旧数据"或"旧代码 + 新数据"的中间态会被自动发布出去。
- Python 用仓库里的 uv venv：**所有命令走 `.venv/bin/python`**，`system python3` 是 3.9，不要用。测试命令一律 `.venv/bin/python -m pytest -q`。
- 改造前基线：`110 passed`。任何一个任务结束时测试都必须全绿。
- 提交签名要绕过 1Password agent：`git -c gpg.ssh.program=ssh-keygen -c user.signingkey="$HOME/.ssh/id_ed25519_headless" commit -m "..."`。直接 `git commit` 会以 `fatal: failed to write commit object` 失败。
- **绝不把 `ADS_API_TOKEN` 的值写进任何文件**，它只存在于环境变量和 GitHub secret 里。
- 代码、注释、docstring、commit message 用英文；页面上的文案用中文。
- 日期字符串一律 ISO：日精度 `YYYY-MM-DD`，月精度 `YYYY-MM`，年精度 `YYYY`，未知为空串 `""`。**永远不要产出 `YYYY-MM-00` 这种 ADS 原始格式**。
- 本机访问 arXiv / Crossref / ADS / opencode 需要 SOCKS 代理 `socks5://127.0.0.1:8235`（venv 里已装 `httpx[socks]`、`socksio`、`pysocks`）。只有 Task 9 和 Task 13 需要联网。

---

### Task 1: 日期规则（纯函数）

**Files:**
- Create: `src/gdr/dates.py`
- Test: `tests/test_dates.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `parse_partial_date(value) -> tuple[str, str]` — 返回 `(日期, 精度)`，精度取 `"day" | "month" | "year" | ""`
  - `sort_value(date: str) -> str` — 把月/年精度补成可比较的日精度，空串返回空串
  - `earliest(*dates: str) -> str` — 返回最早的那个**原始**字符串（保持原精度）
  - `pick_published(*, online=None, printed=None, created=None, ads_pubdate=None) -> dict` — 返回 `{"date","precision","source"}`
  - `archive_date(dates: dict) -> str` — 返回日精度 ISO 串

- [ ] **Step 1: Write the failing test**

创建 `tests/test_dates.py`：

```python
from gdr.dates import archive_date, earliest, parse_partial_date, pick_published, sort_value


def test_parse_iso_day_month_and_year():
    assert parse_partial_date("2026-05-23") == ("2026-05-23", "day")
    assert parse_partial_date("2026-07") == ("2026-07", "month")
    assert parse_partial_date("2026") == ("2026", "year")


def test_parse_ads_zero_day_is_month_precision():
    """ADS pubdate writes an unknown day as 00; it must never become a real day."""
    assert parse_partial_date("2026-07-00") == ("2026-07", "month")


def test_parse_crossref_date_parts():
    assert parse_partial_date([[2026, 7, 8]]) == ("2026-07-08", "day")
    assert parse_partial_date([2026, 9]) == ("2026-09", "month")


def test_parse_english_long_form_used_by_springer_and_pleiades():
    assert parse_partial_date("3 June 2026") == ("2026-06-03", "day")
    assert parse_partial_date("26 May 2026") == ("2026-05-26", "day")
    assert parse_partial_date("January 9, 2026") == ("2026-01-09", "day")


def test_unparseable_input_yields_empty_rather_than_a_guess():
    for junk in ("", None, "in press", "n.d.", [], [[]]):
        assert parse_partial_date(junk) == ("", "")


def test_sort_value_pads_coarse_precision():
    assert sort_value("2026-07") == "2026-07-01"
    assert sort_value("2026") == "2026-01-01"
    assert sort_value("2026-07-08") == "2026-07-08"
    assert sort_value("") == ""


def test_earliest_ignores_blanks_and_keeps_original_precision():
    assert earliest("", "2026-07", "2026-07-08") == "2026-07"
    assert earliest("", "") == ""


def test_pick_published_prefers_online():
    got = pick_published(online=[[2026, 7, 3]], printed=[[2026, 7, 10]],
                         created=[[2026, 7, 3]])
    assert got == {"date": "2026-07-03", "precision": "day",
                   "source": "crossref-online"}


def test_pick_published_rejects_elsevier_future_issue_date():
    """Elsevier deposits a scheduled issue month later than the real online date."""
    got = pick_published(online=None, printed=[[2026, 8]], created=[[2026, 7, 6]])
    assert got == {"date": "2026-07-06", "precision": "day",
                   "source": "crossref-created"}


def test_pick_published_keeps_print_when_not_in_the_future():
    got = pick_published(online=None, printed=[[2026, 4, 24]], created=[[2026, 5, 2]])
    assert got == {"date": "2026-04-24", "precision": "day",
                   "source": "crossref-print"}


def test_pick_published_falls_back_to_ads_pubdate():
    got = pick_published(ads_pubdate="2026-07-00")
    assert got == {"date": "2026-07", "precision": "month", "source": "ads-pubdate"}


def test_pick_published_with_nothing_known():
    assert pick_published() == {"date": "", "precision": "", "source": ""}


def test_archive_date_is_the_earliest_academic_date_at_day_precision():
    dates = {"preprint": "2026-03-14", "accepted": "2026-06-21",
             "published": "2026-07-08", "ingested": "2026-07-22"}
    assert archive_date(dates) == "2026-03-14"


def test_archive_date_ignores_ingested_and_pads_month_precision():
    assert archive_date({"preprint": "", "accepted": "",
                         "published": "2026-07", "ingested": "2026-07-22"}) == "2026-07-01"


def test_archive_date_empty_when_no_academic_date_is_known():
    assert archive_date({"ingested": "2026-07-22"}) == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_dates.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'gdr.dates'`

- [ ] **Step 3: Write minimal implementation**

创建 `src/gdr/dates.py`：

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_dates.py -q`
Expected: PASS（14 passed）

Run: `.venv/bin/python -m pytest -q`
Expected: PASS（124 passed）

- [ ] **Step 5: Commit**

```bash
git checkout -b feat/two-axis-archive
git add src/gdr/dates.py tests/test_dates.py
git -c gpg.ssh.program=ssh-keygen -c user.signingkey="$HOME/.ssh/id_ed25519_headless" \
  commit -m "feat(dates): parse partial publication dates and pick the archive date"
```

---

### Task 2: 日期抓取（Crossref + arXiv）

**Files:**
- Create: `src/gdr/datesource.py`
- Test: `tests/test_datesource.py`

**Interfaces:**
- Consumes: `gdr.dates.parse_partial_date`, `gdr.dates.pick_published`
- Produces:
  - `fetch_crossref_dates(doi: str, mailto: str = "", http_get=requests.get) -> dict` — 返回 `{"accepted","published","published_precision","published_source","received"}`，任何失败返回 `{}`
  - `fetch_arxiv_v1_date(arxiv_id: str, http_get=requests.get) -> str` — 返回日精度 ISO 串，失败返回 `""`

- [ ] **Step 1: Write the failing test**

创建 `tests/test_datesource.py`：

```python
import json

from gdr.datesource import fetch_arxiv_v1_date, fetch_crossref_dates


class FakeResponse:
    def __init__(self, payload=None, status_code=200, text=""):
        self._payload = payload
        self.status_code = status_code
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _crossref(message):
    calls = []

    def http_get(url, params=None, timeout=None):
        calls.append((url, params))
        return FakeResponse({"message": message})

    return http_get, calls


def test_crossref_reads_aas_iso_accepted_and_online_date():
    http_get, calls = _crossref({
        "published-online": {"date-parts": [[2026, 7, 3]]},
        "published-print": {"date-parts": [[2026, 7, 10]]},
        "created": {"date-parts": [[2026, 7, 3]]},
        "assertion": [{"name": "accepted", "value": "2026-05-23"},
                      {"name": "received", "value": "2026-02-16"}],
    })

    got = fetch_crossref_dates("10.3847/1538-4357/ae75dc", http_get=http_get)

    assert got == {"accepted": "2026-05-23", "published": "2026-07-03",
                   "published_precision": "day",
                   "published_source": "crossref-online", "received": "2026-02-16"}
    assert calls[0][0].endswith("/10.3847/1538-4357/ae75dc")


def test_crossref_reads_springer_english_long_form_accepted():
    http_get, _ = _crossref({
        "published-online": {"date-parts": [[2026, 7, 10]]},
        "assertion": [{"label": "Accepted", "value": "3 June 2026"},
                      {"label": "Received", "value": "9 January 2026"}],
    })

    got = fetch_crossref_dates("10.1038/s41550-026-02910-w", http_get=http_get)

    assert got["accepted"] == "2026-06-03"
    assert got["received"] == "2026-01-09"


def test_crossref_elsevier_scheduled_issue_falls_back_to_created():
    http_get, _ = _crossref({
        "published-print": {"date-parts": [[2026, 8]]},
        "created": {"date-parts": [[2026, 7, 6]]},
    })

    got = fetch_crossref_dates("10.1016/j.jheap.2026.100692", http_get=http_get)

    assert got["published"] == "2026-07-06"
    assert got["published_source"] == "crossref-created"
    assert got["accepted"] == ""


def test_crossref_aps_gives_received_but_no_accepted():
    http_get, _ = _crossref({
        "published-online": {"date-parts": [[2026, 7, 7]]},
        "assertion": [{"name": "received", "value": "2026-03-19"}],
    })

    got = fetch_crossref_dates("10.1103/v7dk-q18l", http_get=http_get)

    assert got["accepted"] == ""
    assert got["received"] == "2026-03-19"


def test_crossref_failures_return_empty_dict_rather_than_raising():
    def boom(url, params=None, timeout=None):
        raise RuntimeError("network down")

    assert fetch_crossref_dates("10.1/x", http_get=boom) == {}
    assert fetch_crossref_dates("", http_get=boom) == {}
    assert fetch_crossref_dates(
        "10.1/x", http_get=lambda *a, **k: FakeResponse(status_code=404)) == {}


ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2603.09495v2</id>
    <published>2026-03-12T17:59:59Z</published>
    <updated>2026-06-01T10:00:00Z</updated>
    <title>A paper</title>
    <summary>abstract</summary>
  </entry>
</feed>"""


def test_arxiv_v1_date_is_the_published_field_not_updated():
    def http_get(url, params=None, timeout=None):
        assert params["id_list"] == "2603.09495"
        return FakeResponse(text=ATOM)

    assert fetch_arxiv_v1_date("2603.09495", http_get=http_get) == "2026-03-12"


def test_arxiv_v1_date_empty_on_failure():
    def boom(url, params=None, timeout=None):
        raise RuntimeError("network down")

    assert fetch_arxiv_v1_date("2603.09495", http_get=boom) == ""
    assert fetch_arxiv_v1_date("", http_get=boom) == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_datesource.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'gdr.datesource'`

- [ ] **Step 3: Write minimal implementation**

创建 `src/gdr/datesource.py`：

```python
"""Fetch the three academic dates from Crossref and arXiv.

Crossref is token-free and gives the journal dates ADS cannot: `published-online`
is usually day-precise where ADS's `pubdate` is month-only, and some publishers
deposit the acceptance date in the `assertion` array. Coverage is uneven by
publisher (AAS and Springer deposit acceptance, APS and Elsevier do not), so
every field here is best-effort: a missing or unparseable value stays empty.
"""
from __future__ import annotations

import feedparser
import requests

from gdr import config
from gdr.dates import parse_partial_date, pick_published

ARXIV_API = "http://export.arxiv.org/api/query"


def _assertion(message: dict, needle: str) -> str:
    for item in (message.get("assertion") or []):
        name = f"{item.get('name', '')} {item.get('label', '')}".lower()
        if needle in name:
            date, _ = parse_partial_date(item.get("value"))
            if date:
                return date
    return ""


def fetch_crossref_dates(doi: str, mailto: str = "",
                         http_get=requests.get) -> dict:
    """Journal dates for one DOI. Returns {} when the DOI is unknown or the
    request fails — callers treat that as "no journal dates yet"."""
    doi = (doi or "").strip()
    if not doi:
        return {}
    try:
        response = http_get(f"{config.CROSSREF_API_URL}/{doi}",
                            params={"mailto": mailto}, timeout=30)
        if getattr(response, "status_code", None) != 200:
            return {}
        message = response.json().get("message", {})
    except Exception:
        return {}
    if not isinstance(message, dict):
        return {}
    published = pick_published(
        online=(message.get("published-online") or {}).get("date-parts"),
        printed=(message.get("published-print") or {}).get("date-parts"),
        created=(message.get("created") or {}).get("date-parts"),
    )
    return {
        "accepted": _assertion(message, "accept"),
        "published": published["date"],
        "published_precision": published["precision"],
        "published_source": published["source"],
        "received": _assertion(message, "receiv"),
    }


def fetch_arxiv_v1_date(arxiv_id: str, http_get=requests.get) -> str:
    """arXiv v1 submission date (the preprint date). Empty on any failure."""
    arxiv_id = (arxiv_id or "").strip()
    if not arxiv_id:
        return ""
    try:
        response = http_get(ARXIV_API,
                            params={"id_list": arxiv_id, "max_results": 1},
                            timeout=30)
        entries = feedparser.parse(getattr(response, "text", "")).entries
    except Exception:
        return ""
    if not entries:
        return ""
    return str(entries[0].get("published", ""))[:10]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_datesource.py -q`
Expected: PASS（7 passed）

Run: `.venv/bin/python -m pytest -q`
Expected: PASS（131 passed）

- [ ] **Step 5: Commit**

```bash
git add src/gdr/datesource.py tests/test_datesource.py
git -c gpg.ssh.program=ssh-keygen -c user.signingkey="$HOME/.ssh/id_ed25519_headless" \
  commit -m "feat(dates): fetch accepted/published dates from Crossref and v1 date from arXiv"
```

---

### Task 3: item 结构与 `IngestDay` 模型

**Files:**
- Modify: `src/gdr/models.py`（在文件末尾追加，不动现有的 `DayData`——迁移还要用它读旧数据）
- Test: `tests/test_models.py`（追加）

**Interfaces:**
- Consumes: `gdr.dates.archive_date`
- Produces:
  - `make_item(paper, score, summary, *, dates, decision=None) -> dict` — 组装一个 item，自动算 `archive_date`
  - `item_to_dict(item: dict) -> dict` / `item_from_dict(d: dict) -> dict`
  - `IngestDay` dataclass，字段 `ingested: str` / `items: list[dict]`，带 `to_dict` / `from_dict`
  - item 的键：`paper` / `score` / `summary` / `dates` / `archive_date` / `decision` / `review_attempts` / `decision_final`
  - `dates` 的键：`preprint` / `accepted` / `published` / `published_precision` / `published_source` / `received` / `ingested`

- [ ] **Step 1: Write the failing test**

追加到 `tests/test_models.py`：

```python
from gdr.models import IngestDay, item_from_dict, item_to_dict, make_item


def _paper(pid="arxiv:1"):
    return Paper(id=pid, source="arxiv", title="t", authors=["A"], abstract="a",
                 categories=[], published="2026-03-12", url="")


def _score():
    return RelevanceScore(score=90, tags=["GRB"], layer="core", reason="r")


def test_make_item_computes_archive_date_from_the_earliest_academic_date():
    item = make_item(_paper(), _score(), None,
                     dates={"preprint": "2026-03-12", "accepted": "2026-06-21",
                            "published": "2026-07-08", "ingested": "2026-07-22"})

    assert item["archive_date"] == "2026-03-12"
    assert item["dates"]["ingested"] == "2026-07-22"
    assert item["decision"] is None
    assert item["review_attempts"] == 0
    assert item["decision_final"] is False


def test_make_item_without_academic_dates_archives_under_the_ingest_day():
    """A paper we know nothing about still has to land on some calendar day."""
    item = make_item(_paper(), _score(), None, dates={"ingested": "2026-07-22"})

    assert item["archive_date"] == "2026-07-22"


def test_ingest_day_roundtrips_dates_and_decision():
    decision = {"level": "headline", "title": "T", "evidence": "E", "impact": "I",
                "reason": "R", "watchlist": ["w（arxiv:1）"], "reviewed_at": "2026-07-22"}
    item = make_item(_paper(), _score(), None,
                     dates={"preprint": "2026-03-12", "ingested": "2026-07-22"},
                     decision=decision)
    day = IngestDay(ingested="2026-07-22", items=[item])

    back = IngestDay.from_dict(json.loads(json.dumps(day.to_dict())))

    assert back.ingested == "2026-07-22"
    assert back.items[0]["paper"].id == "arxiv:1"
    assert back.items[0]["score"].layer == "core"
    assert back.items[0]["summary"] is None
    assert back.items[0]["decision"]["level"] == "headline"
    assert back.items[0]["archive_date"] == "2026-03-12"


def test_item_from_dict_defaults_missing_optional_fields():
    raw = item_to_dict(make_item(_paper(), _score(), None,
                                 dates={"ingested": "2026-07-22"}))
    del raw["review_attempts"], raw["decision_final"], raw["decision"]

    item = item_from_dict(raw)

    assert item["decision"] is None
    assert item["review_attempts"] == 0
    assert item["decision_final"] is False
```

`tests/test_models.py` 顶部若还没有 `import json`，加上。

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_models.py -q`
Expected: FAIL，`ImportError: cannot import name 'IngestDay' from 'gdr.models'`

- [ ] **Step 3: Write minimal implementation**

追加到 `src/gdr/models.py` 末尾：

```python
EMPTY_DATES = {
    "preprint": "", "accepted": "", "published": "",
    "published_precision": "", "published_source": "", "received": "",
    "ingested": "",
}


def make_item(paper: Paper, score: RelevanceScore, summary: PaperSummary | None, *,
              dates: dict, decision: dict | None = None) -> dict:
    """Assemble one stored item. `archive_date` is derived, never passed in, so it
    can never drift from the dates it is supposed to summarise. A paper with no
    known academic date falls back to its ingest day — it still has to land on a
    calendar day somewhere."""
    from gdr.dates import archive_date  # local import: models must stay import-light

    merged = {**EMPTY_DATES, **(dates or {})}
    return {
        "paper": paper,
        "score": score,
        "summary": summary,
        "dates": merged,
        "archive_date": archive_date(merged) or merged["ingested"],
        "decision": decision,
        "review_attempts": 0,
        "decision_final": False,
    }


def item_to_dict(item: dict) -> dict:
    return {
        "paper": item["paper"].to_dict(),
        "score": item["score"].to_dict(),
        "summary": item["summary"].to_dict() if item.get("summary") else None,
        "dates": dict(item["dates"]),
        "archive_date": item["archive_date"],
        "decision": item.get("decision"),
        "review_attempts": item.get("review_attempts", 0),
        "decision_final": item.get("decision_final", False),
    }


def item_from_dict(d: dict) -> dict:
    return {
        "paper": Paper.from_dict(d["paper"]),
        "score": RelevanceScore.from_dict(d["score"]),
        "summary": PaperSummary.from_dict(d["summary"]) if d.get("summary") else None,
        "dates": {**EMPTY_DATES, **(d.get("dates") or {})},
        "archive_date": d.get("archive_date", ""),
        "decision": d.get("decision"),
        "review_attempts": d.get("review_attempts", 0),
        "decision_final": d.get("decision_final", False),
    }


@dataclass
class IngestDay:
    """One run's harvest. Files are keyed by ingest date and, on the normal path,
    are written once and never rewritten."""
    ingested: str
    items: list[dict]

    def to_dict(self) -> dict:
        return {"ingested": self.ingested,
                "items": [item_to_dict(it) for it in self.items]}

    @classmethod
    def from_dict(cls, d: dict) -> IngestDay:
        return cls(ingested=d["ingested"],
                   items=[item_from_dict(it) for it in d.get("items", [])])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_models.py -q`
Expected: PASS

Run: `.venv/bin/python -m pytest -q`
Expected: PASS（135 passed）

- [ ] **Step 5: Commit**

```bash
git add src/gdr/models.py tests/test_models.py
git -c gpg.ssh.program=ssh-keygen -c user.signingkey="$HOME/.ssh/id_ed25519_headless" \
  commit -m "feat(models): per-paper dates, decision and the IngestDay container"
```

---

### Task 4: `compose_review()` — 日级综述变纯函数

**Files:**
- Modify: `src/gdr/daily_review.py`（新增 `compose_review`，保留现有 `make_daily_review` 不动——Task 5 才删）
- Test: `tests/test_compose_review.py`

**Interfaces:**
- Consumes: `gdr.models.make_item`、`gdr.models.DailyReview`
- Produces: `compose_review(date: str, items: list[dict]) -> DailyReview`
  - stories 按 `breaking` 在前、`headline` 在后，同级按 `score.score` 降序
  - story 字段：`paper_id` / `level` / `title` / `evidence` / `impact` / `reason`
  - watchlist 按出现顺序去重
  - `editorial_version` 恒为 2

- [ ] **Step 1: Write the failing test**

创建 `tests/test_compose_review.py`：

```python
import pytest

from gdr.daily_review import compose_review
from gdr.models import Paper, RelevanceScore, make_item


class ExplodingLLM:
    """compose_review must be pure; touching a model here is a test failure."""

    def complete(self, model, system, user, temperature=0.3):
        raise AssertionError("compose_review must not call the LLM")


def _item(pid, layer="core", score=90, decision=None):
    paper = Paper(id=pid, source="arxiv", title=f"t {pid}", authors=["A"],
                  abstract="a", categories=[], published="2026-07-18", url="")
    rs = RelevanceScore(score=score, tags=["GRB"], layer=layer, reason="r")
    return make_item(paper, rs, None, dates={"ingested": "2026-07-18"},
                     decision=decision)


def _decision(level, pid, watchlist=None):
    return {"level": level, "title": f"标题 {pid}", "evidence": "证据",
            "impact": "影响", "reason": "理由",
            "watchlist": watchlist if watchlist is not None else [],
            "reviewed_at": "2026-07-18"}


def test_compose_review_takes_no_llm_and_orders_breaking_before_headline():
    items = [_item("arxiv:1", score=60, decision=_decision("headline", "arxiv:1")),
             _item("arxiv:2", score=95, decision=_decision("breaking", "arxiv:2")),
             _item("arxiv:3", score=80, decision=_decision("headline", "arxiv:3")),
             _item("arxiv:4", score=99, decision=_decision("reject", "arxiv:4")),
             _item("arxiv:5", layer="edge", score=10)]

    review = compose_review("2026-07-18", items)

    assert [s["paper_id"] for s in review.stories] == ["arxiv:2", "arxiv:3", "arxiv:1"]
    assert [s["level"] for s in review.stories] == ["breaking", "headline", "headline"]
    assert review.stories[0]["impact"] == "影响"
    assert review.editorial_version == 2


def test_compose_review_is_pure_and_repeatable():
    items = [_item("arxiv:1", decision=_decision("headline", "arxiv:1"))]

    first = compose_review("2026-07-18", items)
    second = compose_review("2026-07-18", items)

    assert first.to_dict() == second.to_dict()


def test_watchlist_is_concatenated_in_story_order_and_deduped():
    items = [_item("arxiv:1", score=95,
                   decision=_decision("breaking", "arxiv:1",
                                      ["等待独立确认（arxiv:1）", "共用信号（arxiv:1）"])),
             _item("arxiv:2", score=80,
                   decision=_decision("headline", "arxiv:2", ["共用信号（arxiv:1）"])),
             _item("arxiv:3", score=99,
                   decision=_decision("reject", "arxiv:3", ["被拒的不算"]))]

    review = compose_review("2026-07-18", items)

    assert review.watchlist == ["等待独立确认（arxiv:1）", "共用信号（arxiv:1）"]


def test_quiet_day_overview_counts_core_and_related_only():
    items = [_item("arxiv:1", decision=_decision("reject", "arxiv:1")),
             _item("arxiv:2", layer="related", score=50,
                   decision=_decision("reject", "arxiv:2")),
             _item("arxiv:3", layer="edge", score=10)]

    review = compose_review("2026-07-18", items)

    assert review.stories == []
    assert review.overview == "当日 2 篇核心与相关文献均为常规推进，核心 1 篇已按优先级列于下方。"


def test_day_with_nothing_reviewed_says_no_original_research_met_the_bar():
    items = [_item("arxiv:1", layer="edge", score=10)]

    review = compose_review("2026-07-18", items)

    assert review.overview == "当日 0 篇核心与相关文献中无原始研究达到新闻门槛。"


def test_empty_day():
    review = compose_review("2026-07-18", [])

    assert review.overview == "今日无新文献。"
    assert review.stories == []
    assert review.editorial_version == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_compose_review.py -q`
Expected: FAIL，`ImportError: cannot import name 'compose_review'`

- [ ] **Step 3: Write minimal implementation**

在 `src/gdr/daily_review.py` 中，`_quiet_overview` 之后追加：

```python
_LEVEL_ORDER = {"breaking": 0, "headline": 1}


def compose_review(date: str, items: list[dict]) -> DailyReview:
    """Build a day's review from the decisions already stored on its papers.

    Pure: no LLM, no I/O, no randomness. Both time axes and every historical
    version of an archive day are just different item sets fed through here, so
    this function must stay a deterministic projection of `item["decision"]`.
    """
    if not items:
        return DailyReview(date=date, overview="今日无新文献。", highlights="—",
                           trends="—", editorial_version=2, stories=[], watchlist=[])

    considered = [it for it in items if it["score"].layer in ("core", "related")]
    reviewed = [it for it in considered if it.get("decision")]
    retained = [it for it in reviewed if it["decision"]["level"] != "reject"]
    retained.sort(key=lambda it: (_LEVEL_ORDER.get(it["decision"]["level"], 9),
                                  -it["score"].score))

    stories = [
        {
            "paper_id": it["paper"].id,
            "level": it["decision"]["level"],
            "title": it["decision"]["title"],
            "evidence": it["decision"]["evidence"],
            "impact": it["decision"]["impact"],
            "reason": it["decision"]["reason"],
        }
        for it in retained
    ]
    watchlist = []
    for it in retained:
        watchlist.extend(it["decision"].get("watchlist") or [])
    watchlist = list(dict.fromkeys(watchlist))

    if stories:
        overview = "今日有通过严格复核的重大进展。"
    elif reviewed:
        overview = _quiet_overview(considered, "均为常规推进")
    else:
        overview = _quiet_overview(considered, "中无原始研究达到新闻门槛")

    return DailyReview(date=date, overview=overview,
                       highlights=_legacy_story_lines(stories),
                       trends="\n".join(watchlist), editorial_version=2,
                       stories=stories, watchlist=watchlist)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_compose_review.py -q`
Expected: PASS（6 passed）

Run: `.venv/bin/python -m pytest -q`
Expected: PASS（141 passed）

- [ ] **Step 5: Commit**

```bash
git add src/gdr/daily_review.py tests/test_compose_review.py
git -c gpg.ssh.program=ssh-keygen -c user.signingkey="$HOME/.ssh/id_ed25519_headless" \
  commit -m "feat(review): derive a day's review from per-paper decisions (pure function)"
```

---

### Task 5: `review_paper()` — 逐篇决策、十连重试、熔断

**Files:**
- Modify: `src/gdr/config.py`（新增 5 个常量）
- Modify: `src/gdr/llm.py`（`OpenCodeLLM` 显式配 `max_retries`）
- Modify: `src/gdr/daily_review.py`（新增 `Breaker` / `review_paper`；删除 `make_daily_review`）
- Modify: `src/gdr/pipeline.py`（删除 `_review_for`，它是 `make_daily_review` 的唯一调用点）
- Modify: `src/gdr/reclassify.py`（改用 `compose_review`）
- Rewrite: `tests/test_daily_review.py`（现有用例整体基于 `make_daily_review`，随之重写）
- Modify: `tests/test_reclassify.py`（跟随 `reclassify_day` 的新行为）

**Interfaces:**
- Consumes: `gdr.daily_review.compose_review`、`gdr.daily_review._digest`、`gdr.daily_review._news_eligible`
- Produces:
  - `class Breaker`：`Breaker(limit=config.EDITORIAL_BREAKER_LIMIT)`、`.tripped() -> bool`、`.record(ok: bool) -> None`
  - `review_paper(item: dict, llm, *, breaker: Breaker | None = None, sleep=time.sleep) -> dict | None`
    - 返回 decision dict（键 `level` / `title` / `evidence` / `impact` / `reason` / `watchlist` / `reviewed_at`）
    - 不合格（edge、勘误、无署名短讯）返回 `None` 且不调用 LLM
    - 十连败或熔断已跳闸返回 `None`
- config 新增：`EDITORIAL_ATTEMPTS=10`、`EDITORIAL_BACKOFF=(1,2,4,8,16,30,30,30,30)`、`EDITORIAL_BREAKER_LIMIT=20`、`OPENAI_MAX_RETRIES=4`、`REVIEW_MAX_ROUNDS=3`

- [ ] **Step 1: Write the failing test**

新建 `tests/test_daily_review.py`（**整体替换**旧文件内容）：

```python
import json
import re

from gdr import config
from gdr.daily_review import Breaker, review_paper
from gdr.models import Paper, PaperSummary, RelevanceScore, make_item


def _item(pid="arxiv:1", layer="core", *, title=None, authors=None, abstract=None,
          doi=None, preprint="2026-03-12", ingested="2026-07-18"):
    paper = Paper(
        id=pid, source="arxiv", title=title or f"paper {pid}",
        authors=authors if authors is not None else ["A. Researcher"],
        abstract=abstract if abstract is not None else
        "We report a directly measured transient result with quantitative evidence.",
        categories=[], published=preprint, url="", doi=doi)
    score = RelevanceScore(score=90, tags=["GRB"], layer=layer, reason="直接研究GRB")
    summary = PaperSummary(paper_id=pid, title_zh=f"伽马暴研究 {pid}", team="",
                           tldr="研究了伽马暴", review="", highlight="给出首次观测",
                           relation="")
    return make_item(paper, score, summary,
                     dates={"preprint": preprint, "ingested": ingested})


def _candidate(pid, decision="headline"):
    return json.dumps({"paper_id": pid, "decision": decision,
                       "reason": "摘要给出可能达到新闻门槛的具体结果。"})


def _verified(pid, decision="headline", watchlist=None):
    retained = decision != "reject"
    return json.dumps({
        "paper_id": pid, "decision": decision,
        "title": f"重大进展 {pid}" if retained else "",
        "evidence": "摘要报告了具体的新观测结果。" if retained else "",
        "impact": "改变了对爆发机制的认识。" if retained else "",
        "reason": "结果通过严格复核。" if retained else "未达到重大新闻门槛。",
        "watchlist": watchlist if watchlist is not None else (
            ["等待独立确认"] if retained else []),
    })


def test_review_paper_runs_two_passes_on_a_single_paper(fake_llm_factory):
    llm = fake_llm_factory([_candidate("arxiv:1", "breaking"),
                           _verified("arxiv:1", "breaking")])

    decision = review_paper(_item(), llm)

    assert decision["level"] == "breaking"
    assert decision["title"] == "重大进展 arxiv:1"
    assert decision["reviewed_at"] == "2026-07-18"
    assert len(llm.calls) == 2
    assert "不选择主头条" in llm.calls[0]["user"]
    assert "第二位、更加怀疑" in llm.calls[1]["user"]


def test_prompt_carries_the_papers_own_preprint_and_ingest_dates(fake_llm_factory):
    """The decision is cached forever, so it must not depend on "today"."""
    llm = fake_llm_factory([_candidate("arxiv:1"), _verified("arxiv:1")])

    review_paper(_item(preprint="2026-03-12", ingested="2026-07-18"), llm)

    assert "本文预印本日 2026-03-12" in llm.calls[0]["user"]
    assert "本站于 2026-07-18 收录" in llm.calls[0]["user"]
    assert "今天是" not in llm.calls[0]["user"]


def test_rejected_paper_yields_a_reject_decision_not_none(fake_llm_factory):
    llm = fake_llm_factory([_candidate("arxiv:1", "reject")])

    decision = review_paper(_item(), llm)

    assert decision["level"] == "reject"
    assert decision["title"] == ""
    assert len(llm.calls) == 1


def test_watchlist_signals_carry_their_own_paper_id(fake_llm_factory):
    llm = fake_llm_factory([
        _candidate("arxiv:1"),
        _verified("arxiv:1", watchlist=["等待独立确认",
                                        "（arxiv:9999.99999）另一路信号需后随观测"])])

    decision = review_paper(_item(), llm)

    assert decision["watchlist"] == ["等待独立确认（arxiv:1）",
                                     "另一路信号需后随观测（arxiv:1）"]


def test_edge_and_non_research_papers_are_never_sent_to_the_model(fake_llm_factory):
    llm = fake_llm_factory([])

    assert review_paper(_item(layer="edge"), llm) is None
    assert review_paper(_item(title="Publisher Correction: A result"), llm) is None
    assert review_paper(_item(authors=[], abstract="A short editorial blurb."),
                        llm) is None
    assert llm.calls == []


def test_nine_bad_responses_then_a_good_one_still_succeeds(fake_llm_factory):
    llm = fake_llm_factory(["not json"] * 9 + [_candidate("arxiv:1", "reject")])
    slept = []

    decision = review_paper(_item(), llm, sleep=slept.append)

    assert decision["level"] == "reject"
    assert len(llm.calls) == 10
    assert slept == list(config.EDITORIAL_BACKOFF)


def test_ten_bad_responses_give_up_and_return_none(fake_llm_factory):
    llm = fake_llm_factory(["not json"] * 10)

    assert review_paper(_item(), llm, sleep=lambda s: None) is None
    assert len(llm.calls) == 10


def test_wrong_schema_is_retried_rather_than_becoming_a_false_reject(fake_llm_factory):
    llm = fake_llm_factory([json.dumps({"candidates": []}),
                            _candidate("arxiv:1"), _verified("arxiv:1")])

    decision = review_paper(_item(), llm, sleep=lambda s: None)

    assert decision["level"] == "headline"
    assert "不要为了修复格式而降低门槛" in llm.calls[1]["user"]


def test_verification_cannot_upgrade_a_headline_to_breaking(fake_llm_factory):
    llm = fake_llm_factory([_candidate("arxiv:1", "headline")]
                           + [_verified("arxiv:1", "breaking")] * 10)

    assert review_paper(_item(), llm, sleep=lambda s: None) is None


def test_breaker_trips_after_twenty_consecutive_total_failures(fake_llm_factory):
    breaker = Breaker(limit=2)
    llm = fake_llm_factory(["not json"] * 20)

    assert review_paper(_item("arxiv:1"), llm, breaker=breaker,
                        sleep=lambda s: None) is None
    assert review_paper(_item("arxiv:2"), llm, breaker=breaker,
                        sleep=lambda s: None) is None
    assert breaker.tripped()

    before = len(llm.calls)
    assert review_paper(_item("arxiv:3"), llm, breaker=breaker) is None
    assert len(llm.calls) == before          # tripped: no further calls at all


def test_one_success_resets_the_breaker(fake_llm_factory):
    breaker = Breaker(limit=2)
    llm = fake_llm_factory(["not json"] * 10 + [_candidate("arxiv:2", "reject")])

    review_paper(_item("arxiv:1"), llm, breaker=breaker, sleep=lambda s: None)
    review_paper(_item("arxiv:2"), llm, breaker=breaker, sleep=lambda s: None)

    assert not breaker.tripped()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_daily_review.py -q`
Expected: FAIL，`ImportError: cannot import name 'Breaker'`

- [ ] **Step 3: Write minimal implementation**

**3a.** `src/gdr/config.py`，在 `EDITORIAL_MAX_CONCURRENCY` 那一行下面追加：

```python
# One malformed JSON is noise; a dead upstream is a whole day of lost decisions
# (kimi-k3 400-ed for a full day in 2026-07). Retry hard, then let the
# cross-run repair pass pick up whatever still failed.
EDITORIAL_ATTEMPTS = int(os.environ.get("GDR_EDITORIAL_ATTEMPTS", "10"))
EDITORIAL_BACKOFF = (1, 2, 4, 8, 16, 30, 30, 30, 30)
# When this many papers in a row exhaust all attempts, upstream is down: stop
# calling for the rest of the run instead of dragging it out for an hour.
EDITORIAL_BREAKER_LIMIT = int(os.environ.get("GDR_EDITORIAL_BREAKER_LIMIT", "20"))
# Transport-level retries (network errors, 5xx, 429) inside the OpenAI SDK.
OPENAI_MAX_RETRIES = int(os.environ.get("GDR_OPENAI_MAX_RETRIES", "4"))
# A paper whose decision failed is retried on this many later runs before we
# give up on it for good.
REVIEW_MAX_ROUNDS = int(os.environ.get("GDR_REVIEW_MAX_ROUNDS", "3"))
```

**3b.** `src/gdr/llm.py`，`OpenCodeLLM.__init__` 里的构造改成：

```python
        self._client = OpenAI(api_key=api_key, base_url=base_url,
                              max_retries=config.OPENAI_MAX_RETRIES)
```

**3c.** `src/gdr/daily_review.py`：

顶部 import 增加 `import time`。

`_CANDIDATE_TMPL` 的首行由

```
今天是 {date}。只复核下面这一篇文献：
```

改为

```
本文预印本日 {preprint}，本站于 {ingested} 收录。只复核下面这一篇文献：
```

`_complete_json_object` 换成带重试次数与退避的版本：

```python
def _complete_json_object(llm: LLM, user: str, validate: Callable[[dict], dict],
                          *, sleep=time.sleep) -> dict:
    retry_note = """

上一次响应无法解析为完整 JSON 对象。请重新执行同一任务，只输出一个语法完整的 JSON 对象；
不要使用 Markdown 代码块或附加说明。继续严格把关，必要时减少候选，不要为了修复格式而降低门槛。
"""
    last_error: Exception | None = None
    for attempt in range(config.EDITORIAL_ATTEMPTS):
        if attempt:
            sleep(config.EDITORIAL_BACKOFF[
                min(attempt - 1, len(config.EDITORIAL_BACKOFF) - 1)])
        try:
            text = llm.complete(model=tier_model("synth"), system=_SYSTEM,
                                user=user if attempt == 0 else user + retry_note)
            data = extract_json(text)
            if not isinstance(data, dict):
                raise TypeError("editorial response must be a JSON object")
            return validate(data)
        except Exception as exc:
            last_error = exc
    raise TypeError("editorial decision returned invalid JSON "
                    f"{config.EDITORIAL_ATTEMPTS} times") from last_error
```

追加 `Breaker` 与 `review_paper`，并**删除** `make_daily_review` 与 `_parallel_map`：

```python
class Breaker:
    """Stop calling a dead upstream. One success anywhere resets it."""

    def __init__(self, limit: int | None = None):
        self.limit = limit or config.EDITORIAL_BREAKER_LIMIT
        self.consecutive_failures = 0

    def tripped(self) -> bool:
        return self.consecutive_failures >= self.limit

    def record(self, ok: bool) -> None:
        self.consecutive_failures = 0 if ok else self.consecutive_failures + 1


def review_paper(item: dict, llm: LLM, *, breaker: Breaker | None = None,
                 sleep=time.sleep) -> dict | None:
    """Decide one paper's news status, once and for all.

    Returns a decision dict, or None when the paper is not eligible for news
    review (edge layer, corrections, unbylined blurbs) or when every attempt
    failed. A None from failure is recoverable: the caller stores it as a missing
    decision and a later run retries it.
    """
    if item["score"].layer not in ("core", "related") or not _news_eligible(item):
        return None
    if breaker is not None and breaker.tripped():
        return None

    paper_id = item["paper"].id
    dates = item.get("dates") or {}
    try:
        candidate = _complete_json_object(
            llm,
            _CANDIDATE_TMPL.format(preprint=dates.get("preprint", "") or "未知",
                                   ingested=dates.get("ingested", "") or "未知",
                                   digest=_digest([item])),
            lambda data: _candidate_decision(data, paper_id), sleep=sleep)
        if candidate["decision"] == "reject":
            decision = {"paper_id": paper_id, "decision": "reject", "title": "",
                        "evidence": "", "impact": "",
                        "reason": candidate["reason"], "watchlist": []}
        else:
            decision = _complete_json_object(
                llm,
                _VERIFY_TMPL.format(
                    digest=_digest([item], include_machine_guide=False),
                    candidate=json.dumps(candidate, ensure_ascii=False)),
                lambda data: _verified_decision(data, paper_id,
                                                candidate["decision"]),
                sleep=sleep)
    except Exception:
        if breaker is not None:
            breaker.record(False)
        return None

    if breaker is not None:
        breaker.record(True)
    return {"level": decision["decision"], "title": decision["title"],
            "evidence": decision["evidence"], "impact": decision["impact"],
            "reason": decision["reason"], "watchlist": decision["watchlist"],
            "reviewed_at": dates.get("ingested", "")}
```

**3d.** `src/gdr/pipeline.py`：删除 `_review_for` 函数和 `from gdr.daily_review import make_daily_review` / `from gdr.models import DailyReview` 里已不需要的部分；`sync()` 里 `review = _review_for(...)` 那行暂时改为 `review = compose_review(date, merged)`（Task 7 会整体重写 `sync`，这里只求不破坏现有测试）。相应 import 改为 `from gdr.daily_review import compose_review`。

**3e.** `src/gdr/reclassify.py`：`from gdr.pipeline import _review_for` 改为 `from gdr.daily_review import compose_review`，`day.review = _review_for(date, day.items, llm)` 改为 `day.review = compose_review(date, day.items)`；`reclassify_day` 的 `llm` 参数仍用于 `score_paper`，签名不变。

**3f.** `tests/test_reclassify.py`：把断言从"重新生成了 review 文本"改为"分层被更新且 review 由存量决策重算"。若旧断言依赖 `_review_for` 的 LLM 调用次数，删掉该断言并替换为：

```python
    assert day.revisions[0]["review"]["overview"] == "旧概览"
    assert day.review.editorial_version == 2
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_daily_review.py -q`
Expected: PASS（11 passed）

Run: `.venv/bin/python -m pytest -q`
Expected: PASS（全绿；`test_pipeline.py` 中断言"整天重跑"的用例若失败，说明它测的是即将被 Task 7 删除的行为——**此时不要改测试**，先确认失败原因确实如此，再在 Task 7 中随 `sync` 重写一并更新）

- [ ] **Step 5: Commit**

```bash
git add src/gdr/config.py src/gdr/llm.py src/gdr/daily_review.py src/gdr/pipeline.py \
        src/gdr/reclassify.py tests/test_daily_review.py tests/test_reclassify.py
git -c gpg.ssh.program=ssh-keygen -c user.signingkey="$HOME/.ssh/id_ed25519_headless" \
  commit -m "feat(review): per-paper review_paper() with 10 retries, backoff and a breaker"
```

---

### Task 6: Store 支持 ingest 布局与 `key → 收录日` 索引

**Files:**
- Modify: `src/gdr/store.py`
- Test: `tests/test_store.py`（追加）

**Interfaces:**
- Consumes: `gdr.models.IngestDay`
- Produces（`Store` 新增方法，旧的 `save_day` / `load_day` / `list_days` 全部保留，Task 13 才删）：
  - `save_ingest(day: IngestDay) -> None`
  - `load_ingest(date: str) -> IngestDay`
  - `list_ingest_dates() -> list[str]`（升序）
  - `all_items() -> list[dict]`（按收录日升序拼接）
  - `seen_map() -> dict[str, str]`（identity key → 收录日）
  - `mark_seen(keys: list[str], date: str) -> None`
  - `locate(key: str) -> str | None`
  - `update_item(paper_id: str, mutate) -> bool` — 在论文所在的 ingest 文件里原地改一条 item，`mutate(item)` 就地修改，返回是否改到

- [ ] **Step 1: Write the failing test**

追加到 `tests/test_store.py`：

```python
import json

from gdr.models import IngestDay, Paper, RelevanceScore, make_item
from gdr.store import Store


def _ing_item(pid, ingested="2026-07-22", layer="core"):
    paper = Paper(id=pid, source="arxiv", title="t", authors=["A"], abstract="a",
                  categories=[], published="2026-07-20", url="")
    score = RelevanceScore(score=90, tags=[], layer=layer, reason="r")
    return make_item(paper, score, None,
                     dates={"preprint": "2026-07-20", "ingested": ingested})


def test_save_and_load_ingest_day(tmp_path):
    store = Store(tmp_path / "data")
    store.save_ingest(IngestDay(ingested="2026-07-22", items=[_ing_item("arxiv:1")]))

    back = store.load_ingest("2026-07-22")

    assert back.ingested == "2026-07-22"
    assert back.items[0]["paper"].id == "arxiv:1"
    assert (tmp_path / "data" / "ingest" / "2026-07-22.json").exists()


def test_list_ingest_dates_is_ascending_and_all_items_follows_it(tmp_path):
    store = Store(tmp_path / "data")
    store.save_ingest(IngestDay("2026-07-23", [_ing_item("arxiv:2", "2026-07-23")]))
    store.save_ingest(IngestDay("2026-07-22", [_ing_item("arxiv:1", "2026-07-22")]))

    assert store.list_ingest_dates() == ["2026-07-22", "2026-07-23"]
    assert [it["paper"].id for it in store.all_items()] == ["arxiv:1", "arxiv:2"]


def test_seen_map_records_which_ingest_day_holds_each_identity(tmp_path):
    store = Store(tmp_path / "data")
    store.mark_seen(["arxiv:1", "doi:10.1/x"], "2026-07-22")

    assert store.seen_map() == {"arxiv:1": "2026-07-22", "doi:10.1/x": "2026-07-22"}
    assert store.locate("doi:10.1/x") == "2026-07-22"
    assert store.locate("arxiv:missing") is None


def test_seen_index_reads_the_legacy_list_format(tmp_path):
    """Pre-migration the index was a flat list; those keys are seen but unlocatable."""
    root = tmp_path / "data"
    root.mkdir(parents=True)
    (root / "seen-index.json").write_text(json.dumps(["arxiv:old"]), encoding="utf-8")
    store = Store(root)

    assert store.seen_identities() == {"arxiv:old"}
    assert store.locate("arxiv:old") is None


def test_update_item_edits_in_place_in_the_owning_ingest_file(tmp_path):
    store = Store(tmp_path / "data")
    store.save_ingest(IngestDay("2026-07-22", [_ing_item("arxiv:1"),
                                               _ing_item("arxiv:2")]))
    store.mark_seen(["arxiv:1"], "2026-07-22")

    def mutate(item):
        item["dates"]["published"] = "2026-07-08"
        item["decision_final"] = True

    assert store.update_item("arxiv:1", mutate) is True
    assert store.update_item("arxiv:absent", mutate) is False

    items = {it["paper"].id: it for it in store.load_ingest("2026-07-22").items}
    assert items["arxiv:1"]["dates"]["published"] == "2026-07-08"
    assert items["arxiv:1"]["decision_final"] is True
    assert items["arxiv:2"]["dates"]["published"] == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_store.py -q`
Expected: FAIL，`AttributeError: 'Store' object has no attribute 'save_ingest'`

- [ ] **Step 3: Write minimal implementation**

`src/gdr/store.py`：顶部 import 增加 `from gdr.models import IngestDay`；`__init__` 里增加 `self.ingest_dir = self.root / "ingest"` 和 `self.ingest_dir.mkdir(parents=True, exist_ok=True)`；`_load_seen` 改为兼容两种格式，并追加以下方法：

```python
    # ---- ingest-keyed storage -------------------------------------------------

    def save_ingest(self, day: IngestDay) -> None:
        path = self.ingest_dir / f"{day.ingested}.json"
        path.write_text(json.dumps(day.to_dict(), ensure_ascii=False, indent=2),
                        encoding="utf-8")

    def load_ingest(self, date: str) -> IngestDay:
        path = self.ingest_dir / f"{date}.json"
        return IngestDay.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def list_ingest_dates(self) -> list[str]:
        return sorted(p.stem for p in self.ingest_dir.glob("*.json"))

    def all_items(self) -> list[dict]:
        items = []
        for date in self.list_ingest_dates():
            items.extend(self.load_ingest(date).items)
        return items

    def update_item(self, paper_id: str, mutate) -> bool:
        """Edit one stored item in place. The only path that rewrites a historical
        ingest file — used by enrichment and by the decision repair pass."""
        for date in reversed(self.list_ingest_dates()):
            day = self.load_ingest(date)
            for item in day.items:
                if item["paper"].id == paper_id:
                    mutate(item)
                    self.save_ingest(day)
                    return True
        return False

    # ---- seen index ----------------------------------------------------------

    def seen_map(self) -> dict[str, str]:
        raw = self._load_seen_raw()
        return {k: v for k, v in raw.items() if isinstance(v, str) and v}

    def mark_seen(self, keys: list[str], date: str) -> None:
        raw = self._load_seen_raw()
        for key in keys:
            raw[key] = date
        self._write_seen(raw)

    def locate(self, key: str) -> str | None:
        return self.seen_map().get(key) or None
```

`_load_seen` / 新增的私有方法：

```python
    def _load_seen_raw(self) -> dict:
        """The index migrated from a flat list of keys to {key: ingest date}. Legacy
        keys load with an empty value: seen, but not locatable."""
        if not self.seen_path.exists():
            return {}
        data = json.loads(self.seen_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
        return {str(k): "" for k in data}

    def _write_seen(self, raw: dict) -> None:
        self.seen_path.write_text(
            json.dumps(dict(sorted(raw.items())), ensure_ascii=False, indent=2),
            encoding="utf-8")

    def _load_seen(self) -> set[str]:
        return set(self._load_seen_raw())
```

`mark_seen_papers` 保持不变（内部改用 `_load_seen_raw` / `_write_seen`，值写空串）：

```python
    def mark_seen_papers(self, ids: list[str]) -> list[str]:
        raw = self._load_seen_raw()
        new = [i for i in ids if i not in raw]
        for i in ids:
            raw.setdefault(i, "")
        self._write_seen(raw)
        return new
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_store.py -q`
Expected: PASS

Run: `.venv/bin/python -m pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/gdr/store.py tests/test_store.py
git -c gpg.ssh.program=ssh-keygen -c user.signingkey="$HOME/.ssh/id_ed25519_headless" \
  commit -m "feat(store): ingest-keyed files, locatable seen index, in-place item update"
```

---

### Task 7: `sync()` 重写 —— 只为新论文付费、跨批次 enrich、跨跑批补评

**Files:**
- Modify: `src/gdr/pipeline.py`
- Rewrite: `tests/test_pipeline.py`
- Modify: `scripts/regenerate_reviews.py`（改为决策补评脚本）

**Interfaces:**
- Consumes: `gdr.store.Store` 的 ingest 方法、`gdr.daily_review.review_paper` / `Breaker`、`gdr.datesource.fetch_crossref_dates` / `fetch_arxiv_v1_date`、`gdr.models.make_item` / `IngestDay`
- Produces:
  - `sync(run_date, source, llm, store, fetch_fulltext=..., window_days=None, max_workers=None, fetch_dates=True) -> list[str]` — 返回本次真正写入的收录日列表（`[run_date]` 或 `[]`）
  - `enrich_seen(papers: list[Paper], store: Store, *, fetch_dates=True) -> int` — 返回被补充的论文数
  - `repair_decisions(store, run_date, llm, *, window_days=None) -> int` — 返回补评成功数
  - `paper_dates(paper, ingested, *, fetch_dates=True) -> dict`

- [ ] **Step 1: Write the failing test**

新建 `tests/test_pipeline.py`（**整体替换**）：

```python
import hashlib
import json
import re

from gdr.models import IngestDay, Paper, RelevanceScore, make_item
from gdr.pipeline import enrich_seen, repair_decisions, sync
from gdr.sources.base import Source
from gdr.store import Store


class StubSource(Source):
    def __init__(self, papers):
        self._papers = papers

    def fetch(self, date):
        return list(self._papers)

    def fetch_recent(self, end_date, days):
        return list(self._papers)


def _paper(pid, title="GRB", published="2026-07-16", source="arxiv", doi=None,
           external_ids=None):
    return Paper(id=pid, source=source, title=title, authors=["A"],
                 abstract="abstract " * 40, categories=["astro-ph.HE"],
                 published=published, url=f"https://arxiv.org/abs/{pid}", doi=doi,
                 external_ids=external_ids or {})


def _keyed_llm(fake_llm_factory, editorial="reject"):
    def editorial_response(user):
        paper_id = re.search(r"paper_id=([^ ]+)", user).group(1)
        if "第二位、更加怀疑" in user:
            return json.dumps({"paper_id": paper_id, "decision": "headline",
                               "title": "T", "evidence": "E", "impact": "I",
                               "reason": "R", "watchlist": ["w"]})
        return json.dumps({"paper_id": paper_id, "decision": editorial,
                           "reason": "理由。"})

    return fake_llm_factory({
        "主题标签与相关层级是两个独立判断": json.dumps({
            "layer": "core", "score": 90, "tags": ["GRB"], "relation": "direct",
            "core_path": "science", "evidence": "GRB 是主要研究对象", "reason": "核心"}),
        "综述卡片": json.dumps({"title_zh": "标题", "team": "A 等", "tldr": "t",
                              "review": "r", "highlight": "h", "relation": "—"}),
        "只复核下面这一篇文献": editorial_response,
        "第二位、更加怀疑": editorial_response,
    })


def _sync(store, papers, llm, run_date="2026-07-18"):
    return sync(run_date, StubSource(papers), llm, store,
                fetch_fulltext=lambda p, **k: "BODY", max_workers=2,
                fetch_dates=False)


def test_sync_writes_one_file_keyed_by_the_run_date(tmp_path, fake_llm_factory):
    store = Store(tmp_path / "data")

    affected = _sync(store, [_paper("arxiv:1", published="2026-07-14"),
                             _paper("arxiv:1", published="2026-07-14")], # dup
                     _keyed_llm(fake_llm_factory))

    assert affected == ["2026-07-18"]
    assert store.list_ingest_dates() == ["2026-07-18"]
    day = store.load_ingest("2026-07-18")
    assert len(day.items) == 1                              # deduped
    assert day.items[0]["dates"]["ingested"] == "2026-07-18"
    assert day.items[0]["dates"]["preprint"] == "2026-07-14"
    assert day.items[0]["archive_date"] == "2026-07-14"     # archive axis is the paper's own date
    assert day.items[0]["decision"]["level"] == "reject"


def test_backfill_only_pays_for_the_new_paper(tmp_path, fake_llm_factory):
    """The whole point: adding 1 paper to a big day must not re-review the day."""
    store = Store(tmp_path / "data")
    old = [_paper(f"arxiv:{i}", published="2026-07-14") for i in range(8)]
    _sync(store, old, _keyed_llm(fake_llm_factory), run_date="2026-07-18")
    before = {p: (tmp_path / "data" / "ingest" / f"{p}.json").read_bytes()
              for p in store.list_ingest_dates()}

    llm = _keyed_llm(fake_llm_factory)
    _sync(store, old + [_paper("arxiv:new", published="2026-07-14")], llm,
          run_date="2026-07-19")

    editorial = [c for c in llm.calls if "只复核下面这一篇文献" in c["user"]]
    assert len(editorial) == 1                    # only the new paper was reviewed
    assert store.list_ingest_dates() == ["2026-07-18", "2026-07-19"]
    for date, blob in before.items():
        assert (tmp_path / "data" / "ingest" / f"{date}.json").read_bytes() == blob


def test_enrich_merges_journal_dates_into_an_already_stored_paper(tmp_path):
    store = Store(tmp_path / "data")
    item = make_item(_paper("arxiv:1"), RelevanceScore(90, [], "core", "r"), None,
                     dates={"preprint": "2026-03-12", "ingested": "2026-07-18"})
    store.save_ingest(IngestDay("2026-07-18", [item]))
    store.mark_seen(["arxiv:1", "doi:10.1/x"], "2026-07-18")

    journal = _paper("ads:2026ApJ", source="ads", doi="10.1/x",
                     external_ids={"arxiv": "1", "doi": "10.1/x",
                                   "ads": "2026ApJ"})
    n = enrich_seen([journal], store, fetch_dates=False)

    stored = store.load_ingest("2026-07-18").items[0]
    assert n == 1
    assert stored["paper"].doi == "10.1/x"
    assert stored["paper"].external_ids["ads"] == "2026ApJ"
    assert stored["archive_date"] == "2026-03-12"        # archive day never moves
    assert stored["decision"] is None                    # never re-reviewed


def test_failed_decision_still_stores_the_paper_and_is_repaired_next_run(
        tmp_path, fake_llm_factory):
    store = Store(tmp_path / "data")
    broken = fake_llm_factory({
        "主题标签与相关层级是两个独立判断": json.dumps({
            "layer": "core", "score": 90, "tags": ["GRB"], "relation": "direct",
            "core_path": "science", "evidence": "e", "reason": "核心"}),
        "综述卡片": json.dumps({"title_zh": "标题", "team": "A", "tldr": "t",
                              "review": "r", "highlight": "h", "relation": "—"}),
        "只复核下面这一篇文献": "not json",
    })

    sync("2026-07-18", StubSource([_paper("arxiv:1")]), broken, store,
         fetch_fulltext=lambda p, **k: "BODY", max_workers=1, fetch_dates=False)

    stored = store.load_ingest("2026-07-18").items[0]
    assert stored["decision"] is None
    assert stored["review_attempts"] == 1
    assert stored["decision_final"] is False

    repaired = repair_decisions(store, "2026-07-19", _keyed_llm(fake_llm_factory))

    assert repaired == 1
    assert store.load_ingest("2026-07-18").items[0]["decision"]["level"] == "reject"


def test_repair_gives_up_after_the_configured_number_of_rounds(
        tmp_path, fake_llm_factory):
    store = Store(tmp_path / "data")
    item = make_item(_paper("arxiv:1"), RelevanceScore(90, [], "core", "r"), None,
                     dates={"ingested": "2026-07-18"})
    item["review_attempts"] = 2
    store.save_ingest(IngestDay("2026-07-18", [item]))
    broken = fake_llm_factory({"只复核下面这一篇文献": "not json"})

    assert repair_decisions(store, "2026-07-19", broken) == 0

    stored = store.load_ingest("2026-07-18").items[0]
    assert stored["review_attempts"] == 3
    assert stored["decision_final"] is True

    assert repair_decisions(store, "2026-07-20", broken) == 0   # never tried again


def test_sync_skips_already_seen_without_reprocessing(tmp_path, fake_llm_factory):
    store = Store(tmp_path / "data")
    store.mark_seen(["arxiv:1"], "2026-07-17")
    llm = _keyed_llm(fake_llm_factory)

    assert _sync(store, [_paper("arxiv:1")], llm) == []
    assert not any("综述卡片" in c["user"] for c in llm.calls)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_pipeline.py -q`
Expected: FAIL，`ImportError: cannot import name 'enrich_seen' from 'gdr.pipeline'`

- [ ] **Step 3: Write minimal implementation**

整体替换 `src/gdr/pipeline.py`：

```python
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from gdr import config
from gdr.citations import resolve_summary
from gdr.daily_review import Breaker, review_paper
from gdr.datesource import fetch_arxiv_v1_date, fetch_crossref_dates
from gdr.dedup import dedupe, paper_keys
from gdr.fulltext import fetch_fulltext as _real_fetch_fulltext
from gdr.models import IngestDay, make_item
from gdr.relevance import score_paper
from gdr.store import Store
from gdr.summarize import summarize_edge, summarize_paper


def paper_dates(paper, ingested: str, *, fetch_dates: bool = True) -> dict:
    """The four dates for one paper. arXiv records carry their v1 date already;
    journal dates come from Crossref, which is also the only source that gives a
    day-precise publication date and an acceptance date."""
    external = getattr(paper, "external_ids", None) or {}
    arxiv_id = str(external.get("arxiv") or "").strip()
    doi = str(getattr(paper, "doi", None) or external.get("doi") or "").strip()

    preprint = paper.published if paper.source == "arxiv" else ""
    journal = {}
    if fetch_dates:
        if not preprint and arxiv_id:
            preprint = fetch_arxiv_v1_date(arxiv_id)
        if doi:
            journal = fetch_crossref_dates(doi, mailto=config.CROSSREF_MAILTO)
    if not journal and paper.source == "ads":
        journal = {"published": paper.published, "published_precision": "day",
                   "published_source": "ads-pubdate"}
    return {
        "preprint": preprint,
        "accepted": journal.get("accepted", ""),
        "published": journal.get("published", ""),
        "published_precision": journal.get("published_precision", ""),
        "published_source": journal.get("published_source", ""),
        "received": journal.get("received", ""),
        "ingested": ingested,
    }


def _process_paper(paper, llm, fetch_fulltext, run_date, breaker,
                   fetch_dates=True) -> dict:
    score = score_paper(paper, llm)
    if score.layer in ("core", "related"):
        fulltext = fetch_fulltext(paper)
        summary = summarize_paper(paper, fulltext, llm)
        resolve_summary(summary, ads_token=config.get_ads_token(),
                        mailto=config.CROSSREF_MAILTO)
    else:
        summary = summarize_edge(paper, llm)
    item = make_item(paper, score, summary,
                     dates=paper_dates(paper, run_date, fetch_dates=fetch_dates))
    decision = review_paper(item, llm, breaker=breaker)
    item["decision"] = decision
    if decision is None and score.layer in ("core", "related"):
        item["review_attempts"] = 1
    return item


def enrich_seen(papers, store: Store, *, fetch_dates: bool = True) -> int:
    """Merge later-arriving identifiers and journal dates into papers we already
    hold. Without this a preprint ingested months ago would never learn that it
    was accepted and published. Never re-summarises, never re-reviews, and never
    moves a paper's archive day."""
    enriched = 0
    for paper in papers:
        target = next((store.locate(k) for k in sorted(paper_keys(paper))
                       if store.locate(k)), None)
        if not target:
            continue
        external = getattr(paper, "external_ids", None) or {}
        doi = str(getattr(paper, "doi", None) or external.get("doi") or "").strip()
        fresh = paper_dates(paper, "", fetch_dates=fetch_dates)

        def mutate(item, external=external, doi=doi, fresh=fresh):
            stored = item["paper"]
            stored.external_ids = {**external, **(stored.external_ids or {})}
            if not stored.doi and doi:
                stored.doi = doi
            for key in ("accepted", "published", "published_precision",
                        "published_source", "received"):
                if not item["dates"].get(key) and fresh.get(key):
                    item["dates"][key] = fresh[key]

        matched = False
        for date in reversed(store.list_ingest_dates()):
            day = store.load_ingest(date)
            for item in day.items:
                if paper_keys(item["paper"]) & paper_keys(paper):
                    mutate(item)
                    store.save_ingest(day)
                    matched = True
                    break
            if matched:
                break
        enriched += 1 if matched else 0
    return enriched


def repair_decisions(store: Store, run_date: str, llm,
                     window_days: int | None = None) -> int:
    """Retry decisions that failed on an earlier run. This is the safety net for a
    dead upstream: a whole day of missing decisions comes back the next morning."""
    window_days = window_days or config.FETCH_WINDOW_DAYS
    dates = store.list_ingest_dates()[-window_days:]
    breaker = Breaker()
    repaired = 0
    for date in dates:
        day = store.load_ingest(date)
        changed = False
        for item in day.items:
            if (item.get("decision") is not None or item.get("decision_final")
                    or item["score"].layer not in ("core", "related")):
                continue
            if item.get("review_attempts", 0) >= config.REVIEW_MAX_ROUNDS:
                item["decision_final"] = True
                changed = True
                continue
            decision = review_paper(item, llm, breaker=breaker)
            item["review_attempts"] = item.get("review_attempts", 0) + 1
            if decision is not None:
                item["decision"] = decision
                repaired += 1
            elif item["review_attempts"] >= config.REVIEW_MAX_ROUNDS:
                item["decision_final"] = True
            changed = True
        if changed:
            store.save_ingest(day)
    return repaired


def sync(run_date, source, llm, store: Store,
         fetch_fulltext=_real_fetch_fulltext, window_days=None, max_workers=None,
         fetch_dates=True) -> list[str]:
    window_days = window_days or config.FETCH_WINDOW_DAYS
    max_workers = max_workers or config.MAX_CONCURRENCY

    store.ensure_seen_identities()
    papers = dedupe(source.fetch_recent(run_date, window_days))
    seen = store.seen_identities()
    fresh = [p for p in papers if seen.isdisjoint(paper_keys(p))]
    enrich_seen([p for p in papers if not seen.isdisjoint(paper_keys(p))], store,
                fetch_dates=fetch_dates)

    items = []
    if fresh:
        breaker = Breaker()
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futs = {pool.submit(_process_paper, p, llm, fetch_fulltext, run_date,
                                breaker, fetch_dates): p for p in fresh}
            for fut in as_completed(futs):
                paper = futs[fut]
                try:
                    items.append(fut.result())
                except Exception as exc:  # per-paper resilience
                    print(f"[gdr] skipping {paper.id}: {exc}", file=sys.stderr)

    if not items:
        return []

    items.sort(key=lambda it: it["paper"].id)
    store.save_ingest(IngestDay(ingested=run_date, items=items))
    for item in items:
        store.mark_seen(sorted(paper_keys(item["paper"])), run_date)
    return [run_date]
```

`scripts/regenerate_reviews.py` 整体替换为决策补评脚本：

```python
"""Repair decisions that failed on an earlier run.

Use this after an upstream outage (the model 400-ing for a day, say). It retries
ONLY papers whose editorial decision is missing — it never refetches, rescores or
resummarises, and never touches a decision that already succeeded.

Usage:
    OPENCODE_API_KEY=... python scripts/repair_decisions.py
"""
import datetime as dt
from pathlib import Path

from gdr import config
from gdr.llm import OpenCodeLLM
from gdr.pipeline import repair_decisions
from gdr.store import Store

ROOT = Path(__file__).resolve().parent.parent


def main():
    llm = OpenCodeLLM(api_key=config.get_api_key())
    store = Store(ROOT / "data")
    run_date = dt.datetime.now(dt.timezone.utc).date().isoformat()
    print(f"repaired {repair_decisions(store, run_date, llm)} decisions")


if __name__ == "__main__":
    main()
```

`git mv scripts/regenerate_reviews.py scripts/repair_decisions.py` 后再写入上面的内容。

`scripts/run_daily.py`：在 `affected = sync(...)` 之前插入一行 `repair_decisions(store, date, llm)`，并 import 之。

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_pipeline.py -q`
Expected: PASS（7 passed）

Run: `.venv/bin/python -m pytest -q`
Expected: PASS（`test_site_build.py` / `test_render.py` 仍走旧的 `data/daily` 路径，应保持绿）

- [ ] **Step 5: Commit**

```bash
git add src/gdr/pipeline.py tests/test_pipeline.py scripts/repair_decisions.py \
        scripts/run_daily.py
git rm --cached scripts/regenerate_reviews.py 2>/dev/null || true
git -c gpg.ssh.program=ssh-keygen -c user.signingkey="$HOME/.ssh/id_ed25519_headless" \
  commit -m "feat(pipeline): ingest-keyed sync, cross-run enrich, decision repair pass"
```

---

### Task 8: 迁移脚本

**Files:**
- Create: `src/gdr/migrate.py`
- Create: `scripts/migrate_two_axis.py`
- Test: `tests/test_migrate.py`

**Interfaces:**
- Consumes: `gdr.models.DayData` / `IngestDay` / `make_item`、`gdr.datesource`
- Produces:
  - `ingest_dates_from_git(repo_root: Path) -> dict[str, str]` — paper id → 首次出现该 id 的 commit 日期
  - `decisions_from_review(day: DayData) -> dict[str, dict]` — paper id → decision（含被拒的）
  - `build_ingest_days(days: list[DayData], ingest_dates: dict, resolve_dates) -> list[IngestDay]`
  - `resolve_dates(paper, ingested) -> dict`（默认实现调用 `gdr.pipeline.paper_dates`；测试传假的）

- [ ] **Step 1: Write the failing test**

创建 `tests/test_migrate.py`：

```python
import json
import subprocess

from gdr.migrate import build_ingest_days, decisions_from_review, ingest_dates_from_git
from gdr.models import DailyReview, DayData, Paper, PaperSummary, RelevanceScore


def _git(repo, *args, date=None):
    env = {"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date} if date else {}
    subprocess.run(["git", *args], cwd=repo, check=True,
                   capture_output=True, env={**_base_env(), **env})


def _base_env():
    import os
    return {**os.environ, "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@e",
            "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@e",
            "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}


def _write_day(repo, date, ids):
    path = repo / "data" / "daily" / f"{date}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "date": date,
        "review": {"date": date, "overview": "o", "highlights": "", "trends": "",
                   "editorial_version": 2, "stories": [], "watchlist": []},
        "items": [{"paper": {"id": pid, "source": "arxiv", "title": "t",
                             "authors": [], "abstract": "a", "categories": [],
                             "published": "2026-07-14", "url": "",
                             "pdf_url": None, "doi": None, "external_ids": {}},
                   "score": {"score": 90, "tags": [], "layer": "core",
                             "reason": "r", "relation": "", "core_path": "",
                             "evidence": ""},
                   "summary": None} for pid in ids],
        "revisions": [],
    }, ensure_ascii=False), encoding="utf-8")


def test_ingest_dates_come_from_the_commit_that_first_introduced_each_paper(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _write_day(repo, "2026-07-14", ["arxiv:1", "arxiv:2"])
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "first", date="2026-07-18T10:00:00 +0000")
    _write_day(repo, "2026-07-14", ["arxiv:1", "arxiv:2", "arxiv:3"])
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "backfill", date="2026-07-21T10:00:00 +0000")

    got = ingest_dates_from_git(repo)

    assert got == {"arxiv:1": "2026-07-18", "arxiv:2": "2026-07-18",
                   "arxiv:3": "2026-07-21"}


def _day_with_story():
    paper = Paper(id="arxiv:1", source="arxiv", title="t", authors=["A"],
                  abstract="a", categories=[], published="2026-07-14", url="")
    other = Paper(id="arxiv:2", source="arxiv", title="t2", authors=["A"],
                  abstract="a", categories=[], published="2026-07-14", url="")
    score = RelevanceScore(score=90, tags=[], layer="core", reason="r")
    edge = RelevanceScore(score=10, tags=[], layer="edge", reason="r")
    summary = PaperSummary(paper_id="arxiv:1", title_zh="标题", team="", tldr="t",
                           review="", highlight="h", relation="")
    review = DailyReview(
        date="2026-07-14", overview="o", highlights="", trends="",
        editorial_version=2,
        stories=[{"paper_id": "arxiv:1", "level": "breaking", "title": "T",
                  "evidence": "E", "impact": "I", "reason": "R"}],
        watchlist=["信号一（arxiv:1）", "无标识的信号"])
    return DayData(date="2026-07-14", review=review, items=[
        {"paper": paper, "score": score, "summary": summary},
        {"paper": other, "score": edge, "summary": None}])


def test_decisions_are_recovered_from_stories_and_the_rest_marked_rejected():
    day = _day_with_story()
    day.items.append({"paper": Paper(id="arxiv:3", source="arxiv", title="t3",
                                     authors=["A"], abstract="a", categories=[],
                                     published="2026-07-14", url=""),
                      "score": RelevanceScore(80, [], "related", "r"),
                      "summary": None})

    got = decisions_from_review(day)

    assert got["arxiv:1"]["level"] == "breaking"
    assert got["arxiv:1"]["impact"] == "I"
    assert got["arxiv:3"]["level"] == "reject"
    assert got["arxiv:3"]["reason"] == "迁移：v2 复核未入选"
    assert "arxiv:2" not in got                     # edge papers are never reviewed


def test_watchlist_without_an_id_goes_to_the_only_story_of_that_day():
    got = decisions_from_review(_day_with_story())

    assert got["arxiv:1"]["watchlist"] == ["信号一（arxiv:1）", "无标识的信号（arxiv:1）"]


def test_build_ingest_days_groups_by_ingest_date_and_computes_archive_date():
    day = _day_with_story()
    ingest = {"arxiv:1": "2026-07-18", "arxiv:2": "2026-07-21"}

    out = {d.ingested: d for d in build_ingest_days(
        [day], ingest,
        resolve_dates=lambda paper, ingested: {
            "preprint": "2026-07-14", "accepted": "", "published": "",
            "published_precision": "", "published_source": "", "received": "",
            "ingested": ingested})}

    assert sorted(out) == ["2026-07-18", "2026-07-21"]
    assert [it["paper"].id for it in out["2026-07-18"].items] == ["arxiv:1"]
    assert out["2026-07-18"].items[0]["archive_date"] == "2026-07-14"
    assert out["2026-07-18"].items[0]["decision"]["level"] == "breaking"
    assert out["2026-07-21"].items[0]["decision"] is None       # edge
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_migrate.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'gdr.migrate'`

- [ ] **Step 3: Write minimal implementation**

创建 `src/gdr/migrate.py`：

```python
"""One-shot migration from date-keyed day files to ingest-keyed files.

The ingest date of every already-stored paper is recovered exactly from git: a
paper's ingest day is the date of the commit that first introduced its id. That
beats reconstructing from append order plus `revisions[].n_papers`, because
`reclassify_day()` also appends a revision without adding papers.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from gdr.models import DayData, IngestDay, make_item

_WATCH_ID_RE = re.compile(r"[（(\[]\s*(?:arxiv|ads):[^）)\]]+\s*[）)\]]",
                          re.IGNORECASE)


def _run(repo_root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo_root, check=True,
                          capture_output=True, text=True).stdout


def ingest_dates_from_git(repo_root: Path) -> dict[str, str]:
    """paper id -> the date of the commit that first stored it."""
    repo_root = Path(repo_root)
    log = _run(repo_root, "log", "--reverse", "--format=%H %ad", "--date=short",
               "--", "data/daily")
    first_seen: dict[str, str] = {}
    for line in log.splitlines():
        if not line.strip():
            continue
        sha, date = line.split(None, 1)
        names = _run(repo_root, "ls-tree", "--name-only", f"{sha}:data/daily")
        for name in names.split():
            if not name.endswith(".json"):
                continue
            blob = _run(repo_root, "show", f"{sha}:data/daily/{name}")
            try:
                payload = json.loads(blob)
            except ValueError:
                continue
            for item in payload.get("items", []):
                pid = item.get("paper", {}).get("id", "")
                if pid and pid not in first_seen:
                    first_seen[pid] = date.strip()
    return first_seen


def decisions_from_review(day: DayData) -> dict[str, dict]:
    """Recover per-paper decisions from a stored day's `stories`.

    Papers that made the cut keep their full editorial text. Every other
    core/related paper was reviewed and rejected at the time — recorded as such
    rather than re-run, because that judgement is a historical fact and rerunning
    it would cost hundreds of calls.
    """
    stories = {s["paper_id"]: s for s in (day.review.stories or [])}
    watchlists: dict[str, list[str]] = {pid: [] for pid in stories}
    for signal in (day.review.watchlist or []):
        match = _WATCH_ID_RE.search(signal)
        owner = ""
        if match:
            owner = match.group(0).strip("（）()[] ")
        if owner not in watchlists:
            owner = next(iter(watchlists)) if len(watchlists) == 1 else ""
        if not owner:
            continue
        text = _WATCH_ID_RE.sub("", signal).strip(" 　·:：、，,；;")
        watchlists[owner].append(f"{text}（{owner}）")

    decisions: dict[str, dict] = {}
    for item in day.items:
        pid = item["paper"].id
        if item["score"].layer not in ("core", "related"):
            continue
        story = stories.get(pid)
        if story:
            decisions[pid] = {
                "level": story["level"], "title": story["title"],
                "evidence": story["evidence"], "impact": story["impact"],
                "reason": story["reason"],
                "watchlist": watchlists.get(pid, []),
                "reviewed_at": day.date,
            }
        else:
            decisions[pid] = {
                "level": "reject", "title": "", "evidence": "", "impact": "",
                "reason": "迁移：v2 复核未入选", "watchlist": [],
                "reviewed_at": day.date,
            }
    return decisions


def build_ingest_days(days: list[DayData], ingest_dates: dict[str, str],
                      resolve_dates) -> list[IngestDay]:
    """Regroup every stored paper under its ingest date, carrying its recovered
    decision and its freshly resolved four dates."""
    buckets: dict[str, list[dict]] = {}
    for day in days:
        decisions = decisions_from_review(day)
        for item in day.items:
            paper = item["paper"]
            ingested = ingest_dates.get(paper.id, day.date)
            buckets.setdefault(ingested, []).append(
                make_item(paper, item["score"], item["summary"],
                          dates=resolve_dates(paper, ingested),
                          decision=decisions.get(paper.id)))
    return [IngestDay(ingested=date, items=sorted(items,
                                                  key=lambda it: it["paper"].id))
            for date, items in sorted(buckets.items())]
```

创建 `scripts/migrate_two_axis.py`：

```python
"""Migrate data/daily/<archive date>.json to data/ingest/<ingest date>.json.

Runs once. Needs the network (arXiv + Crossref) to resolve the three academic
dates, and the repository's git history to recover ingest dates exactly.

Usage:
    python scripts/migrate_two_axis.py --dry-run
    ADS_API_TOKEN=... python scripts/migrate_two_axis.py
"""
import argparse
from pathlib import Path

from gdr.migrate import build_ingest_days, ingest_dates_from_git
from gdr.pipeline import paper_dates
from gdr.store import Store

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    store = Store(ROOT / "data")
    days = [store.load_day(d) for d in sorted(store.list_days())]
    total = sum(len(day.items) for day in days)
    ingest_dates = ingest_dates_from_git(ROOT)
    missing = [it["paper"].id for day in days for it in day.items
               if it["paper"].id not in ingest_dates]
    print(f"{len(days)} days, {total} papers, "
          f"{len(ingest_dates)} ingest dates from git, {len(missing)} unresolved")

    out = build_ingest_days(days, ingest_dates, resolve_dates=paper_dates)
    moved = sum(len(day.items) for day in out)
    print(f"→ {len(out)} ingest days, {moved} papers")
    assert moved == total, f"lost papers: {total} -> {moved}"

    if args.dry_run:
        for day in out:
            print(f"  {day.ingested}: {len(day.items)}")
        return
    for day in out:
        store.save_ingest(day)
    for day in out:
        for item in day.items:
            store.mark_seen([item["paper"].id], day.ingested)
    print("written to data/ingest/")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_migrate.py -q`
Expected: PASS（4 passed）

Run: `.venv/bin/python -m pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/gdr/migrate.py scripts/migrate_two_axis.py tests/test_migrate.py
git -c gpg.ssh.program=ssh-keygen -c user.signingkey="$HOME/.ssh/id_ed25519_headless" \
  commit -m "feat(migrate): rebuild ingest dates from git history and recover decisions"
```

---

### Task 9: 执行迁移（数据提交）

**Files:**
- Create: `data/ingest/*.json`（脚本产出）
- Modify: `data/seen-index.json`
- Create: `tests/test_migrated_data.py`
- 注意：**本任务不删除 `data/daily/`**，渲染层还在用它，Task 13 才删。

**Interfaces:**
- Consumes: Task 8 的脚本
- Produces: 迁移后的真实数据

- [ ] **Step 1: 先跑 dry-run 看清楚会发生什么**

```bash
export ALL_PROXY=socks5://127.0.0.1:8235
.venv/bin/python scripts/migrate_two_axis.py --dry-run
```

Expected: 打印 `17 days, 1277 papers, ... ingest dates from git, 0 unresolved`（篇数以当时仓库为准），随后逐日列出收录日与篇数，且总数与迁移前一致。若 `unresolved` 不为 0，说明有论文在 git 历史里找不到——**停下来查明原因**，不要继续。

- [ ] **Step 2: Write the acceptance test（先写，现在会失败）**

创建 `tests/test_migrated_data.py`：

```python
"""Acceptance checks on the real migrated data. These run against data/ in the
repository, not a fixture — they are the migration's proof, not unit tests."""
import json
from pathlib import Path

import pytest

from gdr.store import Store

ROOT = Path(__file__).resolve().parent.parent
DAILY = ROOT / "data" / "daily"
INGEST = ROOT / "data" / "ingest"

pytestmark = pytest.mark.skipif(not INGEST.exists(),
                                reason="migration has not run yet")


def _legacy_days():
    return [json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(DAILY.glob("*.json"))]


def test_every_paper_survived_the_migration():
    if not DAILY.exists():
        pytest.skip("legacy data already removed")
    before = {it["paper"]["id"] for day in _legacy_days() for it in day["items"]}
    after = {it["paper"].id for it in Store(ROOT / "data").all_items()}

    assert after == before


def test_every_item_has_an_ingest_date_and_an_archive_date():
    for item in Store(ROOT / "data").all_items():
        assert item["dates"]["ingested"], item["paper"].id
        assert item["archive_date"], item["paper"].id


def test_story_counts_match_the_pre_migration_review_of_each_day():
    if not DAILY.exists():
        pytest.skip("legacy data already removed")
    from gdr.daily_review import compose_review

    expected = {day["date"]: len(day["review"].get("stories", []))
                for day in _legacy_days()}
    items = Store(ROOT / "data").all_items()
    by_archive = {}
    for item in items:
        by_archive.setdefault(item["archive_date"], []).append(item)

    for date, n in expected.items():
        got = len(compose_review(date, by_archive.get(date, [])).stories)
        assert got == n, f"{date}: {got} != {n}"


def test_ingest_days_are_not_in_the_future_of_their_papers():
    for item in Store(ROOT / "data").all_items():
        assert item["dates"]["ingested"] >= item["archive_date"], item["paper"].id
```

Run: `.venv/bin/python -m pytest tests/test_migrated_data.py -q`
Expected: `4 skipped`（`data/ingest` 还不存在）

- [ ] **Step 3: 真正执行迁移**

```bash
export ALL_PROXY=socks5://127.0.0.1:8235
ADS_API_TOKEN=$(gh secret list >/dev/null 2>&1; echo "$ADS_API_TOKEN") \
  .venv/bin/python scripts/migrate_two_axis.py 2>&1 | tee /tmp/migrate.log
```

（`ADS_API_TOKEN` 从环境里取，**不要写进任何文件**。没有它也能跑，只是少数无 arXiv id 的 ADS 论文拿不到 pubdate。）

Expected: 结尾打印 `written to data/ingest/`，`data/ingest/` 下出现若干文件。

- [ ] **Step 4: 跑验收测试**

Run: `.venv/bin/python -m pytest tests/test_migrated_data.py -q`
Expected: PASS（4 passed）

Run: `.venv/bin/python -m pytest -q`
Expected: PASS

再人工抽查 5 篇，确认日期链合理（预印本 ≤ 接收 ≤ 刊出，归档日 = 三者最早）：

```bash
.venv/bin/python - <<'PY'
import random
from pathlib import Path
from gdr.store import Store
items = Store(Path("data")).all_items()
for it in random.sample(items, 5):
    print(it["paper"].id, it["dates"], it["archive_date"])
PY
```

- [ ] **Step 5: Commit**

```bash
git add data/ingest data/seen-index.json tests/test_migrated_data.py
git -c gpg.ssh.program=ssh-keygen -c user.signingkey="$HOME/.ssh/id_ed25519_headless" \
  commit -m "data: migrate every stored paper onto the ingest-keyed two-axis layout"
```

---

### Task 10: 渲染两条时间轴

**Files:**
- Modify: `src/gdr/render.py`
- Modify: `templates/day.html`（把 `day.review` / `day.revisions` 换成显式的 `review` / 版本上下文）
- Modify: `templates/base.html`（masthead kicker 区分两轴）
- Modify: `tests/conftest.py`（共享的 item / 站点构造 fixture，Task 11、12 也用）
- Test: `tests/test_render.py`（改写用例的数据构造方式）

**Interfaces:**
- Consumes: `Store.all_items()`、`gdr.daily_review.compose_review`
- Produces:
  - `group_by(items, key) -> dict[str, list[dict]]`
  - `page_context(axis, date, items, *, latest_date, versions=(), current_version="", batches=()) -> dict`
  - `render_site(store, out_dir, templates_dir, static_dir)` 产出 `site/news/<收录日>.html`、`site/day/<归档日>.html`、`site/index.html`（= 最新收录日）、`site/archive.html`
  - 模板变量：`axis`（`"news"` 或 `"archive"`）、`review`、`items`、`core_items`、`related_items`、`edge_items`、`main_items`、`meta`、`prev_date`、`next_date`

- [ ] **Step 1: Write the failing test**

先把三个构造器放进 `tests/conftest.py`（Task 11、12 会复用它们；`tests/` 不是 package，跨测试文件 import 会失败，所以必须走 fixture）：

```python
from pathlib import Path

from gdr.models import IngestDay, Paper, PaperSummary, RelevanceScore, make_item
from gdr.render import render_site
from gdr.store import Store


def _make_ritem(pid, *, archive, ingested, layer="core", score=90, decision=None):
    paper = Paper(id=pid, source="arxiv", title=f"Title {pid}", authors=["A. B."],
                  abstract="abstract", categories=["astro-ph.HE"],
                  published=archive, url=f"https://arxiv.org/abs/{pid}")
    rs = RelevanceScore(score=score, tags=["GRB"], layer=layer, reason="r")
    summary = PaperSummary(paper_id=pid, title_zh=f"中文 {pid}", team="", tldr="t",
                           review="", highlight="亮点", relation="")
    return make_item(paper, rs, summary,
                     dates={"preprint": archive, "ingested": ingested},
                     decision=decision)


def _make_story_decision(pid, level="headline"):
    return {"level": level, "title": f"头条 {pid}", "evidence": "证据",
            "impact": "影响", "reason": "依据", "watchlist": [f"信号（{pid}）"],
            "reviewed_at": "2026-07-22"}


@pytest.fixture
def ritem():
    return _make_ritem


@pytest.fixture
def story_decision():
    return _make_story_decision


@pytest.fixture
def build_site_from(tmp_path):
    """(ingest date, items) pairs -> a rendered site directory."""
    def build(ingest_days):
        store = Store(tmp_path / "data")
        for date, items in ingest_days:
            store.save_ingest(IngestDay(ingested=date, items=items))
        out = tmp_path / "site"
        render_site(store, out, Path("templates"), Path("static"))
        return out
    return build
```

然后在 `tests/test_render.py` 追加（用 fixture，不要在文件里再定义构造器）：

```python
from gdr.render import group_by


def test_group_by_archive_and_ingest_are_independent_groupings(ritem):
    items = [ritem("arxiv:1", archive="2026-07-14", ingested="2026-07-18"),
             ritem("arxiv:2", archive="2026-07-14", ingested="2026-07-22")]

    assert sorted(group_by(items, "archive")) == ["2026-07-14"]
    assert sorted(group_by(items, "ingest")) == ["2026-07-18", "2026-07-22"]


def test_site_has_one_news_page_per_ingest_day_and_one_day_page_per_archive_day(
        ritem, build_site_from):
    out = build_site_from([
        ("2026-07-18", [ritem("arxiv:1", archive="2026-07-14",
                              ingested="2026-07-18")]),
        ("2026-07-22", [ritem("arxiv:2", archive="2026-07-14",
                              ingested="2026-07-22"),
                        ritem("arxiv:3", archive="2026-07-20",
                              ingested="2026-07-22")])])

    assert (out / "news" / "2026-07-18.html").exists()
    assert (out / "news" / "2026-07-22.html").exists()
    assert (out / "day" / "2026-07-14.html").exists()
    assert (out / "day" / "2026-07-20.html").exists()


def test_home_page_is_the_latest_ingest_day(ritem, build_site_from):
    out = build_site_from([
        ("2026-07-18", [ritem("arxiv:1", archive="2026-07-14",
                              ingested="2026-07-18")]),
        ("2026-07-22", [ritem("arxiv:2", archive="2026-07-20",
                              ingested="2026-07-22")])])

    home = (out / "index.html").read_text(encoding="utf-8")

    assert "Title arxiv:2" in home
    assert "Title arxiv:1" not in home
    assert "本日收录" in home


def test_archive_page_shows_every_paper_of_that_archive_day_whenever_ingested(
        ritem, build_site_from):
    out = build_site_from([
        ("2026-07-18", [ritem("arxiv:1", archive="2026-07-14",
                              ingested="2026-07-18")]),
        ("2026-07-22", [ritem("arxiv:2", archive="2026-07-14",
                              ingested="2026-07-22")])])

    page = (out / "day" / "2026-07-14.html").read_text(encoding="utf-8")

    assert "Title arxiv:1" in page and "Title arxiv:2" in page
    assert "最早日期为此日" in page


def test_stories_render_on_both_axes_from_the_same_decision(
        ritem, story_decision, build_site_from):
    item = ritem("arxiv:1", archive="2026-07-14", ingested="2026-07-18",
                 decision=story_decision("arxiv:1"))
    out = build_site_from([("2026-07-18", [item])])

    news = (out / "news" / "2026-07-18.html").read_text(encoding="utf-8")
    archive = (out / "day" / "2026-07-14.html").read_text(encoding="utf-8")

    for page in (news, archive):
        assert "头条 arxiv:1" in page
        assert "影响" in page
```

同时把 `tests/test_render.py` 里现有依赖 `DayData` / `store.save_day` 的用例改为用 `_ritem` + `store.save_ingest` 构造（断言内容不变：密度分级、空态、watchlist 链接等）。

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_render.py -q`
Expected: FAIL，`ImportError: cannot import name 'group_by'`

- [ ] **Step 3: Write minimal implementation**

`src/gdr/render.py`：

```python
def group_by(items: list[dict], key: str) -> dict[str, list[dict]]:
    """Group stored items onto one of the two axes. `key` is "archive" (the
    paper's own earliest academic date) or "ingest" (the day this site saw it)."""
    field = (lambda it: it["archive_date"]) if key == "archive" else \
            (lambda it: it["dates"]["ingested"])
    groups: dict[str, list[dict]] = {}
    for item in items:
        value = field(item)
        if value:
            groups.setdefault(value, []).append(item)
    return groups


def _sorted_items(items: list[dict]) -> list[dict]:
    return sorted(items, key=lambda it: (_LAYER_ORDER.get(it["score"].layer, 9),
                                         -it["score"].score))


def page_context(axis: str, date: str, items: list[dict], *, latest_date: str,
                 prev_date: str = "", next_date: str = "") -> dict:
    from gdr.daily_review import compose_review

    ordered = _sorted_items(items)
    core = [it for it in ordered if it["score"].layer == "core"]
    related = [it for it in ordered if it["score"].layer == "related"]
    edge = [it for it in ordered if it["score"].layer == "edge"]
    return dict(axis=axis, date=date, review=compose_review(date, ordered),
                items=ordered, main_items=core + related, core_items=core,
                related_items=related, edge_items=edge,
                meta=_masthead(date, len(core), len(related), len(edge)),
                latest_date=latest_date, prev_date=prev_date, next_date=next_date)
```

`render_site` 主体改为：

```python
    items = store.all_items()
    by_ingest = group_by(items, "ingest")
    by_archive = group_by(items, "archive")
    ingest_dates = sorted(by_ingest)
    archive_dates = sorted(by_archive)
    latest_date = ingest_dates[-1] if ingest_dates else ""

    (out_dir / "news").mkdir(parents=True, exist_ok=True)
    (out_dir / "day").mkdir(parents=True, exist_ok=True)
    day_tmpl = env.get_template("day.html")
    index_tmpl = env.get_template("index.html")
    archive_tmpl = env.get_template("archive.html")

    for i, date in enumerate(ingest_dates):
        ctx = page_context("news", date, by_ingest[date], latest_date=latest_date,
                           prev_date=ingest_dates[i - 1] if i else "",
                           next_date=ingest_dates[i + 1]
                           if i + 1 < len(ingest_dates) else "")
        (out_dir / "news" / f"{date}.html").write_text(
            day_tmpl.render(static_prefix="../", **ctx), encoding="utf-8")
        if date == latest_date:
            (out_dir / "index.html").write_text(
                index_tmpl.render(static_prefix="", **ctx), encoding="utf-8")

    for date in archive_dates:
        ctx = page_context("archive", date, by_archive[date],
                           latest_date=latest_date)
        (out_dir / "day" / f"{date}.html").write_text(
            day_tmpl.render(static_prefix="../", **ctx), encoding="utf-8")

    (out_dir / "archive.html").write_text(
        archive_tmpl.render(days=sorted(archive_dates, reverse=True),
                            static_prefix="", latest_date=latest_date),
        encoding="utf-8")
```

`templates/day.html`：把所有 `day.review` 替换为 `review`；删除底部 `{% if day.revisions %}` 那整段 `<section class="revisions">`（Task 11 用版本条取代）；TOC 抽屉里 `{% if day.revisions %}` 那行一并删除。

`templates/base.html`：masthead 一行加轴标识：

```jinja
      {% if meta %}<span class="sh-vol">Vol. {{ meta.vol }} · No. {{ '%03d' % meta.no }}</span>{% endif %}
      {% if axis %}<span class="sh-axis">{{ '本日收录' if axis == 'news' else '最早日期为此日' }}</span>{% endif %}
```

`static/style.css` 追加：

```css
.sh-axis { font-size: .72rem; letter-spacing: .08em; color: var(--ink-3); }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_render.py -q`
Expected: PASS

Run: `.venv/bin/python -m pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/gdr/render.py templates/day.html templates/base.html static/style.css \
        tests/test_render.py
git -c gpg.ssh.program=ssh-keygen -c user.signingkey="$HOME/.ssh/id_ed25519_headless" \
  commit -m "feat(render): news pages by ingest date, archive pages by archive date"
```

---

### Task 11: 历史版本页与版本条

**Files:**
- Modify: `src/gdr/render.py`
- Modify: `templates/day.html`（版本条）
- Modify: `static/style.css`
- Test: `tests/test_render_versions.py`

**Interfaces:**
- Consumes: Task 10 的 `page_context` / `group_by`
- Produces:
  - `versions_for(items: list[dict]) -> list[str]` — 该归档日的所有收录日，升序；只有一个时返回空列表（无版本可切）
  - `page_context(...)` 增加 `versions: list[dict]`（每项 `{"date", "n", "href", "current"}`）与 `current_version: str`
  - 输出 `site/day/<归档日>.as-of-<收录日>.html`

- [ ] **Step 1: Write the failing test**

创建 `tests/test_render_versions.py`：

```python
from gdr.render import versions_for


def test_versions_for_lists_each_ingest_day_that_touched_this_archive_day(ritem):
    items = [ritem("arxiv:1", archive="2026-07-14", ingested="2026-07-18"),
             ritem("arxiv:2", archive="2026-07-14", ingested="2026-07-22"),
             ritem("arxiv:3", archive="2026-07-14", ingested="2026-07-22")]

    assert versions_for(items) == ["2026-07-18", "2026-07-22"]


def test_a_day_ingested_all_at_once_has_no_versions_to_switch_between(ritem):
    items = [ritem("arxiv:1", archive="2026-07-14", ingested="2026-07-18")]

    assert versions_for(items) == []


def test_historical_version_page_shows_only_what_was_known_then(
        ritem, build_site_from):
    out = build_site_from([
        ("2026-07-18", [ritem("arxiv:1", archive="2026-07-14",
                              ingested="2026-07-18")]),
        ("2026-07-22", [ritem("arxiv:2", archive="2026-07-14",
                              ingested="2026-07-22")])])

    latest = (out / "day" / "2026-07-14.html").read_text(encoding="utf-8")
    older = (out / "day" / "2026-07-14.as-of-2026-07-18.html").read_text(
        encoding="utf-8")

    assert "Title arxiv:1" in latest and "Title arxiv:2" in latest
    assert "Title arxiv:1" in older and "Title arxiv:2" not in older


def test_historical_version_carries_the_headline_as_it_stood_then(
        ritem, story_decision, build_site_from):
    out = build_site_from([
        ("2026-07-18", [ritem("arxiv:1", archive="2026-07-14",
                              ingested="2026-07-18")]),
        ("2026-07-22", [ritem("arxiv:2", archive="2026-07-14",
                              ingested="2026-07-22",
                              decision=story_decision("arxiv:2"))])])

    older = (out / "day" / "2026-07-14.as-of-2026-07-18.html").read_text(
        encoding="utf-8")
    latest = (out / "day" / "2026-07-14.html").read_text(encoding="utf-8")

    assert "头条 arxiv:2" in latest
    assert "头条 arxiv:2" not in older
    assert "今日无通过复核的重大进展" in older


def test_version_bar_links_every_version_and_marks_the_current_one(
        ritem, build_site_from):
    out = build_site_from([
        ("2026-07-18", [ritem("arxiv:1", archive="2026-07-14",
                              ingested="2026-07-18")]),
        ("2026-07-22", [ritem("arxiv:2", archive="2026-07-14",
                              ingested="2026-07-22")])])

    latest = (out / "day" / "2026-07-14.html").read_text(encoding="utf-8")

    assert 'class="version-bar"' in latest
    assert "2026-07-14.as-of-2026-07-18.html" in latest
    assert "最新" in latest


def test_news_pages_have_no_version_bar(ritem, build_site_from):
    """An ingest day is immutable by construction — nothing to version."""
    out = build_site_from([("2026-07-18", [ritem("arxiv:1",
                                                 archive="2026-07-14",
                                                 ingested="2026-07-18")])])

    assert 'class="version-bar"' not in (
        out / "news" / "2026-07-18.html").read_text(encoding="utf-8")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_render_versions.py -q`
Expected: FAIL，`ImportError: cannot import name 'versions_for'`

- [ ] **Step 3: Write minimal implementation**

`src/gdr/render.py` 追加：

```python
def versions_for(items: list[dict]) -> list[str]:
    """Ingest days that contributed to one archive day. A day that arrived in one
    piece has no versions — there is nothing to switch between."""
    dates = sorted({it["dates"]["ingested"] for it in items
                    if it["dates"].get("ingested")})
    return dates if len(dates) > 1 else []


def _version_href(date: str, version: str, latest: str) -> str:
    return f"{date}.html" if version == latest else f"{date}.as-of-{version}.html"
```

`page_context` 增加参数与返回键：

```python
def page_context(axis, date, items, *, latest_date, prev_date="", next_date="",
                 versions=(), current_version="") -> dict:
    ...
    ctx["versions"] = list(versions)
    ctx["current_version"] = current_version
    return ctx
```

`render_site` 的归档循环改为：

```python
    for date in archive_dates:
        all_day_items = by_archive[date]
        versions = versions_for(all_day_items)
        latest_version = versions[-1] if versions else ""
        bar = [{"date": v, "href": _version_href(date, v, latest_version),
                "n": sum(1 for it in all_day_items
                         if it["dates"]["ingested"] <= v),
                "current": False} for v in versions]
        for version in [""] + versions:
            shown = (all_day_items if not version else
                     [it for it in all_day_items
                      if it["dates"]["ingested"] <= version])
            if version and version == latest_version:
                continue                       # the latest version IS the bare URL
            marked = [{**b, "current": b["date"] == version} for b in bar]
            ctx = page_context("archive", date, shown, latest_date=latest_date,
                               versions=marked, current_version=version)
            name = f"{date}.html" if not version else f"{date}.as-of-{version}.html"
            (out_dir / "day" / name).write_text(
                day_tmpl.render(static_prefix="../", **ctx), encoding="utf-8")
```

`templates/day.html`，在 `<main class="reading">` 内、第一个 `section` 之前插入：

```jinja
  {% if versions %}
  <nav class="version-bar" aria-label="版本">
    <span class="version-label">版本</span>
    <a class="version {{ 'is-current' if not current_version else '' }}"
       href="{{ static_prefix }}day/{{ date }}.html">最新 · {{ items|length }} 篇</a>
    {% for v in versions if v.date != versions[-1].date %}
    <a class="version {{ 'is-current' if v.current else '' }}"
       href="{{ static_prefix }}day/{{ v.href }}">{{ v.date[5:] }} · {{ v.n }} 篇</a>
    {% endfor %}
  </nav>
  {% endif %}
```

`static/style.css` 追加：

```css
.version-bar { display: flex; flex-wrap: wrap; gap: .6rem; align-items: baseline;
  margin: 0 0 1.4rem; padding-bottom: .6rem;
  border-bottom: 1px solid var(--rule-soft); }
.version-label { font-size: .72rem; letter-spacing: .16em; color: var(--ink-3); }
.version { font-size: .8rem; color: var(--ink-2); text-decoration: none;
  border-bottom: 1px solid transparent; }
.version:hover { border-bottom-color: var(--ink-3); }
.version.is-current { color: var(--ink-1); border-bottom-color: var(--ink-1); }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_render_versions.py -q`
Expected: PASS（6 passed）

Run: `.venv/bin/python -m pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/gdr/render.py templates/day.html static/style.css \
        tests/test_render_versions.py
git -c gpg.ssh.program=ssh-keygen -c user.signingkey="$HOME/.ssh/id_ed25519_headless" \
  commit -m "feat(render): historical version pages derived from ingest dates"
```

---

### Task 12: 补录徽标、日期链、归档页分组

**Files:**
- Modify: `src/gdr/render.py`
- Modify: `templates/day.html`、`templates/archive.html`
- Modify: `static/style.css`、`static/search.js`
- Test: `tests/test_render_badges.py`

**Interfaces:**
- Consumes: Task 10/11 的上下文
- Produces:
  - `backfill_batches(items) -> list[dict]` — `[{"date","n"}]`，首批不计入
  - `date_chain(item) -> list[dict]` — `[{"label","value"}]`，缺项不出现，月精度不补日
  - `archive_groups(by_archive: dict) -> list[dict]` — `[{"ym", "days": [{"date","n","breaking","backfills"}]}]`，倒序
  - `page_context` 增加 `batches`
  - 模板：卡片序号旁 `.backfill-badge`，页头 `.backfill-note`，卡片内 `.date-chain`

- [ ] **Step 1: Write the failing test**

创建 `tests/test_render_badges.py`：

```python
from gdr.render import archive_groups, backfill_batches, date_chain


def test_backfill_batches_exclude_the_first_ingest(ritem):
    items = [ritem("arxiv:1", archive="2026-07-14", ingested="2026-07-18"),
             ritem("arxiv:2", archive="2026-07-14", ingested="2026-07-22"),
             ritem("arxiv:3", archive="2026-07-14", ingested="2026-07-22")]

    assert backfill_batches(items) == [{"date": "2026-07-22", "n": 2}]


def test_no_batches_when_everything_arrived_together(ritem):
    assert backfill_batches([ritem("arxiv:1", archive="2026-07-14",
                                   ingested="2026-07-18")]) == []


def test_date_chain_omits_unknown_dates_and_keeps_month_precision(ritem):
    item = ritem("arxiv:1", archive="2026-03-14", ingested="2026-07-22")
    item["dates"].update({"preprint": "2026-03-14", "accepted": "",
                          "published": "2026-08", "published_precision": "month"})

    assert date_chain(item) == [{"label": "预印本", "value": "2026-03-14"},
                                {"label": "刊出", "value": "2026-08"},
                                {"label": "收录", "value": "2026-07-22"}]


def test_backfilled_cards_carry_a_badge_and_the_first_batch_does_not(
        ritem, build_site_from):
    out = build_site_from([
        ("2026-07-18", [ritem("arxiv:1", archive="2026-07-14",
                              ingested="2026-07-18")]),
        ("2026-07-22", [ritem("arxiv:2", archive="2026-07-14",
                              ingested="2026-07-22")])])

    page = (out / "day" / "2026-07-14.html").read_text(encoding="utf-8")

    assert page.count("backfill-badge") == 1
    assert "07-22 补录" in page
    assert "本页经 1 次补录" in page


def test_news_pages_have_no_backfill_badges(ritem, build_site_from):
    out = build_site_from([("2026-07-18", [ritem("arxiv:1",
                                                 archive="2026-07-14",
                                                 ingested="2026-07-18")])])

    assert "backfill-badge" not in (
        out / "news" / "2026-07-18.html").read_text(encoding="utf-8")


def test_archive_groups_by_year_month_newest_first(ritem, story_decision):
    items = {"2026-07-14": [ritem("arxiv:1", archive="2026-07-14",
                                  ingested="2026-07-18"),
                            ritem("arxiv:2", archive="2026-07-14",
                                  ingested="2026-07-22",
                                  decision=story_decision("arxiv:2",
                                                          "breaking"))],
             "2026-03-14": [ritem("arxiv:3", archive="2026-03-14",
                                  ingested="2026-07-22")]}

    groups = archive_groups(items)

    assert [g["ym"] for g in groups] == ["2026-07", "2026-03"]
    assert groups[0]["days"][0] == {"date": "2026-07-14", "n": 2,
                                    "breaking": True, "backfills": 1}
    assert groups[1]["days"][0]["breaking"] is False


def test_archive_page_marks_days_before_the_site_existed(ritem, build_site_from):
    out = build_site_from([("2026-07-22", [
        ritem("arxiv:1", archive="2026-03-14", ingested="2026-07-22"),
        ritem("arxiv:2", archive="2026-07-14", ingested="2026-07-22")])])

    page = (out / "archive.html").read_text(encoding="utf-8")

    assert "2026-03" in page
    assert "本站自 2026-07-12 起收录" in page
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_render_badges.py -q`
Expected: FAIL，`ImportError: cannot import name 'backfill_batches'`

- [ ] **Step 3: Write minimal implementation**

`src/gdr/config.py` 追加：

```python
# The first day this site ingested anything. Archive days before it hold only
# papers that were backfilled later, never that day's full literature.
SITE_COVERAGE_START = os.environ.get("GDR_SITE_COVERAGE_START", "2026-07-12")
```

`src/gdr/render.py` 追加：

```python
_DATE_LABELS = (("preprint", "预印本"), ("accepted", "接收"),
                ("published", "刊出"), ("ingested", "收录"))


def backfill_batches(items: list[dict]) -> list[dict]:
    """Later arrivals, grouped by the run that brought them. The first ingest is
    the day itself, not a backfill, so it never appears."""
    counts: dict[str, int] = {}
    for item in items:
        counts[item["dates"]["ingested"]] = counts.get(
            item["dates"]["ingested"], 0) + 1
    dates = sorted(counts)
    return [{"date": d, "n": counts[d]} for d in dates[1:]]


def date_chain(item: dict) -> list[dict]:
    """The four dates as printed on a card. Unknown dates are omitted rather than
    guessed, and a month-precision date stays a month."""
    dates = item["dates"]
    return [{"label": label, "value": dates.get(key, "")}
            for key, label in _DATE_LABELS if dates.get(key)]


def archive_groups(by_archive: dict[str, list[dict]]) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for date, items in by_archive.items():
        groups.setdefault(date[:7], []).append({
            "date": date,
            "n": len(items),
            "breaking": any((it.get("decision") or {}).get("level") == "breaking"
                            for it in items),
            "backfills": len(backfill_batches(items)),
        })
    return [{"ym": ym, "days": sorted(days, key=lambda d: d["date"], reverse=True)}
            for ym, days in sorted(groups.items(), reverse=True)]
```

`page_context` 里加 `ctx["batches"] = backfill_batches(items) if axis == "archive" else []`，并把 `first_ingest` 也放进去：`ctx["first_ingest"] = min((it["dates"]["ingested"] for it in ordered), default="")`。

`env.globals` 注册 `date_chain`。

`render_site` 的 archive 模板渲染改为传 `groups=archive_groups(by_archive)` 与 `coverage_start=config.SITE_COVERAGE_START`。**历史版本页不渲染徽标**：`page_context` 中当 `current_version` 非空时把 `batches` 置空。

`templates/day.html`：

- 版本条下方插入补录提示：

```jinja
  {% if batches %}
  <p class="backfill-note">本页经 {{ batches|length }} 次补录{% for b in batches %} · <button class="backfill-jump" data-ingest="{{ b.date }}">{{ b.date[5:] }} +{{ b.n }}</button>{% endfor %}</p>
  {% endif %}
```

- 论文卡片的序号 gutter 内，紧跟序号之后：

```jinja
        {% if axis == 'archive' and first_ingest and it.dates.ingested != first_ingest %}
        <span class="backfill-badge">{{ it.dates.ingested[5:] }} 补录</span>
        {% endif %}
```

- 卡片底部 arXiv 链接一行之前插入日期链：

```jinja
        <p class="date-chain">{% for d in date_chain(it) %}{% if not loop.first %} · {% endif %}{{ d.label }} {{ d.value }}{% endfor %}</p>
```

卡片循环变量若不是 `it`，按当前模板里的实际变量名替换（现有模板用 `it`）。同时给卡片根元素加 `data-ingest="{{ it.dates.ingested }}"` 供高亮用。

`templates/archive.html` 的列表改为：

```jinja
    {% for g in groups %}
    <section class="archive-group">
      <h3>{{ g.ym }}</h3>
      {% if g.ym < coverage_start[:7] %}<p class="archive-note">本站自 {{ coverage_start }} 起收录，此前日期仅含后期补录的论文。</p>{% endif %}
      <ul class="archive">
        {% for d in g.days %}
        <li><a href="{{ static_prefix }}day/{{ d.date }}.html">{{ d.date }}</a>
          <span class="archive-n">{{ d.n }} 篇</span>
          {% if d.breaking %}<span class="archive-breaking">突发</span>{% endif %}
          {% if d.backfills %}<span class="archive-rev">补录 {{ d.backfills }} 次</span>{% endif %}
        </li>
        {% endfor %}
      </ul>
    </section>
    {% endfor %}
```

`static/style.css` 追加：

```css
.backfill-note { font-size: .78rem; color: var(--ink-3); margin: -.8rem 0 1.4rem; }
.backfill-jump { font: inherit; color: var(--ink-2); background: none; border: 0;
  padding: 0; cursor: pointer; border-bottom: 1px dotted var(--rule-soft); }
.backfill-badge { display: block; margin-top: .3rem; font-size: .64rem;
  letter-spacing: .04em; color: var(--ink-3); }
.date-chain { font-size: .74rem; color: var(--ink-3); margin: .5rem 0 0; }
.archive-group h3 { font-size: .9rem; letter-spacing: .1em; color: var(--ink-2);
  margin: 1.6rem 0 .4rem; }
.archive-note { font-size: .74rem; color: var(--ink-3); margin: 0 0 .4rem; }
.archive-n, .archive-rev { font-size: .74rem; color: var(--ink-3); margin-left: .5rem; }
.archive-breaking { font-size: .7rem; color: var(--alert); margin-left: .5rem; }
.paper.is-flagged { background: color-mix(in oklch, var(--alert) 6%, transparent); }
```

`static/search.js` 追加：

```js
document.querySelectorAll('.backfill-jump').forEach(function (btn) {
  btn.addEventListener('click', function () {
    var want = btn.dataset.ingest;
    var on = !btn.classList.contains('is-on');
    document.querySelectorAll('.backfill-jump').forEach(function (b) {
      b.classList.remove('is-on');
    });
    if (on) { btn.classList.add('is-on'); }
    document.querySelectorAll('[data-ingest]').forEach(function (card) {
      if (!card.classList.contains('paper')) { return; }
      card.classList.toggle('is-flagged', on && card.dataset.ingest === want);
    });
  });
});
```

（卡片根元素的 class 若不是 `paper`，按模板实际类名调整这两处。）

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_render_badges.py -q`
Expected: PASS（7 passed）

Run: `.venv/bin/python -m pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/gdr/render.py src/gdr/config.py templates/day.html templates/archive.html \
        static/style.css static/search.js tests/test_render_badges.py
git -c gpg.ssh.program=ssh-keygen -c user.signingkey="$HOME/.ssh/id_ed25519_headless" \
  commit -m "feat(render): backfill badges, four-date chain, grouped archive index"
```

---

### Task 13: 清理旧布局、视觉核对、合并与部署

**Files:**
- Delete: `data/daily/`
- Modify: `src/gdr/store.py`（删 `save_day` / `load_day` / `load_day_or_none` / `list_days` / `daily_dir`）
- Modify: `src/gdr/models.py`（删 `DayData`）
- Modify: `src/gdr/reclassify.py`（改为在 ingest 布局上工作）
- Modify: `tests/test_models.py`、`tests/test_store.py`、`tests/test_reclassify.py`、`tests/test_migrated_data.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: 前 12 个任务
- Produces: 只剩一种存储布局的代码库

- [ ] **Step 1: 删除旧布局与旧代码**

```bash
git rm -r --quiet data/daily
```

`src/gdr/store.py`：删除 `daily_dir` 及 `save_day` / `load_day` / `load_day_or_none` / `list_days`；`ensure_seen_identities` 里遍历 `list_days()` 的一次性迁移逻辑改为遍历 `list_ingest_dates()`。

`src/gdr/models.py`：删除 `DayData`。

`src/gdr/migrate.py`：迁移已完成，整个模块连同 `scripts/migrate_two_axis.py`、`tests/test_migrate.py` 一并 `git rm`（它依赖已删除的 `DayData`；迁移过程与结论都记录在设计文档和 git 历史里）。

`tests/test_migrated_data.py`：删除两个 `if not DAILY.exists(): pytest.skip(...)` 的对比用例（对照物已不存在），保留 `test_every_item_has_an_ingest_date_and_an_archive_date` 与 `test_ingest_days_are_not_in_the_future_of_their_papers`。

`src/gdr/reclassify.py`：`reclassify_day(date, store, llm, ...)` 改为按**收录日**重打分：`day = store.load_ingest(date)`，重打分后 `store.save_ingest(day)`，删除写 `revisions` 的那段（版本已由收录日推导）。`tests/test_reclassify.py` 跟随改造。

`tests/test_models.py` / `tests/test_store.py`：删除针对 `DayData` / `save_day` 的用例。

- [ ] **Step 2: 跑全量测试**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS，且没有任何 skip

- [ ] **Step 3: 重建站点并视觉核对**

```bash
.venv/bin/python scripts/build_site.py
```

Expected: 打印 built N static files。

用 Playwright MCP 在 **1440px** 和 **414px** 两个宽度各看四个页面（截图写到 `.playwright-mcp/`，该目录已 gitignore）：

1. `site/index.html` —— 最新收录日，masthead 显示「本日收录」
2. 一个有补录的归档日 `site/day/2026-07-19.html` —— 版本条 + 补录提示 + 徽标 + 日期链
3. 它的历史版本 `site/day/2026-07-19.as-of-<首个收录日>.html` —— 论文更少、头条回到当时
4. `site/archive.html` —— 按年月分组，覆盖期之前的月份带说明

检查点：版本条不换行挤压；徽标不破坏序号 gutter 的对齐；日期链在窄屏不溢出；今日头条的 editorial v2 排版（密度分级、突发红色三处、空态双细线）与改造前一致。

- [ ] **Step 4: 更新 README 并做最后一次全量检查**

`README.md` 的架构一节追加一段：

```markdown
每篇论文携带四个日期（预印本、期刊接收、期刊刊出、本站收录）与一条一次性生成的编辑决策，
数据按收录日存放于 `data/ingest/<收录日>.json`，正常路径只新增文件、不改写历史。站点由此渲染
两条时间轴：`/news/<收录日>.html`（每日新闻，首页指向最新收录日）与 `/day/<归档日>.html`
（文献归档，归档日取预印本／接收／刊出中最早的一个）。归档日页面带版本条，可切换到任一历史
收录时刻的状态；最新版页面用徽标标出后续补录的论文。补录只为新论文调用模型，已有决策不再重算。
```

Run: `.venv/bin/python -m pytest -q`
Expected: PASS

- [ ] **Step 5: Commit、合并、部署**

```bash
git add -A
git -c gpg.ssh.program=ssh-keygen -c user.signingkey="$HOME/.ssh/id_ed25519_headless" \
  commit -m "refactor: drop the date-keyed layout now that both axes render from ingest files"
```

合并前**先确认今天的 cron 已经跑完**（北京时间 10:00 之后再合，避免 main 上出现中间态被自动部署）：

```bash
gh run list --workflow=daily-review --limit 3
git fetch && git rebase origin/main
.venv/bin/python -m pytest -q          # rebase 后必须再绿一次
git checkout main && git merge --ff-only feat/two-axis-archive && git push
```

部署（`git push` 本身不部署，必须手动触发）：

```bash
gh workflow run daily-review
gh run watch
curl -s https://hx-guo.github.io/daily-review/ | head -40
```

线上核对：首页是最新收录日、归档页分组正确、随便点开一个有版本条的归档日能切换版本。

---

## Self-Review

**Spec coverage**

| 设计文档章节 | 落在哪个任务 |
|---|---|
| §3 决策下沉、日级综述派生 | Task 4、Task 5 |
| §4.1 item 结构 | Task 3 |
| §4.2 四个日期与归档日规则 | Task 1、Task 3 |
| §4.3 Crossref 覆盖率与两个坑 | Task 1（预定刊期）、Task 2（长格式日期） |
| §4.4 存储布局、seen-index 升级 | Task 6 |
| §5.1 sync 重写、prompt 改日期 | Task 5（prompt）、Task 7（sync） |
| §5.2 跨批次 enrich | Task 7 |
| §5.3 两层失败处理、熔断 | Task 5（第一层 + 熔断）、Task 7（第二层） |
| §6 两条轴、版本下拉、补录徽标、日期链、归档分组 | Task 10、11、12 |
| §7 迁移（git 重建 / 三个日期 / 决策回填 / 验收） | Task 8、Task 9 |
| §8 测试 | 分散在各任务，端到端在 Task 13 |
| §9 落地顺序与三个风险 | Global Constraints（分支）、Task 13（避开 cron） |

**发现并已修正的问题**

1. 设计文档第 9 节的落地顺序把"删除 `data/daily`"放在迁移那一步，会让渲染层在 Task 10 之前失去数据源、测试变红。计划改为**迁移只新增 `data/ingest`，Task 13 才删旧目录**，于是每一次提交都是绿的、可回滚的。
2. 设计文档没有指定迁移脚本自身的归宿。`gdr/migrate.py` 依赖 `DayData`，而 `DayData` 在 Task 13 被删——计划明确在 Task 13 把迁移模块、脚本与其测试一并删除。
3. 设计文档说 `archive_date` 取三个学术日期中最早的非空值，但没说三个都为空时怎么办（无 arXiv id、Crossref 查不到、ADS 无 pubdate 的论文确实可能出现）。计划里 `make_item` 兜底到该论文的收录日，并有测试锁定这一行为。
4. `_quiet_overview` 原先接收的是"已总结的 core/related"，而 `compose_review` 拿到的是当天全部 item。计划在 `compose_review` 内部先过滤到 core/related，保证「当日 N 篇核心与相关文献」这句话的语义不变，并有测试锁定。
