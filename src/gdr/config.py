import os

OPENCODE_BASE_URL = os.environ.get("OPENCODE_BASE_URL", "https://opencode.ai/zen/go/v1")

ARXIV_CATEGORIES = ["astro-ph.HE", "gr-qc", "astro-ph.SR", "astro-ph.CO"]

# Model tiers. Defaults are display-name-derived; confirm exact ids via scripts/list_models.py.
MODEL_TRIAGE = os.environ.get("GDR_MODEL_TRIAGE", "deepseek-v4-flash")
MODEL_WRITE = os.environ.get("GDR_MODEL_WRITE", "deepseek-v4-pro")
MODEL_SYNTH = os.environ.get("GDR_MODEL_SYNTH", "kimi-k3")

LAYER_CORE_MIN = 70
LAYER_RELATED_MIN = 40
SUMMARIZE_EDGE = False

# Max characters of full text sent to the write model (token control).
FULLTEXT_MAX_CHARS = 24000

GECAM_PROFILE = """GECAM（引力波高能电磁对应体全天监测器）团队关注的科学范围，分三层：

核心主题（直接科学目标）：
- 伽马暴 GRB（长/短暴、prompt/余辉、能谱、jet、宿主）
- 引力波电磁对应体（BNS/NSBH 并合、kilonova、GW170817-like、O4/O5 后随观测）
- 磁星 / 软伽马重复暴 SGR（巨耀发、暴发、SGR 1935+2154）
- 快速射电暴 FRB（尤其高能对应体、FRB–磁星联系）
- 多信使触发与联合（LIGO/Virgo/KAGRA 引力波、IceCube 中微子）

相关主题（高能暂现源大类 + 相关任务）：
- 高能暂现天体：TDE、X/γ 射线暂现、新星/超新星激波、中子星/黑洞暂现现象
- 太阳耀斑、硬 X 射线爆发、地球伽马闪 TGF
- 相关任务：Fermi/GBM、Swift、HXMT/Insight、Einstein Probe、SVOM、Integral、Konus-Wind、GECAM

边缘主题（相关度低但不丢弃）：
- astro-ph.HE 内其余物理（宇宙线、暗物质、AGN 稳态物理等）
"""


def get_api_key() -> str:
    key = os.environ.get("OPENCODE_API_KEY")
    if not key:
        raise RuntimeError("OPENCODE_API_KEY environment variable is not set")
    return key


def layer_for(score: int) -> str:
    if score >= LAYER_CORE_MIN:
        return "core"
    if score >= LAYER_RELATED_MIN:
        return "related"
    return "edge"
