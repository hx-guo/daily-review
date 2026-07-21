from gdr import config
from gdr.jsonutil import extract_json
from gdr.llm import LLM, tier_model
from gdr.models import Paper, PaperSummary

_SYSTEM = "你是高能天体物理文献综述助手，通读整篇论文后用简洁中文写作，只输出 JSON。"

_USER_TMPL = """下面给出的是这篇论文的**完整正文（含末尾的参考文献表）**。请通读全文后写一张中文综述卡片，输出 JSON（中文字段力求简洁可扫读）：
{{
  "title_zh": "标题的中文译名",
  "tldr": "一句话核心：这篇干了什么（仅用于当日总览，卡片不展示）",
  "highlight": "亮点：为什么值得关注、创新点，1-2 句",
  "context_outlook": "脉络与展望：一段连贯叙述（3-5 句），先承接与既往研究的联系，再展望方法/领域的发展趋势（由过去到未来）。凡引用到具体的既往工作，就地用 [[作者+年份]] 标注，例如 [[DeLaunay+ 2022]]、[[Wijnands+ 2013]]；标注文本要与 citations 里的 label 完全一致，且必须是可识别的『姓氏+年份』，不要用论文自定义的缩写（如 G25、Paper I）。不要臆造文献。",
  "citations": [
    {{"label": "与 context_outlook 中 [[标注]] 完全一致的作者+年份，如 'DeLaunay+ 2022'",
      "authors": "该文献第一作者的姓氏（仅姓，如 'DeLaunay'）",
      "year": "该文献年份（4 位数字）",
      "title": "该文献标题（从参考文献表原文抄录；抄不到就留空）",
      "ref": "参考文献表里该条目的完整原文（用于检索核对；务必逐字抄录）"}}
  ],
  "authors_en": "英文原文中前3位作者的姓名及其工作单位（从正文/作者块提取，如 'A. Author (Institute X), B. Boss (Institute Y), C. Coauthor (Institute Z)'）；若超过3位在末尾加 ' et al.'；提取不到单位就只给姓名",
  "corresponding_en": "通讯作者的英文姓名（从正文提取，通常标注 corresponding author / 星号 / 邮箱作者）；提取不到就留空字符串"
}}

要求：citations 只列 context_outlook 中真正 [[标注]] 过的文献；每条尽量根据**参考文献表**填 authors/year/title/ref，便于程序检索到确切链接；没有可靠引用时 citations 用空数组 []。

英文标题：{title}
作者：{authors}
分类：{categories}
正文（含参考文献）：
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
                        "authors": str(c.get("authors") or "").strip(),
                        "year": str(c.get("year") or "").strip(),
                        "title": str(c.get("title") or "").strip(),
                        "ref": str(c.get("ref") or "").strip()})
    return out


def _parse(paper: Paper, text: str) -> PaperSummary:
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


def summarize_paper(paper: Paper, fulltext: str | None, llm: LLM) -> PaperSummary:
    body = fulltext if fulltext else paper.abstract

    def _call(text_body: str) -> str:
        user = _USER_TMPL.format(
            title=paper.title, authors=", ".join(paper.authors),
            categories=", ".join(paper.categories), body=text_body)
        return llm.complete(model=tier_model("write"), system=_SYSTEM, user=user)

    try:
        return _parse(paper, _call(body))
    except (ValueError, TypeError):
        pass                                        # parse failure — no retry, use metadata below
    except Exception:
        # transport/model error (e.g. an over-long paper overflowing context): retry once
        # with a short body before giving up, so the write call still yields a real summary.
        if len(body) > config.FULLTEXT_RETRY_CHARS:
            try:
                return _parse(paper, _call(body[: config.FULLTEXT_RETRY_CHARS]))
            except Exception:
                pass
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
