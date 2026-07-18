from gdr import config
from gdr.jsonutil import extract_json
from gdr.llm import LLM, tier_model
from gdr.models import Paper, RelevanceScore

_SYSTEM = "你是天体物理文献筛选助手，只输出 JSON。"

_USER_TMPL = """下面是 GECAM 团队的科学关注范围：
{profile}

请判断这篇论文与上述范围的相关性，输出 JSON：
{{"score": 0-100 的整数, "tags": ["主题标签", ...], "reason": "一句话理由（中文）"}}
score 越高越相关；宁可给中间分也不要漏判边缘相关的论文。

标题：{title}
摘要：{abstract}
分类：{categories}
"""


def score_paper(paper: Paper, llm: LLM) -> RelevanceScore:
    user = _USER_TMPL.format(
        profile=config.GECAM_PROFILE,
        title=paper.title,
        abstract=paper.abstract,
        categories=", ".join(paper.categories),
    )
    text = llm.complete(model=tier_model("triage"), system=_SYSTEM, user=user)
    try:
        data = extract_json(text)
        score = int(data.get("score", 0))
        score = max(0, min(100, score))
        tags = [str(t) for t in data.get("tags", [])]
        reason = str(data.get("reason", ""))
    except (ValueError, TypeError):
        score, tags, reason = 0, [], "打分输出解析失败，保守归为边缘"
    return RelevanceScore(score=score, tags=tags, layer=config.layer_for(score), reason=reason)
