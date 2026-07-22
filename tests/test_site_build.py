import hashlib
import shutil
from pathlib import Path

from gdr.models import DailyReview, DayData
from gdr.site_build import build_site
from gdr.store import Store


ROOT = Path(__file__).parent.parent


def _manifest(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_build_site_is_clean_and_reproducible(tmp_path):
    shutil.copytree(ROOT / "templates", tmp_path / "templates")
    shutil.copytree(ROOT / "static", tmp_path / "static")
    Store(tmp_path / "data").save_day(
        DayData(
            date="2026-07-22",
            review=DailyReview("2026-07-22", "确定性构建", "", ""),
            items=[],
        )
    )

    out_dir = build_site(tmp_path)
    first = _manifest(out_dir)
    assert first

    (out_dir / "index.html").write_text("stale", encoding="utf-8")
    (out_dir / "obsolete.html").write_text("obsolete", encoding="utf-8")
    build_site(tmp_path)

    assert not (out_dir / "obsolete.html").exists()
    assert _manifest(out_dir) == first
