from abc import ABC, abstractmethod
from gdr.models import Paper


class Source(ABC):
    @abstractmethod
    def fetch(self, date: str) -> list[Paper]:
        """Return papers announced/published on `date` (YYYY-MM-DD)."""
        raise NotImplementedError

    @abstractmethod
    def fetch_recent(self, end_date: str, days: int) -> list[Paper]:
        """Return papers whose published date is within [end_date-(days-1), end_date]."""
        raise NotImplementedError
