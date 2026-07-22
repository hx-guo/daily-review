import json
from pathlib import Path
from gdr.dedup import paper_keys
from gdr.models import DayData


_SEEN_IDENTITY_SCHEMA = "schema:paper-identities-v1"


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

    def load_day_or_none(self, date: str):
        path = self.daily_dir / f"{date}.json"
        if not path.exists():
            return None
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

    def unseen_ids(self, ids: list[str]) -> list[str]:
        seen = self._load_seen()
        return [i for i in ids if i not in seen]

    def identities_unseen(self, ids) -> bool:
        """True only when none of a paper's arXiv/ADS/DOI identities was seen."""
        return self._load_seen().isdisjoint(ids)

    def seen_identities(self) -> set[str]:
        """Return a snapshot so a batch can filter papers with one disk read."""
        return self._load_seen()

    def ensure_seen_identities(self) -> None:
        """One-time migration from the legacy primary-ID-only seen index.

        The ADS rollout needs DOI, linked arXiv ID, and normalized title aliases
        for papers already stored before `external_ids` existed. A schema marker
        keeps the potentially expensive daily-JSON scan strictly one-time.
        """
        seen = self._load_seen()
        if _SEEN_IDENTITY_SCHEMA in seen:
            return
        for date in self.list_days():
            try:
                day = self.load_day(date)
            except (OSError, ValueError, TypeError, KeyError):
                continue
            for item in day.items:
                seen.update(paper_keys(item["paper"]))
        seen.add(_SEEN_IDENTITY_SCHEMA)
        self.seen_path.write_text(json.dumps(sorted(seen), ensure_ascii=False, indent=2),
                                  encoding="utf-8")
