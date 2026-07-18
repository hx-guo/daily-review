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
