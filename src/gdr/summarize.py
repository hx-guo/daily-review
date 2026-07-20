from gdr.jsonutil import extract_json
from gdr.llm import LLM, tier_model
from gdr.models import Paper, PaperSummary

_SYSTEM = "你是高能天体物理文献综述助手，用简洁中文写作，只输出 JSON。"

_USER_TMPL = """请为下面这篇论文写一张中文综述卡片，输出 JSON（中文字段力求简洁可扫读）：
{{
  "title_zh": "标题的中文译名",
  "tldr": "一句话核心：这篇干了什么（仅用于当日总览，卡片不展示）",
  "highlight": "亮点：为什么值得关注、创新点，1-2 句",
  "context_outlook": "脉络与展望：一段连贯叙述（3-5 句），先承接与既往研究的联系，再展望方法/领域的发展趋势（由过去到未来）。凡引用到具体的既往工作，就地用 [[作者+年份]] 标注，例如 [[DeLaunay+ 2022]]、[[Wijnands+ 2013]]；标注文本要与 citations 里的 label 完全一致。不要臆造文献。",
  "citations": [
    {{"label": "与正文一致的作者+年份，如 'DeLaunay+ 2022'",
      "arxiv": "仅当正文明确出现该文献的 arXiv 编号时填（如 '2205.01346'），否则空字符串——绝不臆造编号",
      "doi": "仅当正文明确出现该文献的 DOI 时填，否则空字符串"}}
  ],
  "authors_en": "英文原文中前3位作者的姓名及其工作单位（从正文/作者块提取，如 'A. Author (Institute X), B. Boss (Institute Y), C. Coauthor (Institute Z)'）；若超过3位在末尾加 ' et al.'；提取不到单位就只给姓名",
  "corresponding_en": "通讯作者的英文姓名（从正文提取，通常标注 corresponding author / 星号 / 邮箱作者）；提取不到就留空字符串"
}}

要求：citations 里只列 context_outlook 中真正 [[标注]] 过的文献；没有可靠引用时 citations 用空数组 []。

英文标题：{title}
作者：{authors}
分类：{categories}
正文/摘要：
{body}
"""


def _clean_citations(raw) -> list[dict]:
    out = []
    if isinstance(raw, list):
        for c in raw:
            if not isinstance(c, dict):
                continue
            label = str(c.get("label") or "").strip()
            if not label:
                continue
            out.append({"label": label,
                        "arxiv": str(c.get("arxiv") or "").strip(),
                        "doi": str(c.get("doi") or "").strip()})
    return out


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
            team="",
            tldr=str(d.get("tldr") or ""),
            review="",
            highlight=str(d.get("highlight") or ""),
            relation="",
            authors_en=str(d.get("authors_en") or ""),
            corresponding_en=str(d.get("corresponding_en") or ""),
            context_outlook=str(d.get("context_outlook") or ""),
            citations=_clean_citations(d.get("citations")),
        )
    except (ValueError, TypeError):
        return PaperSummary(
            paper_id=paper.id, title_zh=paper.title, team="",
            tldr="", review="", highlight="", relation="",
            context_outlook=paper.abstract,
        )


_EDGE_SYSTEM = "你是高能天体物理文献助手，用简洁中文写作，只输出 JSON。"

_EDGE_USER_TMPL = """把下面这篇论文压缩成一行中文，输出 JSON（仅这两个字段）：
{{"title_zh": "标题的中文译名", "tldr": "一句话说明这篇论文做了什么"}}

英文标题：{title}
摘要：{abstract}
"""


def summarize_edge(paper: Paper, llm: LLM) -> PaperSummary:
    user = _EDGE_USER_TMPL.format(title=paper.title, abstract=paper.abstract)
    text = llm.complete(model=tier_model("triage"), system=_EDGE_SYSTEM, user=user)
    try:
        d = extract_json(text)
        return PaperSummary(paper_id=paper.id, title_zh=str(d.get("title_zh") or paper.title),
                            team="", tldr=str(d.get("tldr") or ""),
                            review="", highlight="", relation="")
    except (ValueError, TypeError):
        return PaperSummary(paper_id=paper.id, title_zh=paper.title, team="",
                            tldr="", review="", highlight="", relation="")
