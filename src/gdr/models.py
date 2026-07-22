from __future__ import annotations

from dataclasses import asdict, dataclass, field


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
    # Cross-source identifiers, stored without their prefixes where practical,
    # e.g. {"arxiv": "2607.00001", "ads": "2026ApJ...", "doi": "10..."}.
    # Keeping these alongside the canonical `id` lets arXiv and ADS records merge
    # without changing the IDs already persisted in daily JSON files.
    external_ids: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Paper:
        return cls(**d)


@dataclass
class RelevanceScore:
    score: int
    tags: list[str]
    layer: str
    reason: str
    relation: str = ""
    core_path: str = ""
    evidence: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> RelevanceScore:
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
    authors_en: str = ""        # first ~3 authors + affiliations, English, from full text
    corresponding_en: str = ""   # corresponding author, English, from full text
    context_outlook: str = ""    # 脉络与展望: past-connection → future-trend, with inline [[cite]] markers
    citations: list[dict] = field(default_factory=list)  # [{label, arxiv, doi}] for the [[cite]] chips

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> PaperSummary:
        return cls(**d)


@dataclass
class DailyReview:
    date: str
    overview: str
    highlights: str
    trends: str
    headline_level: str = ""
    headline: str = ""
    headline_paper_id: str = ""
    headline_reason: str = ""
    developments: list[dict] = field(default_factory=list)
    watchlist: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> DailyReview:
        return cls(**d)


@dataclass
class DayData:
    date: str
    review: DailyReview
    items: list[dict]  # {"paper": Paper, "score": RelevanceScore, "summary": PaperSummary | None}
    revisions: list[dict] = field(default_factory=list)

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
            "revisions": self.revisions,
        }

    @classmethod
    def from_dict(cls, d: dict) -> DayData:
        items = [
            {
                "paper": Paper.from_dict(it["paper"]),
                "score": RelevanceScore.from_dict(it["score"]),
                "summary": PaperSummary.from_dict(it["summary"]) if it.get("summary") else None,
            }
            for it in d["items"]
        ]
        return cls(date=d["date"], review=DailyReview.from_dict(d["review"]), items=items, revisions=d.get("revisions", []))
