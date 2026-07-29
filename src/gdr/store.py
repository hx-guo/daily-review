import json
from pathlib import Path
from gdr.dedup import paper_keys
from gdr.models import DayData, IngestDay


_SEEN_IDENTITY_SCHEMA = "schema:paper-identities-v1"


class Store:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.daily_dir = self.root / "daily"
        self.ingest_dir = self.root / "ingest"
        self.seen_path = self.root / "seen-index.json"
        self.daily_dir.mkdir(parents=True, exist_ok=True)
        self.ingest_dir.mkdir(parents=True, exist_ok=True)

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

    # ---- seen index ------------------------------------------------------------

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

    def mark_seen_papers(self, ids: list[str]) -> list[str]:
        raw = self._load_seen_raw()
        new = [i for i in ids if i not in raw]
        for i in ids:
            raw.setdefault(i, "")
        self._write_seen(raw)
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
        keeps the potentially expensive daily-JSON scan strictly one-time. Merges
        new aliases into the existing {key: ingest date} mapping rather than
        rebuilding it as a flat list, so dates already recorded via `mark_seen`
        are preserved.
        """
        raw = self._load_seen_raw()
        if _SEEN_IDENTITY_SCHEMA in raw:
            return
        for date in self.list_days():
            try:
                day = self.load_day(date)
            except (OSError, ValueError, TypeError, KeyError):
                continue
            for item in day.items:
                for key in paper_keys(item["paper"]):
                    raw.setdefault(key, "")
        raw[_SEEN_IDENTITY_SCHEMA] = ""
        self._write_seen(raw)
