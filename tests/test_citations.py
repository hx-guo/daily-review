from gdr.citations import resolve_one, resolve_citations, _surname, _verify


class _Resp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload or {}
    def json(self):
        return self._payload


def _ads(bibcode, author, year, doi=None, arxiv=None):
    doc = {"bibcode": bibcode, "author": [author], "year": str(year)}
    if doi:
        doc["doi"] = [doi]
    if arxiv:
        doc["identifier"] = ["arXiv:" + arxiv]
    return _Resp(200, {"response": {"docs": [doc]}})


def _crossref(family, year, doi):
    return _Resp(200, {"message": {"items": [
        {"author": [{"family": family}], "issued": {"date-parts": [[year]]}, "DOI": doi}]}})


_EMPTY_ADS = _Resp(200, {"response": {"docs": []}})
_EMPTY_CR = _Resp(200, {"message": {"items": []}})


def _http(ads=None, crossref=None):
    def _get(url, **kw):
        if "adsabs" in url:
            return ads if ads is not None else _EMPTY_ADS
        if "crossref" in url:
            return crossref if crossref is not None else _EMPTY_CR
        return _Resp(404)
    return _get


def test_surname_and_verify():
    assert _surname("Illarionov, A. F.") == "illarionov"
    assert _surname("Shakura & Sunyaev") == "shakura"
    assert _surname("A. B. DeLaunay 2022") == "delaunay"
    assert _verify("gnarini", 2022, "gnarini", 2022)
    assert _verify("gnarini", 2022, "gnarini", 2023)      # ±1 tolerated
    assert not _verify("gnarini", 2022, "gnarini", 2025)  # year off by 3 -> reject
    assert not _verify("illarionov", 1975, "toropina", 2011)  # wrong author -> reject


def test_ads_hit_prefers_arxiv():
    cite = {"label": "Gnarini+ 2022", "authors": "Gnarini", "year": "2022",
            "title": "polarization", "ref": "Gnarini et al. 2022, MNRAS 514 2561"}
    out = resolve_one(cite, ads_token="tok",
                      http_get=_http(ads=_ads("2022MNRAS.514.2561G", "Gnarini, A.", 2022,
                                              doi="10.1093/mnras/stac1523", arxiv="2206.00749")))
    assert out["verified"] is True
    assert out["source"] == "ads"
    assert out["url"] == "https://arxiv.org/abs/2206.00749"


def test_ads_bibcode_only_link():
    cite = {"label": "Illarionov & Sunyaev 1975", "authors": "Illarionov", "year": "1975"}
    out = resolve_one(cite, ads_token="tok",
                      http_get=_http(ads=_ads("1975A&A....39..185I", "Illarionov, A. F.", 1975)))
    assert out["verified"] is True
    assert out["url"] == "https://ui.adsabs.harvard.edu/abs/1975A&A....39..185I"


def test_ads_mismatch_rejected_then_unresolved():
    # ADS returns a wrong paper (Toropina 2011) for Illarionov&Sunyaev 1975; verify rejects it,
    # Crossref (empty) also misses -> stays unresolved with url="".
    cite = {"label": "Illarionov & Sunyaev 1975", "authors": "Illarionov", "year": "1975",
            "ref": "Illarionov & Sunyaev 1975, A&A 39 185"}
    out = resolve_one(cite, ads_token="tok",
                      http_get=_http(ads=_ads("2011PoS...TOROPINA", "Toropina, O.", 2011)))
    assert out["verified"] is False
    assert out["url"] == ""


def test_crossref_fallback_when_no_ads_token():
    cite = {"label": "Anitra+ 2025", "authors": "Anitra", "year": "2025",
            "ref": "Anitra et al. 2025 A&A 697 A83"}
    out = resolve_one(cite, ads_token="",
                      http_get=_http(crossref=_crossref("Anitra", 2025, "10.1051/0004-6361/202554097")))
    assert out["verified"] is True
    assert out["source"] == "crossref"
    assert out["url"] == "https://doi.org/10.1051/0004-6361/202554097"


def test_resolve_citations_empty():
    assert resolve_citations([]) == []


def test_resolve_network_error_is_graceful():
    def _boom(url, **kw):
        raise RuntimeError("network down")
    out = resolve_one({"label": "X+ 2020", "authors": "X", "year": "2020"},
                      ads_token="tok", http_get=_boom)
    assert out["verified"] is False and out["url"] == ""
