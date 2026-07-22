from __future__ import annotations

import shutil
from pathlib import Path

from gdr.render import render_site
from gdr.store import Store


def build_site(root: Path, out_dir: Path | None = None) -> Path:
    """Build a clean static site using only committed data and local assets."""
    root = Path(root)
    out_dir = Path(out_dir) if out_dir is not None else root / "site"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    render_site(
        Store(root / "data"),
        out_dir,
        root / "templates",
        root / "static",
    )
    return out_dir
