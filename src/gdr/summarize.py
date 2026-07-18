from gdr.jsonutil import extract_json
from gdr.llm import LLM, tier_model
from gdr.models import Paper, PaperSummary

_SYSTEM = "你是高能天体物理文献综述助手，用简洁中文写作，只输出 JSON。"

_USER_TMPL = """请为下面这篇论文写一张中文综述卡片，输出 JSON（所有字段中文，力求简洁可扫读）：
{{
  "title_zh": "标题的中文译名",
  "team": "第一作者、通讯作者、主要机构；是否知名合作组",
  "tldr": "一句话核心：这篇干了什么",
  "review": "内容综述，3-5 句：研究对象/数据方法/主要结果/结论",
  "highlight": "亮点：为什么值得关注、创新点",
  "relation": "与 GECAM 科学目标或高能暂现研究的联系；无则写'—'"
}}

英文标题：{title}
作者：{authors}
分类：{categories}
正文/摘要：
{body}
"""


def summarize_paper(paper: Paper, fulltext: str | None, llm: LLM) -> PaperSummary:
    body = fulltext if fulltext else paper.abstract
    user = _USER_TMPL.format(
        title=paper.title,
        authors=", ".join(paper.authors),
        categories=", ".join(paper.categories),
        body=body,
    )
    text = llm.complete(model=tier_model("write"), system=_SYSTEM, user=user)
    try:
        d = extract_json(text)
        return PaperSummary(
            paper_id=paper.id,
            title_zh=str(d.get("title_zh") or paper.title),
            team=str(d.get("team") or ""),
            tldr=str(d.get("tldr") or ""),
            review=str(d.get("review") or ""),
            highlight=str(d.get("highlight") or ""),
            relation=str(d.get("relation") or ""),
        )
    except (ValueError, TypeError):
        return PaperSummary(
            paper_id=paper.id, title_zh=paper.title, team=", ".join(paper.authors),
            tldr="", review=paper.abstract, highlight="", relation="—",
        )
