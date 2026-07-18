# GECAM Daily Review — Phase 1 (MVP) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an end-to-end daily pipeline that fetches new arXiv papers, scores their relevance to GECAM science, reads full text, writes per-paper and daily Chinese reviews, and publishes a static site — running automatically every day via GitHub Actions.

**Architecture:** A small Python package `gdr` with one module per pipeline stage (source → dedup → relevance → fulltext → summary → daily review → store → render), wired together by `pipeline.py`. All LLM and network access is behind injectable interfaces so every stage is unit-testable with fakes/fixtures (no live calls in tests). Paper/entity data is persisted as JSON files committed to the repo; the rendered HTML is deployed as a GitHub Pages artifact.

**Tech Stack:** Python 3.11+, `requests` + `feedparser` (arXiv API), `beautifulsoup4` + `lxml` (full-text HTML parsing), `openai` SDK (opencode go, OpenAI-compatible), `jinja2` (static rendering), `pytest` (tests). GitHub Actions for scheduling + Pages for hosting.

## Global Constraints

- **Python:** 3.11+ (uses `X | None` syntax and `list[str]` generics).
- **Package layout:** `src/gdr/` installed editable via `pip install -e ".[dev]"`; tests in `tests/`.
- **Output language:** all reader-facing generated text is **Chinese**.
- **Scope = Phase 1 only.** Source is **arXiv only**. Deferred to later phases (do NOT build now): NASA ADS source, author/team profiling + author/team pages, journal-site scrapers, PDF/LaTeX-source full-text extraction (Phase 1 uses arXiv HTML → abstract fallback only), SQLite migration.
- **opencode go:** OpenAI-compatible, base URL `https://opencode.ai/zen/go/v1`. API key ONLY from env var `OPENCODE_API_KEY`; never hard-code or commit it.
- **Model tiers (config constants, env-overridable):** triage = `deepseek-v4-flash`, write = `deepseek-v4-pro`, synth = `kimi-k3`. These are the display-name-derived defaults; **exact API model ids MUST be confirmed via `python scripts/list_models.py` before the first live run** and overridden through env if they differ.
- **arXiv broad net categories:** `astro-ph.HE`, `gr-qc`, `astro-ph.SR`, `astro-ph.CO`.
- **Relevance layering (score 0–100):** `core` ≥ 70, `related` ≥ 40, else `edge` (kept, never dropped).
- **Persistence:** JSON under `data/` is committed to the repo. Rendered HTML under `site/` is a build artifact (git-ignored, deployed to Pages).
- **Cost discipline:** triage/relevance uses title+abstract only; full text is fetched and sent only for in-scope (core/related) papers.
- **Commits:** frequent, one per task. Conventional-commit prefixes (`feat:`, `test:`, `chore:`, `docs:`).

---

## File Structure

```
daily-review/
├── pyproject.toml                     # package + deps + pytest config
├── .gitignore                         # ignores site/, __pycache__, .venv, *.egg-info
├── README.md                          # setup + run instructions
├── src/gdr/
│   ├── __init__.py
│   ├── config.py                      # constants, GECAM profile text, env accessors
│   ├── models.py                      # dataclasses: Paper, RelevanceScore, PaperSummary, DailyReview, DayData
│   ├── jsonutil.py                    # robust "extract first JSON object from LLM text"
│   ├── llm.py                         # LLM protocol + OpenCodeLLM (openai SDK) + tier resolution
│   ├── sources/
│   │   ├── __init__.py
│   │   ├── base.py                    # Source ABC (adapter interface)
│   │   └── arxiv_source.py            # ArxivSource.fetch(date) -> list[Paper]
│   ├── dedup.py                       # dedupe(papers) -> list[Paper]
│   ├── relevance.py                   # score_paper(paper, llm) -> RelevanceScore
│   ├── fulltext.py                    # fetch_fulltext(paper) -> str | None
│   ├── summarize.py                   # summarize_paper(paper, fulltext, llm) -> PaperSummary
│   ├── daily_review.py                # make_daily_review(date, items, llm) -> DailyReview
│   ├── store.py                       # JSON persistence + seen-index
│   ├── render.py                      # Jinja2 rendering -> site/
│   └── pipeline.py                    # run(date, source, llm, store) orchestration
├── templates/                         # base.html, index.html, day.html, archive.html
├── static/                            # style.css, search.js
├── scripts/
│   ├── run_daily.py                   # CLI entry: build real deps, run pipeline
│   └── list_models.py                 # GET /v1/models -> print available model ids
├── data/                              # committed JSON output (created at runtime)
├── tests/
│   ├── conftest.py                    # FakeLLM + fixtures
│   ├── fixtures/arxiv_sample.xml      # saved arXiv Atom response
│   ├── fixtures/arxiv_html_sample.html
│   └── test_*.py
└── .github/workflows/daily.yml        # daily cron + Pages deploy
```

---

## Task 1: Project scaffolding + config

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `src/gdr/__init__.py`, `src/gdr/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `gdr.config.OPENCODE_BASE_URL: str`, `ARXIV_CATEGORIES: list[str]`, `MODEL_TRIAGE/MODEL_WRITE/MODEL_SYNTH: str`, `LAYER_CORE_MIN: int`, `LAYER_RELATED_MIN: int`, `SUMMARIZE_EDGE: bool`, `GECAM_PROFILE: str`, `get_api_key() -> str`, `layer_for(score: int) -> str`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
import os
import pytest
from gdr import config

def test_layer_for_thresholds():
    assert config.layer_for(85) == "core"
    assert config.layer_for(70) == "core"
    assert config.layer_for(55) == "related"
    assert config.layer_for(40) == "related"
    assert config.layer_for(20) == "edge"

def test_get_api_key_reads_env(monkeypatch):
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-test")
    assert config.get_api_key() == "sk-test"

def test_get_api_key_missing_raises(monkeypatch):
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        config.get_api_key()

def test_profile_and_categories_present():
    assert "GRB" in config.GECAM_PROFILE or "伽马暴" in config.GECAM_PROFILE
    assert "astro-ph.HE" in config.ARXIV_CATEGORIES
```

- [ ] **Step 2: Create `pyproject.toml`, `.gitignore`, and package init**

```toml
# pyproject.toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "gdr"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "requests>=2.31",
    "feedparser>=6.0",
    "beautifulsoup4>=4.12",
    "lxml>=5.0",
    "openai>=1.30",
    "jinja2>=3.1",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

```gitignore
# .gitignore
__pycache__/
*.egg-info/
.venv/
site/
.pytest_cache/
*.pyc
```

```python
# src/gdr/__init__.py
```

- [ ] **Step 3: Write `src/gdr/config.py`**

```python
# src/gdr/config.py
import os

OPENCODE_BASE_URL = os.environ.get("OPENCODE_BASE_URL", "https://opencode.ai/zen/go/v1")

ARXIV_CATEGORIES = ["astro-ph.HE", "gr-qc", "astro-ph.SR", "astro-ph.CO"]

# Model tiers. Defaults are display-name-derived; confirm exact ids via scripts/list_models.py.
MODEL_TRIAGE = os.environ.get("GDR_MODEL_TRIAGE", "deepseek-v4-flash")
MODEL_WRITE = os.environ.get("GDR_MODEL_WRITE", "deepseek-v4-pro")
MODEL_SYNTH = os.environ.get("GDR_MODEL_SYNTH", "kimi-k3")

LAYER_CORE_MIN = 70
LAYER_RELATED_MIN = 40
SUMMARIZE_EDGE = False

# Max characters of full text sent to the write model (token control).
FULLTEXT_MAX_CHARS = 24000

GECAM_PROFILE = """GECAM（引力波高能电磁对应体全天监测器）团队关注的科学范围，分三层：

核心主题（直接科学目标）：
- 伽马暴 GRB（长/短暴、prompt/余辉、能谱、jet、宿主）
- 引力波电磁对应体（BNS/NSBH 并合、kilonova、GW170817-like、O4/O5 后随观测）
- 磁星 / 软伽马重复暴 SGR（巨耀发、暴发、SGR 1935+2154）
- 快速射电暴 FRB（尤其高能对应体、FRB–磁星联系）
- 多信使触发与联合（LIGO/Virgo/KAGRA 引力波、IceCube 中微子）

相关主题（高能暂现源大类 + 相关任务）：
- 高能暂现天体：TDE、X/γ 射线暂现、新星/超新星激波、中子星/黑洞暂现现象
- 太阳耀斑、硬 X 射线爆发、地球伽马闪 TGF
- 相关任务：Fermi/GBM、Swift、HXMT/Insight、Einstein Probe、SVOM、Integral、Konus-Wind、GECAM

边缘主题（相关度低但不丢弃）：
- astro-ph.HE 内其余物理（宇宙线、暗物质、AGN 稳态物理等）
"""


def get_api_key() -> str:
    key = os.environ.get("OPENCODE_API_KEY")
    if not key:
        raise RuntimeError("OPENCODE_API_KEY environment variable is not set")
    return key


def layer_for(score: int) -> str:
    if score >= LAYER_CORE_MIN:
        return "core"
    if score >= LAYER_RELATED_MIN:
        return "related"
    return "edge"
```

- [ ] **Step 4: Install and run tests**

Run: `pip install -e ".[dev]" && pytest tests/test_config.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .gitignore src/gdr/__init__.py src/gdr/config.py tests/test_config.py
git commit -m "chore: scaffold gdr package and config"
```

---

## Task 2: Data models

**Files:**
- Create: `src/gdr/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces dataclasses, each with `to_dict()` and classmethod `from_dict(d)`:
  - `Paper(id, source, title, authors: list[str], abstract, categories: list[str], published, url, pdf_url=None, doi=None)`
  - `RelevanceScore(score: int, tags: list[str], layer: str, reason: str)`
  - `PaperSummary(paper_id, title_zh, team, tldr, review, highlight, relation)`
  - `DailyReview(date, overview, highlights, trends)`
  - `DayData(date, review: DailyReview, items: list[dict])` where each item is `{"paper": Paper, "score": RelevanceScore, "summary": PaperSummary | None}` and `to_dict/from_dict` recurse.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models.py
from gdr.models import Paper, RelevanceScore, PaperSummary, DailyReview, DayData

def _paper():
    return Paper(id="arxiv:2607.00001", source="arxiv", title="A GRB study",
                 authors=["A. Author", "B. Boss"], abstract="We study a GRB.",
                 categories=["astro-ph.HE"], published="2026-07-18",
                 url="https://arxiv.org/abs/2607.00001", pdf_url=None, doi=None)

def test_paper_roundtrip():
    p = _paper()
    assert Paper.from_dict(p.to_dict()) == p

def test_daydata_roundtrip():
    p = _paper()
    score = RelevanceScore(score=88, tags=["GRB"], layer="core", reason="direct GECAM topic")
    summ = PaperSummary(paper_id=p.id, title_zh="一项伽马暴研究", team="A. Author 等",
                        tldr="研究了一个伽马暴", review="……", highlight="……", relation="……")
    review = DailyReview(date="2026-07-18", overview="今日 1 篇", highlights="……", trends="……")
    day = DayData(date="2026-07-18", review=review,
                  items=[{"paper": p, "score": score, "summary": summ}])
    back = DayData.from_dict(day.to_dict())
    assert back == day
    assert back.items[0]["paper"].title == "A GRB study"
    assert back.items[0]["summary"].title_zh == "一项伽马暴研究"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: FAIL (ImportError: cannot import name 'Paper')

- [ ] **Step 3: Write `src/gdr/models.py`**

```python
# src/gdr/models.py
from __future__ import annotations
from dataclasses import dataclass, asdict


@dataclass
class Paper:
    id: str
    source: str
    title: str
    authors: list[str]
    abstract: str
    categories: list[str]
    published: str
    url: str
    pdf_url: str | None = None
    doi: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Paper":
        return cls(**d)


@dataclass
class RelevanceScore:
    score: int
    tags: list[str]
    layer: str
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RelevanceScore":
        return cls(**d)


@dataclass
class PaperSummary:
    paper_id: str
    title_zh: str
    team: str
    tldr: str
    review: str
    highlight: str
    relation: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PaperSummary":
        return cls(**d)


@dataclass
class DailyReview:
    date: str
    overview: str
    highlights: str
    trends: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "DailyReview":
        return cls(**d)


@dataclass
class DayData:
    date: str
    review: DailyReview
    items: list[dict]  # {"paper": Paper, "score": RelevanceScore, "summary": PaperSummary | None}

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "review": self.review.to_dict(),
            "items": [
                {
                    "paper": it["paper"].to_dict(),
                    "score": it["score"].to_dict(),
                    "summary": it["summary"].to_dict() if it["summary"] else None,
                }
                for it in self.items
            ],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DayData":
        items = [
            {
                "paper": Paper.from_dict(it["paper"]),
                "score": RelevanceScore.from_dict(it["score"]),
                "summary": PaperSummary.from_dict(it["summary"]) if it.get("summary") else None,
            }
            for it in d["items"]
        ]
        return cls(date=d["date"], review=DailyReview.from_dict(d["review"]), items=items)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/gdr/models.py tests/test_models.py
git commit -m "feat: add data models with json roundtrip"
```

---

## Task 3: JSON extraction helper

**Files:**
- Create: `src/gdr/jsonutil.py`
- Test: `tests/test_jsonutil.py`

**Interfaces:**
- Produces: `extract_json(text: str) -> dict` — returns the first top-level JSON object found in an LLM reply, tolerating ```` ```json ```` fences and surrounding prose. Raises `ValueError` if none found.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_jsonutil.py
import pytest
from gdr.jsonutil import extract_json

def test_plain_json():
    assert extract_json('{"score": 80, "tags": ["GRB"]}') == {"score": 80, "tags": ["GRB"]}

def test_fenced_json():
    text = 'Here is the result:\n```json\n{"a": 1, "b": {"c": 2}}\n```\nDone.'
    assert extract_json(text) == {"a": 1, "b": {"c": 2}}

def test_prose_then_object():
    assert extract_json('分数如下 {"score": 55} 谢谢') == {"score": 55}

def test_no_json_raises():
    with pytest.raises(ValueError):
        extract_json("no json here")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_jsonutil.py -v`
Expected: FAIL (ModuleNotFoundError: gdr.jsonutil)

- [ ] **Step 3: Write `src/gdr/jsonutil.py`**

```python
# src/gdr/jsonutil.py
import json


def extract_json(text: str) -> dict:
    """Return the first balanced top-level JSON object in an LLM reply."""
    start = text.find("{")
    while start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = text[start : i + 1]
                        try:
                            return json.loads(candidate)
                        except json.JSONDecodeError:
                            break
        start = text.find("{", start + 1)
    raise ValueError("no JSON object found in text")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_jsonutil.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/gdr/jsonutil.py tests/test_jsonutil.py
git commit -m "feat: add robust json extraction for llm output"
```

---

## Task 4: LLM client + fake

**Files:**
- Create: `src/gdr/llm.py`, `tests/conftest.py`
- Test: `tests/test_llm.py`

**Interfaces:**
- Produces:
  - `LLM` (typing.Protocol) with `complete(self, model: str, system: str, user: str, temperature: float = 0.3) -> str`
  - `OpenCodeLLM(api_key: str, base_url: str)` implementing `LLM` via the `openai` SDK
  - `tier_model(tier: str) -> str` mapping `"triage"|"write"|"synth"` to the config model ids
- `tests/conftest.py` produces the `FakeLLM` fixture used by later tasks:
  - `FakeLLM(responses: dict[str, str] | list[str])` — records calls in `.calls`, returns queued/keyed replies from `complete(...)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_llm.py
from gdr.llm import tier_model
from gdr import config

def test_tier_model_maps_to_config():
    assert tier_model("triage") == config.MODEL_TRIAGE
    assert tier_model("write") == config.MODEL_WRITE
    assert tier_model("synth") == config.MODEL_SYNTH

def test_fake_llm_records_and_replies(fake_llm_factory):
    llm = fake_llm_factory(["hello"])
    out = llm.complete(model="m", system="s", user="u")
    assert out == "hello"
    assert llm.calls[0]["model"] == "m"
    assert llm.calls[0]["user"] == "u"
```

- [ ] **Step 2: Write `tests/conftest.py` with the FakeLLM factory**

```python
# tests/conftest.py
import pytest


class FakeLLM:
    """Test double for gdr.llm.LLM. Returns queued or keyed responses."""

    def __init__(self, responses):
        self._responses = responses
        self._i = 0
        self.calls = []

    def complete(self, model, system, user, temperature=0.3):
        self.calls.append({"model": model, "system": system, "user": user})
        if isinstance(self._responses, dict):
            for key, val in self._responses.items():
                if key in user:
                    return val
            raise AssertionError(f"no keyed FakeLLM response matched user prompt")
        resp = self._responses[self._i]
        self._i += 1
        return resp


@pytest.fixture
def fake_llm_factory():
    return lambda responses: FakeLLM(responses)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_llm.py -v`
Expected: FAIL (ModuleNotFoundError: gdr.llm)

- [ ] **Step 4: Write `src/gdr/llm.py`**

```python
# src/gdr/llm.py
from typing import Protocol
from gdr import config


class LLM(Protocol):
    def complete(self, model: str, system: str, user: str, temperature: float = 0.3) -> str:
        ...


_TIERS = {
    "triage": config.MODEL_TRIAGE,
    "write": config.MODEL_WRITE,
    "synth": config.MODEL_SYNTH,
}


def tier_model(tier: str) -> str:
    return _TIERS[tier]


class OpenCodeLLM:
    def __init__(self, api_key: str, base_url: str = config.OPENCODE_BASE_URL):
        from openai import OpenAI  # imported lazily so tests don't need the network
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    def complete(self, model: str, system: str, user: str, temperature: float = 0.3) -> str:
        resp = self._client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
        )
        return resp.choices[0].message.content or ""
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_llm.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add src/gdr/llm.py tests/conftest.py tests/test_llm.py
git commit -m "feat: add llm client protocol, opencode impl, and fake"
```

---

## Task 5: arXiv source adapter

**Files:**
- Create: `src/gdr/sources/__init__.py`, `src/gdr/sources/base.py`, `src/gdr/sources/arxiv_source.py`, `tests/fixtures/arxiv_sample.xml`
- Test: `tests/test_arxiv_source.py`

**Interfaces:**
- Consumes: `gdr.models.Paper`
- Produces:
  - `Source` (ABC) with `fetch(self, date: str) -> list[Paper]`
  - `ArxivSource(categories: list[str], http_get=requests.get)` implementing `Source`; `http_get` is injectable for testing. Internally builds the arXiv API query, parses the Atom feed with `feedparser`, and returns `Paper`s whose published date == `date`.
  - Helper `parse_atom(xml: str, date: str) -> list[Paper]` (module-level, pure, tested directly).

- [ ] **Step 1: Create the fixture** `tests/fixtures/arxiv_sample.xml`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2607.00001v1</id>
    <updated>2026-07-18T10:00:00Z</updated>
    <published>2026-07-18T09:00:00Z</published>
    <title>A magnetar giant flare study</title>
    <summary>We analyze a magnetar giant flare observed by GECAM.</summary>
    <author><name>Alice Author</name></author>
    <author><name>Bob Boss</name></author>
    <link href="http://arxiv.org/abs/2607.00001v1" rel="alternate" type="text/html"/>
    <link title="pdf" href="http://arxiv.org/pdf/2607.00001v1" rel="related" type="application/pdf"/>
    <arxiv:doi>10.0000/example</arxiv:doi>
    <category term="astro-ph.HE" scheme="http://arxiv.org/schemas/atom"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2607.00002v1</id>
    <updated>2026-07-17T10:00:00Z</updated>
    <published>2026-07-17T09:00:00Z</published>
    <title>An older paper</title>
    <summary>Published the previous day.</summary>
    <author><name>Carol Coauthor</name></author>
    <link href="http://arxiv.org/abs/2607.00002v1" rel="alternate" type="text/html"/>
    <category term="gr-qc" scheme="http://arxiv.org/schemas/atom"/>
  </entry>
</feed>
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_arxiv_source.py
from pathlib import Path
from gdr.sources.arxiv_source import parse_atom, ArxivSource

SAMPLE = (Path(__file__).parent / "fixtures" / "arxiv_sample.xml").read_text()

def test_parse_atom_filters_by_date():
    papers = parse_atom(SAMPLE, date="2026-07-18")
    assert len(papers) == 1
    p = papers[0]
    assert p.id == "arxiv:2607.00001"
    assert p.title == "A magnetar giant flare study"
    assert p.authors == ["Alice Author", "Bob Boss"]
    assert p.categories == ["astro-ph.HE"]
    assert p.pdf_url == "http://arxiv.org/pdf/2607.00001v1"
    assert p.doi == "10.0000/example"
    assert p.published == "2026-07-18"

def test_fetch_uses_injected_http_get():
    class Resp:
        text = SAMPLE
        def raise_for_status(self): pass
    captured = {}
    def fake_get(url, params=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        return Resp()
    src = ArxivSource(categories=["astro-ph.HE", "gr-qc"], http_get=fake_get)
    papers = src.fetch("2026-07-18")
    assert len(papers) == 1
    assert "astro-ph.HE" in captured["params"]["search_query"]
    assert "gr-qc" in captured["params"]["search_query"]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_arxiv_source.py -v`
Expected: FAIL (ModuleNotFoundError: gdr.sources)

- [ ] **Step 4: Write the source modules**

```python
# src/gdr/sources/__init__.py
```

```python
# src/gdr/sources/base.py
from abc import ABC, abstractmethod
from gdr.models import Paper


class Source(ABC):
    @abstractmethod
    def fetch(self, date: str) -> list[Paper]:
        """Return papers announced/published on `date` (YYYY-MM-DD)."""
        raise NotImplementedError
```

```python
# src/gdr/sources/arxiv_source.py
import feedparser
import requests
from gdr.models import Paper
from gdr.sources.base import Source

ARXIV_API = "http://export.arxiv.org/api/query"


def _arxiv_id(entry_id: str) -> str:
    # "http://arxiv.org/abs/2607.00001v1" -> "arxiv:2607.00001"
    tail = entry_id.rsplit("/abs/", 1)[-1]
    if "v" in tail:
        tail = tail.split("v")[0]
    return f"arxiv:{tail}"


def parse_atom(xml: str, date: str) -> list[Paper]:
    feed = feedparser.parse(xml)
    papers: list[Paper] = []
    for e in feed.entries:
        published = e.get("published", "")[:10]
        if published != date:
            continue
        pdf_url = None
        for link in e.get("links", []):
            if link.get("title") == "pdf" or link.get("type") == "application/pdf":
                pdf_url = link.get("href")
        categories = [t.get("term") for t in e.get("tags", []) if t.get("term")]
        papers.append(
            Paper(
                id=_arxiv_id(e.id),
                source="arxiv",
                title=e.title.strip().replace("\n", " "),
                authors=[a.name for a in e.get("authors", [])],
                abstract=e.get("summary", "").strip().replace("\n", " "),
                categories=categories,
                published=published,
                url=e.get("link", ""),
                pdf_url=pdf_url,
                doi=e.get("arxiv_doi"),
            )
        )
    return papers


class ArxivSource(Source):
    def __init__(self, categories: list[str], http_get=requests.get, max_results: int = 300):
        self.categories = categories
        self._http_get = http_get
        self.max_results = max_results

    def fetch(self, date: str) -> list[Paper]:
        query = " OR ".join(f"cat:{c}" for c in self.categories)
        params = {
            "search_query": query,
            "start": 0,
            "max_results": self.max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        resp = self._http_get(ARXIV_API, params=params, timeout=60)
        resp.raise_for_status()
        return parse_atom(resp.text, date)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_arxiv_source.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add src/gdr/sources tests/test_arxiv_source.py tests/fixtures/arxiv_sample.xml
git commit -m "feat: add arxiv source adapter with date filtering"
```

---

## Task 6: Dedup / normalize

**Files:**
- Create: `src/gdr/dedup.py`
- Test: `tests/test_dedup.py`

**Interfaces:**
- Consumes: `gdr.models.Paper`
- Produces: `dedupe(papers: list[Paper]) -> list[Paper]` — removes duplicates, keying on DOI when present, else canonical id, else normalized title; keeps first occurrence, preserves order.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dedup.py
from gdr.models import Paper
from gdr.dedup import dedupe

def _p(id, doi=None, title="T"):
    return Paper(id=id, source="arxiv", title=title, authors=[], abstract="",
                 categories=[], published="2026-07-18", url="", pdf_url=None, doi=doi)

def test_dedupe_by_id():
    out = dedupe([_p("arxiv:1"), _p("arxiv:1"), _p("arxiv:2")])
    assert [p.id for p in out] == ["arxiv:1", "arxiv:2"]

def test_dedupe_by_doi_across_ids():
    out = dedupe([_p("arxiv:1", doi="10.1/x"), _p("arxiv:2", doi="10.1/x")])
    assert [p.id for p in out] == ["arxiv:1"]

def test_dedupe_by_title_when_no_doi():
    out = dedupe([_p("arxiv:1", title="A  GRB Study"), _p("arxiv:2", title="a grb study")])
    assert [p.id for p in out] == ["arxiv:1"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_dedup.py -v`
Expected: FAIL (ModuleNotFoundError: gdr.dedup)

- [ ] **Step 3: Write `src/gdr/dedup.py`**

```python
# src/gdr/dedup.py
import re
from gdr.models import Paper


def _norm_title(title: str) -> str:
    return re.sub(r"\s+", " ", title).strip().lower()


def _key(p: Paper) -> str:
    if p.doi:
        return f"doi:{p.doi.strip().lower()}"
    if p.id:
        return f"id:{p.id}"
    return f"title:{_norm_title(p.title)}"


def dedupe(papers: list[Paper]) -> list[Paper]:
    seen: set[str] = set()
    title_seen: set[str] = set()
    out: list[Paper] = []
    for p in papers:
        k = _key(p)
        t = _norm_title(p.title)
        if k in seen or t in title_seen:
            continue
        seen.add(k)
        title_seen.add(t)
        out.append(p)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_dedup.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/gdr/dedup.py tests/test_dedup.py
git commit -m "feat: add paper dedup/normalize"
```

---

## Task 7: Relevance scoring

**Files:**
- Create: `src/gdr/relevance.py`
- Test: `tests/test_relevance.py`

**Interfaces:**
- Consumes: `gdr.models.Paper`, `gdr.models.RelevanceScore`, `gdr.llm.LLM`, `gdr.jsonutil.extract_json`, `gdr.config`
- Produces: `score_paper(paper: Paper, llm: LLM) -> RelevanceScore` — sends title+abstract+GECAM profile to the triage model, parses `{score, tags, reason}`, derives `layer` via `config.layer_for`. Clamps score to 0–100; on parse failure returns a safe `edge` score of 0 with reason noting the failure (never drops a paper).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_relevance.py
import json
from gdr.models import Paper
from gdr.relevance import score_paper

def _paper():
    return Paper(id="arxiv:1", source="arxiv", title="Magnetar giant flare",
                 authors=[], abstract="A magnetar SGR burst.", categories=["astro-ph.HE"],
                 published="2026-07-18", url="")

def test_score_paper_parses_and_layers(fake_llm_factory):
    reply = json.dumps({"score": 92, "tags": ["磁星", "SGR"], "reason": "GECAM 核心主题"})
    llm = fake_llm_factory([reply])
    rs = score_paper(_paper(), llm)
    assert rs.score == 92
    assert rs.layer == "core"
    assert "磁星" in rs.tags
    assert llm.calls[0]["model"] != ""  # triage model used

def test_score_paper_bad_output_is_safe_edge(fake_llm_factory):
    llm = fake_llm_factory(["not json at all"])
    rs = score_paper(_paper(), llm)
    assert rs.layer == "edge"
    assert rs.score == 0

def test_score_clamped(fake_llm_factory):
    llm = fake_llm_factory([json.dumps({"score": 150, "tags": [], "reason": "x"})])
    assert score_paper(_paper(), llm).score == 100
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_relevance.py -v`
Expected: FAIL (ModuleNotFoundError: gdr.relevance)

- [ ] **Step 3: Write `src/gdr/relevance.py`**

```python
# src/gdr/relevance.py
from gdr import config
from gdr.jsonutil import extract_json
from gdr.llm import LLM, tier_model
from gdr.models import Paper, RelevanceScore

_SYSTEM = "你是天体物理文献筛选助手，只输出 JSON。"

_USER_TMPL = """下面是 GECAM 团队的科学关注范围：
{profile}

请判断这篇论文与上述范围的相关性，输出 JSON：
{{"score": 0-100 的整数, "tags": ["主题标签", ...], "reason": "一句话理由（中文）"}}
score 越高越相关；宁可给中间分也不要漏判边缘相关的论文。

标题：{title}
摘要：{abstract}
分类：{categories}
"""


def score_paper(paper: Paper, llm: LLM) -> RelevanceScore:
    user = _USER_TMPL.format(
        profile=config.GECAM_PROFILE,
        title=paper.title,
        abstract=paper.abstract,
        categories=", ".join(paper.categories),
    )
    text = llm.complete(model=tier_model("triage"), system=_SYSTEM, user=user)
    try:
        data = extract_json(text)
        score = int(data.get("score", 0))
        score = max(0, min(100, score))
        tags = [str(t) for t in data.get("tags", [])]
        reason = str(data.get("reason", ""))
    except (ValueError, TypeError):
        score, tags, reason = 0, [], "打分输出解析失败，保守归为边缘"
    return RelevanceScore(score=score, tags=tags, layer=config.layer_for(score), reason=reason)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_relevance.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/gdr/relevance.py tests/test_relevance.py
git commit -m "feat: add relevance scoring stage"
```

---

## Task 8: Full-text fetch

**Files:**
- Create: `src/gdr/fulltext.py`, `tests/fixtures/arxiv_html_sample.html`
- Test: `tests/test_fulltext.py`

**Interfaces:**
- Consumes: `gdr.models.Paper`, `gdr.config.FULLTEXT_MAX_CHARS`
- Produces: `fetch_fulltext(paper: Paper, http_get=requests.get) -> str | None` — for arXiv papers, GETs `https://arxiv.org/html/<bare_id>`, extracts readable text from the article body, truncates to `FULLTEXT_MAX_CHARS`. Returns `None` on any failure (non-200, network error, non-arxiv paper) so callers fall back to the abstract. Helper `extract_text(html: str) -> str` is pure and tested directly.

- [ ] **Step 1: Create fixture** `tests/fixtures/arxiv_html_sample.html`

```html
<html><body>
<nav>skip me</nav>
<article>
<h1>Magnetar Giant Flares</h1>
<p>We present observations of a magnetar giant flare.</p>
<p>The burst was detected by GECAM and analyzed in detail.</p>
</article>
<footer>skip me too</footer>
</body></html>
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_fulltext.py
from pathlib import Path
from gdr.models import Paper
from gdr.fulltext import extract_text, fetch_fulltext

HTML = (Path(__file__).parent / "fixtures" / "arxiv_html_sample.html").read_text()

def _paper():
    return Paper(id="arxiv:2607.00001", source="arxiv", title="t", authors=[],
                 abstract="a", categories=[], published="2026-07-18", url="")

def test_extract_text_gets_body_content():
    text = extract_text(HTML)
    assert "magnetar giant flare" in text.lower()
    assert "detected by GECAM" in text

def test_fetch_fulltext_success():
    class Resp:
        status_code = 200
        text = HTML
    def fake_get(url, timeout=None):
        assert "2607.00001" in url
        return Resp()
    out = fetch_fulltext(_paper(), http_get=fake_get)
    assert out is not None and "GECAM" in out

def test_fetch_fulltext_404_returns_none():
    class Resp:
        status_code = 404
        text = ""
    out = fetch_fulltext(_paper(), http_get=lambda url, timeout=None: Resp())
    assert out is None

def test_fetch_fulltext_non_arxiv_returns_none():
    p = _paper()
    p.source = "journal"
    assert fetch_fulltext(p, http_get=lambda url, timeout=None: None) is None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_fulltext.py -v`
Expected: FAIL (ModuleNotFoundError: gdr.fulltext)

- [ ] **Step 4: Write `src/gdr/fulltext.py`**

```python
# src/gdr/fulltext.py
import requests
from bs4 import BeautifulSoup
from gdr import config
from gdr.models import Paper


def extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["nav", "footer", "script", "style"]):
        tag.decompose()
    body = soup.find("article") or soup.body or soup
    text = body.get_text(separator="\n")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines)


def fetch_fulltext(paper: Paper, http_get=requests.get) -> str | None:
    if paper.source != "arxiv":
        return None
    bare = paper.id.split(":", 1)[-1]
    url = f"https://arxiv.org/html/{bare}"
    try:
        resp = http_get(url, timeout=60)
    except Exception:
        return None
    if getattr(resp, "status_code", None) != 200:
        return None
    text = extract_text(resp.text)
    if not text:
        return None
    return text[: config.FULLTEXT_MAX_CHARS]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_fulltext.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add src/gdr/fulltext.py tests/test_fulltext.py tests/fixtures/arxiv_html_sample.html
git commit -m "feat: add arxiv html full-text fetch with abstract fallback"
```

---

## Task 9: Per-paper summarize

**Files:**
- Create: `src/gdr/summarize.py`
- Test: `tests/test_summarize.py`

**Interfaces:**
- Consumes: `gdr.models.Paper`, `gdr.models.PaperSummary`, `gdr.llm.LLM`, `gdr.jsonutil.extract_json`
- Produces: `summarize_paper(paper: Paper, fulltext: str | None, llm: LLM) -> PaperSummary` — sends the card template + full text (or abstract if `fulltext` is None) to the write model, parses the six card fields. On parse failure, returns a `PaperSummary` filled from the paper's own metadata (title as `title_zh`, abstract as `review`) so the card is never blank.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_summarize.py
import json
from gdr.models import Paper
from gdr.summarize import summarize_paper

def _paper():
    return Paper(id="arxiv:1", source="arxiv", title="Magnetar giant flare",
                 authors=["Alice Author"], abstract="A magnetar SGR burst.",
                 categories=["astro-ph.HE"], published="2026-07-18", url="")

def test_summarize_uses_fulltext_and_parses(fake_llm_factory):
    reply = json.dumps({
        "title_zh": "磁星巨耀发", "team": "Alice Author 等", "tldr": "研究一次磁星巨耀发",
        "review": "……三到五句……", "highlight": "首次……", "relation": "与 GECAM 磁星课题相关",
    })
    llm = fake_llm_factory([reply])
    s = summarize_paper(_paper(), fulltext="FULL BODY TEXT", llm=llm)
    assert s.title_zh == "磁星巨耀发"
    assert s.paper_id == "arxiv:1"
    assert "FULL BODY TEXT" in llm.calls[0]["user"]

def test_summarize_falls_back_to_abstract(fake_llm_factory):
    llm = fake_llm_factory([json.dumps({"title_zh": "x", "team": "", "tldr": "",
                                        "review": "", "highlight": "", "relation": ""})])
    summarize_paper(_paper(), fulltext=None, llm=llm)
    assert "A magnetar SGR burst." in llm.calls[0]["user"]

def test_summarize_bad_output_uses_metadata(fake_llm_factory):
    llm = fake_llm_factory(["garbage"])
    s = summarize_paper(_paper(), fulltext=None, llm=llm)
    assert s.title_zh == "Magnetar giant flare"
    assert s.review == "A magnetar SGR burst."
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_summarize.py -v`
Expected: FAIL (ModuleNotFoundError: gdr.summarize)

- [ ] **Step 3: Write `src/gdr/summarize.py`**

```python
# src/gdr/summarize.py
from gdr.jsonutil import extract_json
from gdr.llm import LLM, tier_model
from gdr.models import Paper, PaperSummary

_SYSTEM = "你是高能天体物理文献综述助手，用简洁中文写作，只输出 JSON。"

_USER_TMPL = """请为下面这篇论文写一张中文综述卡片，输出 JSON（所有字段中文，力求简洁可扫读）：
{{
  "title_zh": "标题的中文译名",
  "team": "第一作者、通讯作者、主要机构；是否知名合作组",
  "tldr": "一句话核心：这篇干了什么",
  "review": "内容综述，3-5 句：研究对象/数据方法/主要结果/结论",
  "highlight": "亮点：为什么值得关注、创新点",
  "relation": "与 GECAM 科学目标或高能暂现研究的联系；无则写'—'"
}}

英文标题：{title}
作者：{authors}
分类：{categories}
正文/摘要：
{body}
"""


def summarize_paper(paper: Paper, fulltext: str | None, llm: LLM) -> PaperSummary:
    body = fulltext if fulltext else paper.abstract
    user = _USER_TMPL.format(
        title=paper.title,
        authors=", ".join(paper.authors),
        categories=", ".join(paper.categories),
        body=body,
    )
    text = llm.complete(model=tier_model("write"), system=_SYSTEM, user=user)
    try:
        d = extract_json(text)
        return PaperSummary(
            paper_id=paper.id,
            title_zh=str(d.get("title_zh") or paper.title),
            team=str(d.get("team", "")),
            tldr=str(d.get("tldr", "")),
            review=str(d.get("review", "")),
            highlight=str(d.get("highlight", "")),
            relation=str(d.get("relation", "")),
        )
    except (ValueError, TypeError):
        return PaperSummary(
            paper_id=paper.id, title_zh=paper.title, team=", ".join(paper.authors),
            tldr="", review=paper.abstract, highlight="", relation="—",
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_summarize.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/gdr/summarize.py tests/test_summarize.py
git commit -m "feat: add per-paper summary stage"
```

---

## Task 10: Daily overview review

**Files:**
- Create: `src/gdr/daily_review.py`
- Test: `tests/test_daily_review.py`

**Interfaces:**
- Consumes: `gdr.models.DailyReview`, `gdr.llm.LLM`, `gdr.jsonutil.extract_json`
- Produces: `make_daily_review(date: str, items: list[dict], llm: LLM) -> DailyReview` — `items` are the scored/summarized entries (`{"paper", "score", "summary"}`); builds a compact digest (title_zh, tags, layer, tldr per item), sends to the synth model, parses `{overview, highlights, trends}`. On empty items returns a "今日无新文献" review without calling the LLM. On parse failure returns a minimal review noting counts.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_daily_review.py
import json
from gdr.models import Paper, RelevanceScore, PaperSummary
from gdr.daily_review import make_daily_review

def _item(layer="core"):
    p = Paper(id="arxiv:1", source="arxiv", title="t", authors=[], abstract="",
              categories=[], published="2026-07-18", url="")
    s = RelevanceScore(score=90, tags=["GRB"], layer=layer, reason="")
    summ = PaperSummary(paper_id="arxiv:1", title_zh="伽马暴研究", team="", tldr="研究了伽马暴",
                        review="", highlight="", relation="")
    return {"paper": p, "score": s, "summary": summ}

def test_make_daily_review_parses(fake_llm_factory):
    reply = json.dumps({"overview": "今日 1 篇", "highlights": "亮点是……", "trends": "趋势是……"})
    llm = fake_llm_factory([reply])
    r = make_daily_review("2026-07-18", [_item()], llm)
    assert r.date == "2026-07-18"
    assert r.overview == "今日 1 篇"
    assert "伽马暴研究" in llm.calls[0]["user"]

def test_empty_day_skips_llm(fake_llm_factory):
    llm = fake_llm_factory([])
    r = make_daily_review("2026-07-18", [], llm)
    assert r.date == "2026-07-18"
    assert llm.calls == []
    assert "无新文献" in r.overview
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_daily_review.py -v`
Expected: FAIL (ModuleNotFoundError: gdr.daily_review)

- [ ] **Step 3: Write `src/gdr/daily_review.py`**

```python
# src/gdr/daily_review.py
from gdr.jsonutil import extract_json
from gdr.llm import LLM, tier_model
from gdr.models import DailyReview

_SYSTEM = "你是高能天体物理领域的资深综述编辑，用简洁中文写作，只输出 JSON。"

_USER_TMPL = """今天（{date}）收录了以下文献（按相关性分层）：
{digest}

请写当日总览综述，输出 JSON：
{{
  "overview": "今日概览：多少篇、各主题分布",
  "highlights": "今日亮点：挑 2-4 篇最值得读的，逐条说明为什么亮",
  "trends": "趋势与联系：共同趋势、与近期/经典研究的呼应、值得注意的方向"
}}
"""


def _digest(items: list[dict]) -> str:
    lines = []
    for it in items:
        summ = it["summary"]
        title = summ.title_zh if summ else it["paper"].title
        tldr = summ.tldr if summ else ""
        sc = it["score"]
        lines.append(f"- [{sc.layer}] {title}（标签：{', '.join(sc.tags)}）{tldr}")
    return "\n".join(lines)


def make_daily_review(date: str, items: list[dict], llm: LLM) -> DailyReview:
    if not items:
        return DailyReview(date=date, overview="今日无新文献。", highlights="—", trends="—")
    user = _USER_TMPL.format(date=date, digest=_digest(items))
    text = llm.complete(model=tier_model("synth"), system=_SYSTEM, user=user)
    try:
        d = extract_json(text)
        return DailyReview(
            date=date,
            overview=str(d.get("overview", "")),
            highlights=str(d.get("highlights", "")),
            trends=str(d.get("trends", "")),
        )
    except (ValueError, TypeError):
        return DailyReview(date=date, overview=f"今日收录 {len(items)} 篇。",
                           highlights="（综述生成失败）", trends="—")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_daily_review.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/gdr/daily_review.py tests/test_daily_review.py
git commit -m "feat: add daily overview review stage"
```

---

## Task 11: JSON store

**Files:**
- Create: `src/gdr/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `gdr.models.DayData`
- Produces: `Store(root: Path)` with:
  - `save_day(day: DayData) -> None` → writes `data/daily/<date>.json`
  - `load_day(date: str) -> DayData` → reads it back
  - `list_days() -> list[str]` → sorted (desc) list of dates that have files
  - `mark_seen_papers(ids: list[str]) -> list[str]` → records ids in `data/seen-index.json`, returns the subset that were NOT previously seen (so the pipeline can detect new papers). Idempotent within a run.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_store.py
from gdr.models import Paper, RelevanceScore, PaperSummary, DailyReview, DayData
from gdr.store import Store

def _day(date):
    p = Paper(id="arxiv:1", source="arxiv", title="t", authors=[], abstract="",
              categories=[], published=date, url="")
    return DayData(date=date,
                   review=DailyReview(date=date, overview="o", highlights="h", trends="t"),
                   items=[{"paper": p,
                           "score": RelevanceScore(score=90, tags=["GRB"], layer="core", reason=""),
                           "summary": PaperSummary(paper_id="arxiv:1", title_zh="标题", team="",
                                                   tldr="", review="", highlight="", relation="")}])

def test_save_and_load_day(tmp_path):
    st = Store(tmp_path)
    st.save_day(_day("2026-07-18"))
    back = st.load_day("2026-07-18")
    assert back.review.overview == "o"
    assert back.items[0]["summary"].title_zh == "标题"

def test_list_days_desc(tmp_path):
    st = Store(tmp_path)
    st.save_day(_day("2026-07-17"))
    st.save_day(_day("2026-07-18"))
    assert st.list_days() == ["2026-07-18", "2026-07-17"]

def test_mark_seen_returns_new_only(tmp_path):
    st = Store(tmp_path)
    assert st.mark_seen_papers(["arxiv:1", "arxiv:2"]) == ["arxiv:1", "arxiv:2"]
    assert st.mark_seen_papers(["arxiv:2", "arxiv:3"]) == ["arxiv:3"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_store.py -v`
Expected: FAIL (ModuleNotFoundError: gdr.store)

- [ ] **Step 3: Write `src/gdr/store.py`**

```python
# src/gdr/store.py
import json
from pathlib import Path
from gdr.models import DayData


class Store:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.daily_dir = self.root / "daily"
        self.seen_path = self.root / "seen-index.json"
        self.daily_dir.mkdir(parents=True, exist_ok=True)

    def save_day(self, day: DayData) -> None:
        path = self.daily_dir / f"{day.date}.json"
        path.write_text(json.dumps(day.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def load_day(self, date: str) -> DayData:
        path = self.daily_dir / f"{date}.json"
        return DayData.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def list_days(self) -> list[str]:
        return sorted((p.stem for p in self.daily_dir.glob("*.json")), reverse=True)

    def _load_seen(self) -> set[str]:
        if self.seen_path.exists():
            return set(json.loads(self.seen_path.read_text(encoding="utf-8")))
        return set()

    def mark_seen_papers(self, ids: list[str]) -> list[str]:
        seen = self._load_seen()
        new = [i for i in ids if i not in seen]
        seen.update(ids)
        self.seen_path.write_text(json.dumps(sorted(seen), ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        return new
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_store.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/gdr/store.py tests/test_store.py
git commit -m "feat: add json store with seen-index"
```

---

## Task 12: Static site rendering

**Files:**
- Create: `src/gdr/render.py`, `templates/base.html`, `templates/index.html`, `templates/day.html`, `templates/archive.html`, `static/style.css`, `static/search.js`
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: `gdr.store.Store`, `gdr.models.DayData`
- Produces: `render_site(store: Store, out_dir: Path, templates_dir: Path, static_dir: Path) -> None` — renders the latest day as `index.html`, each day as `day/<date>.html`, an `archive.html` listing all days, and copies `static/` into `out_dir/static/`. Uses Jinja2 with autoescaping. Items are ordered core → related → edge, and within a layer by descending score.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_render.py
from pathlib import Path
from gdr.models import Paper, RelevanceScore, PaperSummary, DailyReview, DayData
from gdr.store import Store
from gdr.render import render_site

TEMPLATES = Path(__file__).parent.parent / "templates"
STATIC = Path(__file__).parent.parent / "static"

def _item(pid, score, layer, title_zh):
    p = Paper(id=pid, source="arxiv", title="t", authors=["A"], abstract="",
              categories=["astro-ph.HE"], published="2026-07-18",
              url=f"https://arxiv.org/abs/{pid}")
    return {"paper": p,
            "score": RelevanceScore(score=score, tags=["GRB"], layer=layer, reason=""),
            "summary": PaperSummary(paper_id=pid, title_zh=title_zh, team="A 等",
                                    tldr="核心", review="综述", highlight="亮点", relation="—")}

def test_render_site(tmp_path):
    st = Store(tmp_path / "data")
    day = DayData(date="2026-07-18",
                  review=DailyReview(date="2026-07-18", overview="今日概览", highlights="H", trends="T"),
                  items=[_item("2607.2", 50, "related", "相关文章"),
                         _item("2607.1", 95, "core", "核心文章")])
    st.save_day(day)
    out = tmp_path / "site"
    render_site(st, out, TEMPLATES, STATIC)

    index = (out / "index.html").read_text(encoding="utf-8")
    assert "今日概览" in index
    # core sorts before related
    assert index.index("核心文章") < index.index("相关文章")
    assert (out / "day" / "2026-07-18.html").exists()
    assert (out / "archive.html").exists()
    assert (out / "static" / "style.css").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_render.py -v`
Expected: FAIL (ModuleNotFoundError: gdr.render)

- [ ] **Step 3: Write the templates and static assets**

```html
<!-- templates/base.html -->
<!doctype html>
<html lang="zh">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}GECAM 每日文献综述{% endblock %}</title>
  <link rel="stylesheet" href="{{ static_prefix }}static/style.css">
</head>
<body>
  <header><a href="{{ static_prefix }}index.html"><h1>GECAM 每日文献综述</h1></a>
    <nav><a href="{{ static_prefix }}archive.html">归档</a></nav></header>
  <main>{% block content %}{% endblock %}</main>
  <footer>自动生成 · GECAM Daily Review</footer>
</body>
</html>
```

```html
<!-- templates/day.html -->
{% extends "base.html" %}
{% block title %}{{ day.date }} · GECAM 每日文献综述{% endblock %}
{% block content %}
<section class="review">
  <h2>{{ day.date }} 当日总览</h2>
  <h3>今日概览</h3><p>{{ day.review.overview }}</p>
  <h3>今日亮点</h3><p>{{ day.review.highlights }}</p>
  <h3>趋势与联系</h3><p>{{ day.review.trends }}</p>
</section>
<section class="papers">
  {% for it in items %}
  <article class="card {{ it.score.layer }}">
    <div class="tags">
      <span class="layer">{{ it.score.layer }}</span>
      <span class="score">相关性 {{ it.score.score }}</span>
      {% for t in it.score.tags %}<span class="tag">{{ t }}</span>{% endfor %}
    </div>
    <h3>{{ it.summary.title_zh }}</h3>
    <p class="orig">{{ it.paper.title }}</p>
    <p class="team">{{ it.summary.team }}</p>
    <p class="tldr"><b>TL;DR：</b>{{ it.summary.tldr }}</p>
    <p class="body">{{ it.summary.review }}</p>
    <p class="highlight"><b>亮点：</b>{{ it.summary.highlight }}</p>
    <p class="relation"><b>与我们的关联：</b>{{ it.summary.relation }}</p>
    <p class="links"><a href="{{ it.paper.url }}" target="_blank" rel="noopener">arXiv</a></p>
  </article>
  {% endfor %}
</section>
{% endblock %}
```

```html
<!-- templates/index.html -->
{% extends "day.html" %}
```

```html
<!-- templates/archive.html -->
{% extends "base.html" %}
{% block title %}归档 · GECAM 每日文献综述{% endblock %}
{% block content %}
<h2>归档</h2>
<ul class="archive">
  {% for d in days %}<li><a href="{{ static_prefix }}day/{{ d }}.html">{{ d }}</a></li>{% endfor %}
</ul>
{% endblock %}
```

```css
/* static/style.css */
:root { color-scheme: light dark; }
body { font-family: system-ui, sans-serif; max-width: 860px; margin: 0 auto; padding: 1rem; line-height: 1.6; }
header a { text-decoration: none; color: inherit; }
.card { border: 1px solid #8884; border-radius: 8px; padding: 1rem; margin: 1rem 0; }
.card.core { border-left: 4px solid #d33; }
.card.related { border-left: 4px solid #39c; }
.card.edge { opacity: .8; border-left: 4px solid #999; }
.tags span { display: inline-block; font-size: .75rem; background: #8882; border-radius: 4px; padding: .1rem .4rem; margin-right: .3rem; }
.orig { color: #888; font-size: .85rem; }
```

```javascript
// static/search.js
// Phase 1 placeholder for client-side search (wired up in a later phase).
```

- [ ] **Step 4: Write `src/gdr/render.py`**

```python
# src/gdr/render.py
import shutil
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from gdr.store import Store
from gdr.models import DayData

_LAYER_ORDER = {"core": 0, "related": 1, "edge": 2}


def _ordered_items(day: DayData) -> list[dict]:
    return sorted(day.items, key=lambda it: (_LAYER_ORDER.get(it["score"].layer, 9),
                                             -it["score"].score))


def render_site(store: Store, out_dir: Path, templates_dir: Path, static_dir: Path) -> None:
    out_dir = Path(out_dir)
    (out_dir / "day").mkdir(parents=True, exist_ok=True)
    env = Environment(loader=FileSystemLoader(str(templates_dir)),
                      autoescape=select_autoescape(["html"]))
    days = store.list_days()

    day_tmpl = env.get_template("day.html")
    index_tmpl = env.get_template("index.html")
    archive_tmpl = env.get_template("archive.html")

    for i, date in enumerate(days):
        day = store.load_day(date)
        items = _ordered_items(day)
        html = day_tmpl.render(day=day, items=items, static_prefix="../")
        (out_dir / "day" / f"{date}.html").write_text(html, encoding="utf-8")
        if i == 0:
            idx = index_tmpl.render(day=day, items=items, static_prefix="")
            (out_dir / "index.html").write_text(idx, encoding="utf-8")

    (out_dir / "archive.html").write_text(
        archive_tmpl.render(days=days, static_prefix=""), encoding="utf-8")

    dst_static = out_dir / "static"
    if dst_static.exists():
        shutil.rmtree(dst_static)
    shutil.copytree(static_dir, dst_static)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_render.py -v`
Expected: PASS (1 test)

- [ ] **Step 6: Commit**

```bash
git add src/gdr/render.py templates static tests/test_render.py
git commit -m "feat: add jinja2 static site rendering"
```

---

## Task 13: Pipeline orchestration + CLI

**Files:**
- Create: `src/gdr/pipeline.py`, `scripts/run_daily.py`, `scripts/list_models.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `run(date, source, llm, store) -> DayData` executing stages: fetch → dedupe → mark_seen (keep only new papers) → score each → for core/related fetch full text + summarize (edge summarized only if `config.SUMMARIZE_EDGE`) → make_daily_review → save_day → return the DayData. `fetch_fulltext` is injectable (default the real one) so the pipeline test stays offline.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline.py
import json
from gdr.models import Paper
from gdr.sources.base import Source
from gdr.store import Store
from gdr.pipeline import run

class StubSource(Source):
    def __init__(self, papers): self._papers = papers
    def fetch(self, date): return list(self._papers)

def _paper(pid, title):
    return Paper(id=pid, source="arxiv", title=title, authors=["A"], abstract="abstract",
                 categories=["astro-ph.HE"], published="2026-07-18",
                 url=f"https://arxiv.org/abs/{pid}")

def test_pipeline_end_to_end(tmp_path, fake_llm_factory):
    # relevance (keyed by profile phrase), summary (keyed by 综述卡片), daily (keyed by 当日总览)
    llm = fake_llm_factory({
        "GECAM": json.dumps({"score": 90, "tags": ["GRB"], "reason": "核心"}),
        "综述卡片": json.dumps({"title_zh": "标题", "team": "A 等", "tldr": "t",
                              "review": "r", "highlight": "h", "relation": "—"}),
        "当日总览": json.dumps({"overview": "今日 1 篇", "highlights": "H", "trends": "T"}),
    })
    store = Store(tmp_path / "data")
    src = StubSource([_paper("2607.1", "GRB paper"), _paper("2607.1", "GRB paper")])  # dup
    day = run("2026-07-18", src, llm, store, fetch_fulltext=lambda p, **k: "BODY")
    assert len(day.items) == 1                     # deduped
    assert day.items[0]["summary"].title_zh == "标题"
    assert day.review.overview == "今日 1 篇"
    assert store.load_day("2026-07-18").items[0]["score"].layer == "core"

def test_pipeline_skips_already_seen(tmp_path, fake_llm_factory):
    llm = fake_llm_factory({
        "GECAM": json.dumps({"score": 90, "tags": [], "reason": ""}),
        "综述卡片": json.dumps({"title_zh": "x", "team": "", "tldr": "", "review": "",
                              "highlight": "", "relation": ""}),
        "当日总览": json.dumps({"overview": "o", "highlights": "", "trends": ""}),
    })
    store = Store(tmp_path / "data")
    store.mark_seen_papers(["arxiv:2607.1"])       # pre-seen
    src = StubSource([_paper("2607.1", "GRB paper")])
    day = run("2026-07-18", src, llm, store, fetch_fulltext=lambda p, **k: "BODY")
    assert day.items == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline.py -v`
Expected: FAIL (ModuleNotFoundError: gdr.pipeline)

- [ ] **Step 3: Write `src/gdr/pipeline.py`**

```python
# src/gdr/pipeline.py
from gdr import config
from gdr.dedup import dedupe
from gdr.fulltext import fetch_fulltext as _real_fetch_fulltext
from gdr.relevance import score_paper
from gdr.summarize import summarize_paper
from gdr.daily_review import make_daily_review
from gdr.models import DayData
from gdr.store import Store


def run(date, source, llm, store: Store, fetch_fulltext=_real_fetch_fulltext) -> DayData:
    papers = dedupe(source.fetch(date))
    new_ids = set(store.mark_seen_papers([p.id for p in papers]))
    papers = [p for p in papers if p.id in new_ids]

    items = []
    for paper in papers:
        score = score_paper(paper, llm)
        summary = None
        if score.layer in ("core", "related") or config.SUMMARIZE_EDGE:
            fulltext = fetch_fulltext(paper)
            summary = summarize_paper(paper, fulltext, llm)
        items.append({"paper": paper, "score": score, "summary": summary})

    review = make_daily_review(date, [it for it in items if it["summary"]], llm)
    day = DayData(date=date, review=review, items=items)
    store.save_day(day)
    return day
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Write the CLI entry points**

```python
# scripts/run_daily.py
import argparse
import datetime as dt
from pathlib import Path
from gdr import config
from gdr.llm import OpenCodeLLM
from gdr.sources.arxiv_source import ArxivSource
from gdr.store import Store
from gdr.pipeline import run
from gdr.render import render_site

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (default: yesterday UTC)")
    args = ap.parse_args()
    date = args.date or (dt.datetime.utcnow().date() - dt.timedelta(days=1)).isoformat()

    llm = OpenCodeLLM(api_key=config.get_api_key())
    source = ArxivSource(categories=config.ARXIV_CATEGORIES)
    store = Store(ROOT / "data")

    day = run(date, source, llm, store)
    print(f"{date}: {len(day.items)} papers")
    render_site(store, ROOT / "site", ROOT / "templates", ROOT / "static")


if __name__ == "__main__":
    main()
```

```python
# scripts/list_models.py
"""Print the model ids opencode go exposes, to confirm config model ids."""
import requests
from gdr import config

resp = requests.get(f"{config.OPENCODE_BASE_URL}/models",
                    headers={"Authorization": f"Bearer {config.get_api_key()}"}, timeout=30)
resp.raise_for_status()
for m in resp.json().get("data", []):
    print(m.get("id"))
```

- [ ] **Step 6: Commit**

```bash
git add src/gdr/pipeline.py scripts/run_daily.py scripts/list_models.py tests/test_pipeline.py
git commit -m "feat: add pipeline orchestration and cli entry points"
```

---

## Task 14: GitHub Actions daily workflow + README

**Files:**
- Create: `.github/workflows/daily.yml`, `README.md`
- Test: manual verification (documented below) — no unit test; a scheduled workflow cannot be unit-tested.

**Interfaces:**
- Consumes: `scripts/run_daily.py`
- Produces: a daily-scheduled + manually-dispatchable workflow that runs the pipeline, commits `data/`, and deploys `site/` to GitHub Pages.

- [ ] **Step 1: Write `.github/workflows/daily.yml`**

```yaml
name: daily-review
on:
  schedule:
    - cron: "0 2 * * *"   # 02:00 UTC = 10:00 Beijing
  workflow_dispatch: {}

permissions:
  contents: write
  pages: write
  id-token: write

concurrency:
  group: daily-review
  cancel-in-progress: false

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -e ".[dev]"
      - run: pytest -q
      - name: Run daily pipeline
        env:
          OPENCODE_API_KEY: ${{ secrets.OPENCODE_API_KEY }}
        run: python scripts/run_daily.py
      - name: Commit data
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data
          git commit -m "data: daily update $(date -u +%F)" || echo "no changes"
          git push
      - uses: actions/upload-pages-artifact@v3
        with:
          path: site
  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - id: deployment
        uses: actions/deploy-pages@v4
```

- [ ] **Step 2: Write `README.md`**

````markdown
# GECAM Daily Review

每天自动抓取 arXiv 新文献，按 GECAM 科学画像打分、综述，并发布静态站。

## 本地运行

```bash
pip install -e ".[dev]"
export OPENCODE_API_KEY=sk-...
python scripts/list_models.py          # 确认模型 id，如与默认不符用 GDR_MODEL_* 环境变量覆盖
python scripts/run_daily.py --date 2026-07-17
open site/index.html
```

## 测试

```bash
pytest -q
```

## 部署

- 仓库 Settings → Pages → Source 选 **GitHub Actions**。
- 仓库 Settings → Secrets and variables → Actions 新增 `OPENCODE_API_KEY`。
- `.github/workflows/daily.yml` 每天 02:00 UTC（北京 10:00）自动运行，也可在 Actions 页手动 `Run workflow`。

## 架构

见 `docs/superpowers/specs/2026-07-18-gecam-daily-review-design.md`。数据 JSON 提交进 `data/`；渲染 HTML 作为 Pages 构件部署，不进 git。
````

- [ ] **Step 3: Manual verification**

Run locally to confirm the end-to-end path before relying on the schedule:
```bash
export OPENCODE_API_KEY=sk-...
python scripts/list_models.py     # confirm/adjust model ids
python scripts/run_daily.py --date <a recent weekday>
```
Expected: `data/daily/<date>.json` created, `site/index.html` renders cards, console prints the paper count. Then push to GitHub, add the `OPENCODE_API_KEY` secret, set Pages source to "GitHub Actions", and use **Run workflow** to confirm the Action succeeds and the Pages URL serves the site.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/daily.yml README.md
git commit -m "ci: add daily workflow and readme"
```

---

## Self-Review Notes (author checklist — completed)

- **Spec coverage:**
  - §4 arXiv source → Task 5; pluggable `Source` ABC → Task 5. (ADS/journal deferred per Global Constraints.)
  - §5 GECAM profile → Task 1 (`GECAM_PROFILE`), used in Task 7.
  - §6 pipeline stages 0/1/2/2.5/3/5/6 → Tasks 5/6/7/8/9/10/12, orchestrated in Task 13. (Stage 4 entity building deferred to Phase 2.)
  - §7.1 per-paper card fields → Task 9 + Task 12 template. §7.2 daily overview fields → Task 10 + template. (§7.3/§7.4 author/team deferred.)
  - §8 storage (papers/daily/seen-index) → Task 11. (authors/teams files deferred.)
  - §9 site (index/archive/day + client search stub) → Task 12.
  - §10 tech stack → pyproject (Task 1), Jinja2 (Task 12).
  - §11 model tiers → config (Task 1) + `tier_model` (Task 4); full-text token control via `FULLTEXT_MAX_CHARS` (Task 8).
  - §13 secrets via env / Actions secret → Task 1 (`get_api_key`), Task 14 (workflow env).
  - §15 Actions cron 02:00 UTC + Pages → Task 14.
  - §16 Phase 1 boundary → Global Constraints "Deferred" list.
- **Placeholder scan:** the only intentional stub is `static/search.js` (Phase-1 no-op, documented); model ids have real defaults + a confirmation script (`list_models.py`). No TBD/TODO code steps.
- **Type consistency:** `Paper`/`RelevanceScore`/`PaperSummary`/`DailyReview`/`DayData` field names are consistent across Tasks 2/5/7/9/10/11/12/13; `LLM.complete(model, system, user, temperature)` signature consistent across Tasks 4/7/9/10 and the `FakeLLM`; `Source.fetch(date)` consistent across Tasks 5/13; `Store` method names consistent across Tasks 11/12/13; `tier_model` tiers ("triage"/"write"/"synth") consistent across Tasks 4/7/9/10.
```
