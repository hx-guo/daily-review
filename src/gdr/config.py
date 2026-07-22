import os

OPENCODE_BASE_URL = os.environ.get("OPENCODE_BASE_URL", "https://opencode.ai/zen/go/v1")

ARXIV_CATEGORIES = ["astro-ph.HE", "gr-qc", "astro-ph.SR", "astro-ph.CO"]

# ADS is the published-journal complement to arXiv. `entdate` is added by
# ADSSource at request time; this base query stays configurable so a deployment
# can widen or narrow its subject coverage without a code change. Requiring a
# topic match is intentional: selecting whole journals made the first ADS run
# ingest hundreds of unrelated papers from batch-indexed issues.
_ADS_TOPICS = (
    'abs:("gamma-ray burst" OR GRB OR magnetar OR "soft gamma repeater" OR '
    '"fast radio burst" OR FRB OR "gravitational wave" OR kilonova OR '
    '"neutron star merger" OR "black hole neutron star" OR "multi-messenger" OR '
    'neutrino OR "tidal disruption event" OR "X-ray transient" OR '
    '"gamma-ray transient" OR "solar flare" OR "terrestrial gamma-ray flash" OR '
    '"X-ray binary" OR GECAM OR "Insight-HXMT" OR SVOM OR "Einstein Probe" OR '
    '"Fermi GBM" OR Swift OR NICER)'
)
ADS_INGEST_QUERY = os.environ.get(
    "GDR_ADS_QUERY",
    f"database:astronomy property:refereed doctype:article {_ADS_TOPICS}",
)

# Model tiers. Defaults are display-name-derived; confirm exact ids via scripts/list_models.py.
MODEL_TRIAGE = os.environ.get("GDR_MODEL_TRIAGE", "deepseek-v4-flash")
MODEL_WRITE = os.environ.get("GDR_MODEL_WRITE", "deepseek-v4-pro")
# synth: glm-5.2 — kimi-k3 was persistently 400-ing on opencode's upstream (2026-07-18).
MODEL_SYNTH = os.environ.get("GDR_MODEL_SYNTH", "glm-5.2")

LAYER_CORE_MIN = 70
LAYER_RELATED_MIN = 40

# Max characters of full text sent to the write model. Set high enough to read a
# whole paper (a typical arXiv paper is ~60-100k chars; the reference list — needed
# for citation resolution — sits at the very end). Only a pathologically long paper
# is truncated here, and summarize_paper retries with a short body if the model ever
# rejects an over-long input. ~150k chars ≈ ~38k tokens.
FULLTEXT_MAX_CHARS = int(os.environ.get("GDR_FULLTEXT_MAX_CHARS", "150000"))
# Fallback body length used when a full-text write call errors (e.g. context overflow).
FULLTEXT_RETRY_CHARS = int(os.environ.get("GDR_FULLTEXT_RETRY_CHARS", "24000"))

# Citation link resolution. ADS is the primary resolver (astro-specialised, returns
# bibcode + arXiv + DOI); Crossref is the token-free fallback. Both are optional — with
# neither reachable, citation chips fall back to an ADS search of the reference string.
ADS_API_URL = os.environ.get("ADS_API_URL", "https://api.adsabs.harvard.edu/v1/search/query")
CROSSREF_API_URL = os.environ.get("CROSSREF_API_URL", "https://api.crossref.org/works")
CROSSREF_MAILTO = os.environ.get("GDR_CROSSREF_MAILTO", "daily-review@users.noreply.github.com")

FETCH_WINDOW_DAYS = int(os.environ.get("GDR_FETCH_WINDOW_DAYS", "7"))
ARXIV_PAGE_SIZE = int(os.environ.get("GDR_ARXIV_PAGE_SIZE", "100"))
ADS_PAGE_SIZE = int(os.environ.get("GDR_ADS_PAGE_SIZE", "200"))
MAX_CONCURRENCY = int(os.environ.get("GDR_MAX_CONCURRENCY", "6"))
# Editorial decisions are intentionally one-paper-per-call for stable, short
# JSON. Run them concurrently so large ADS days do not become serial bottlenecks.
EDITORIAL_MAX_CONCURRENCY = int(os.environ.get("GDR_EDITORIAL_MAX_CONCURRENCY", "6"))
# arXiv asks for ~3s between API requests; pagination sleeps this long between pages.
ARXIV_REQUEST_DELAY = float(os.environ.get("GDR_ARXIV_REQUEST_DELAY", "3"))
ADS_REQUEST_DELAY = float(os.environ.get("GDR_ADS_REQUEST_DELAY", "0.5"))

TEAM_PROFILE = """高能暂现源研究团队（同时参与 GECAM、Insight-HXMT、SVOM 等高能天文任务）的科学关注范围如下。

科学与观测赛道（这些是主题标签，不预设核心/相关层级）：
- 伽马暴 GRB（长/短暴、prompt/余辉、能谱、jet、宿主、高红移、GRB 宇宙学）
- 引力波电磁对应体（BNS/NSBH 并合、kilonova、GW170817-like、O4/O5 后随观测）
- 磁星 / 软伽马重复暴 SGR（巨耀发、暴发、SGR 1935+2154）
- 快速射电暴 FRB（尤其高能对应体、FRB–磁星联系）
- 多信使触发与联合（LIGO/Virgo/KAGRA 引力波、IceCube 中微子）
- X 射线双星与吸积致密天体（黑洞/中子星吸积、X 射线暂现与暴发、吸积毫秒脉冲星、QPO、X 射线定时与能谱）
- 高能暂现天体：TDE、X/γ 射线暂现、新星/超新星激波、中子星/黑洞暂现现象
- 太阳耀斑、硬 X 射线爆发、地球伽马闪 TGF
- 由暂现源样本驱动的总体统计、宇宙学与基础物理应用

任务与能力赛道：
- GECAM、Insight-HXMT、SVOM、Fermi/GBM、Swift、Einstein Probe、Integral、Konus-Wind、NICER 等任务
- 直接服务上述科学目标的触发、后随、标定、分类、定位、时域分析、能谱分析、数据产品与方法

归类原则：TDE、太阳耀斑、任务方法、引力波/中微子/FRB 宇宙学等任何赛道都可能是核心；
层级取决于论文主要问题与团队目标的直接程度，而不是主题名称。仅在背景中提及关键词、仅把相关天体
当作通用方法示例，或与暂现/任务目标没有实质联系的 astro-ph.HE 论文属于边缘关注。
"""


def get_api_key() -> str:
    key = os.environ.get("OPENCODE_API_KEY")
    if not key:
        raise RuntimeError("OPENCODE_API_KEY environment variable is not set")
    return key


def get_ads_token() -> str:
    """ADS API token for citation resolution. Optional — empty when unset, in which
    case resolution skips ADS and relies on Crossref / search-link fallback."""
    return os.environ.get("ADS_API_TOKEN", "").strip()


def layer_for(score: int) -> str:
    if score >= LAYER_CORE_MIN:
        return "core"
    if score >= LAYER_RELATED_MIN:
        return "related"
    return "edge"
