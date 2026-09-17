"""The entry script's failure contract: publish what survived, then go red."""
import importlib.util
import sys
from pathlib import Path

import pytest

from gdr.pipeline import PartialFailure


def _load_run_daily():
    spec = importlib.util.spec_from_file_location(
        "run_daily_under_test", Path("scripts/run_daily.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _stub_everything(monkeypatch, module, sync_impl):
    monkeypatch.setattr(sys, "argv", ["run_daily.py", "--date", "2026-09-16"])
    monkeypatch.setattr(module, "make_llm", lambda *a, **k: object())
    monkeypatch.setattr(module, "Store", lambda path: object())
    monkeypatch.setattr(module, "repair_decisions", lambda *a, **k: None)
    monkeypatch.setattr(module, "sync", sync_impl)


def test_a_partial_outage_still_renders_the_site_then_exits_nonzero(monkeypatch):
    # The whole point of raising after the data is durable: the survivors must
    # still reach the site and the commit, and the run must still end red.
    module = _load_run_daily()
    built = []

    def failing_sync(*a, **k):
        raise PartialFailure(10, 6, RuntimeError("boom"), ["2026-09-16"])

    _stub_everything(monkeypatch, module, failing_sync)
    monkeypatch.setattr(module, "build_site", lambda root: built.append(root))

    with pytest.raises(SystemExit) as caught:
        module.main()

    assert caught.value.code == 1
    assert built, "the site must still be rendered from the survivors"


def test_a_clean_run_exits_zero(monkeypatch):
    module = _load_run_daily()
    built = []
    _stub_everything(monkeypatch, module, lambda *a, **k: ["2026-09-16"])
    monkeypatch.setattr(module, "build_site", lambda root: built.append(root))

    module.main()

    assert built
