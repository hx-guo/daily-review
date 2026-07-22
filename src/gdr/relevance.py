from gdr import config
from gdr.jsonutil import extract_json
from gdr.llm import LLM, tier_model
from gdr.models import Paper, RelevanceScore

_SYSTEM = "你是高能暂现源研究团队的资深文献编辑。严格依据标题和摘要，只输出 JSON。"

_USER_TMPL = """下面是本研究团队的科学关注范围：
{profile}

主题标签与相关层级是两个独立判断。不要因为某个主题通常被视为相邻方向，就预先把它降级；
TDE、太阳耀斑、任务方法、引力波/中微子/FRB 宇宙学等，只要论文主要贡献直接服务团队目标，均可判为核心。

相关层级标准：
- core：主要科学问题、观测结果或方法直接服务团队目标。可经 science（科学问题）、observation（新事件/观测）、
  mission（任务数据/能力）或 method（可直接采用的方法）任一路径进入核心。
- related：主题在范围内，但主要贡献是背景、邻近问题、可迁移方法或间接应用。
- edge：仅提到关键词/任务/天体作为背景或示例，或与高能暂现及团队能力没有实质联系。

relation 取 direct、enabling、contextual 之一；core_path 取 science、observation、mission、method 或空字符串。
score 是层级内阅读优先级（0-100），只用于排序，不能用它反推 layer。evidence 必须指出标题/摘要中的具体依据。
输出 JSON：
{{"layer": "core|related|edge", "score": 0-100 的整数, "tags": ["主题标签", ...],
  "relation": "direct|enabling|contextual", "core_path": "science|observation|mission|method|",
  "evidence": "标题或摘要中的具体依据", "reason": "一句话归类理由（中文）"}}

标题：{title}
摘要：{abstract}
分类：{categories}
"""


def score_paper(paper: Paper, llm: LLM) -> RelevanceScore:
    user = _USER_TMPL.format(
        profile=config.TEAM_PROFILE,
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
        layer = str(data.get("layer", "")).lower()
        explicit_layer = layer in {"core", "related", "edge"}
        if not explicit_layer:
            # Backward-compatible fallback for old/test model replies. New replies
            # classify explicitly; score is only an ordering signal within a layer.
            layer = config.layer_for(score)
        relation = str(data.get("relation", ""))
        if relation not in {"direct", "enabling", "contextual"}:
            relation = ""
        core_path = str(data.get("core_path", ""))
        if core_path not in {"science", "observation", "mission", "method"}:
            core_path = ""
        evidence = str(data.get("evidence", ""))
        if explicit_layer and layer == "core":
            direct_core = relation == "direct" and bool(core_path) and bool(evidence.strip())
            enabling_core = (relation == "enabling" and core_path in {"mission", "method"}
                             and bool(evidence.strip()))
            if not (direct_core or enabling_core):
                # A core label must identify a concrete route and abstract evidence.
                # This makes the structured fields enforce the rubric instead of
                # merely recording a self-contradictory model explanation.
                layer = "related"
    except (ValueError, TypeError):
        score, tags, reason = 0, [], "分类输出解析失败，保守归为边缘"
        layer, relation, core_path, evidence = "edge", "", "", ""
    return RelevanceScore(score=score, tags=tags, layer=layer, reason=reason,
                          relation=relation, core_path=core_path, evidence=evidence)
