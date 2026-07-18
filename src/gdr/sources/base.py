from abc import ABC, abstractmethod
from gdr.models import Paper


class Source(ABC):
    @abstractmethod
    def fetch(self, date: str) -> list[Paper]:
        """Return papers announced/published on `date` (YYYY-MM-DD)."""
        raise NotImplementedError
