import json
import re

from gdr.jsonutil import extract_json
from gdr.llm import LLM, tier_model
from gdr.models import DailyReview


_SYSTEM = "你是审慎的高能天体物理新闻编辑。严格依据给定论文材料，只输出 JSON。"

_CANDIDATE_TMPL = """今天（{date}）收录了以下文献（按相关性分层）：
{digest}

页面已单独展示论文总数和主题标签，不要复述篇数，不要写每天都成立的泛泛方向总结。

请逐篇提名真正可能达到新闻门槛的候选，不设数量目标或上限，也不选择主头条：
- breaking：摘要明确支持的新暂现事件、首次/突破性探测、异常极端结果、重要联合对应体，或需要及时跟进的重大任务结果。
- headline：足以显著改变科学认识、观测能力或任务实践的重大进展，但不具有突发性。
- 常规增量、一般参数改进、宽泛综述、仅凭 first/new/unprecedented 等宣传词的结果不要提名。
- 新闻简报、Research Briefing、News & Views、社论、评论、更正和撤稿说明不能借用其报道对象的重要性进入候选；候选必须是材料中原始研究自身给出的结果。
- title、evidence、impact 和 reason 中的事实性主张都必须由所给原题或原摘要直接支持；“通常如此”或“标准推断”不能代替证据。

输出 JSON：
{{
  "candidates": [
    {{
      "paper_id": "必须来自材料",
      "level": "breaking|headline",
      "title": "克制、准确的中文新闻标题",
      "evidence": "摘要明确给出的关键结果或数值",
      "impact": "这项结果将改变什么或为何需要关注",
      "reason": "为何达到该新闻等级"
    }}
  ],
  "watchlist": ["尚需新数据、独立验证或持续观察的具体信号"]
}}
候选可以为空。不要为了填栏目提名，不要臆造论文材料之外的实时事件。
"""

_VERIFY_TMPL = """请作为第二位、更加怀疑的资深科学编辑，复核下面的候选新闻。

原始论文材料：
{digest}

第一轮候选：
{candidates}

逐条执行质量门槛：
1. evidence 必须能由材料直接支持，而非从标题修辞推断。
2. title、impact 和 reason 中的事实性前提也必须由材料支持；不接受材料之外的“标准推断”、源类确认或影响外推。
3. 新闻简报、Research Briefing、News & Views、社论、评论、更正和撤稿说明不是原始结果，必须删除，不能把其报道对象的结论算到本条目名下。
4. breaking 必须兼具明确的新观测/事件或突破性首次结果、重大影响，以及现实的及时跟进价值；否则降为 headline 或删除。
5. headline 必须是会实质改变认识、能力或实践的重大进展；扎实但常规的论文应删除。
6. 不比较候选之间谁更重要，不选主头条，同一等级完全平级。
7. 不设数量目标或上限。宁可输出空列表，也不要降低门槛。
8. 只能保留、降级或删除第一轮候选，不能新增候选；同一论文最多出现一次。

输出 JSON：
{{
  "stories": [
    {{"paper_id": "...", "level": "breaking|headline", "title": "...",
      "evidence": "...", "impact": "...", "reason": "通过复核的理由"}}
  ],
  "watchlist": ["与保留新闻直接相关、需要后续确认的具体信号"]
}}
"""


_NON_RESEARCH_TITLE = re.compile(
    r"^(?:publisher\s+|author\s+)?(?:correction|erratum|corrigendum|retraction)\b"
    r"|^(?:editorial|news\s*&\s*views|research\s+(?:briefing|highlight))\b",
    re.IGNORECASE,
)


def _complete_json_object(llm: LLM, user: str, required_list_key: str) -> dict:
    retry_note = """

上一次响应无法解析为完整 JSON 对象。请重新执行同一任务，只输出一个语法完整的 JSON 对象；
不要使用 Markdown 代码块或附加说明。继续严格把关，必要时减少候选，不要为了修复格式而降低门槛。
"""
    last_error: Exception | None = None
    for attempt in range(2):
        text = llm.complete(
            model=tier_model("synth"),
            system=_SYSTEM,
            user=user if attempt == 0 else user + retry_note,
        )
        try:
            data = extract_json(text)
            if not isinstance(data, dict):
                raise TypeError("daily review response must be a JSON object")
            if (required_list_key not in data
                    or not isinstance(data[required_list_key], list)):
                raise TypeError(
                    f"daily review response must contain a {required_list_key} list")
            return data
        except (ValueError, TypeError) as exc:
            last_error = exc
    raise TypeError("daily review returned invalid JSON twice") from last_error


def _news_eligible(item: dict) -> bool:
    """Apply only high-confidence source-type exclusions to editorial news."""
    paper = item["paper"]
    title = paper.title.strip()
    doi = (paper.doi or paper.external_ids.get("doi", "")).strip().lower()
    if doi.startswith("10.1038/d41586-"):
        # Nature's d41586 namespace contains editorial/news material rather
        # than the primary research articles whose results it discusses.
        return False
    if _NON_RESEARCH_TITLE.search(title):
        return False
    # A missing byline plus a one-sentence blurb is characteristic of an ADS
    # editorial/news record. Keep either signal alone permissive so incomplete
    # metadata on a real paper does not automatically disqualify it.
    if not paper.authors and len(paper.abstract.strip()) < 220:
        return False
    return True


def _abstract_excerpt(text: str, limit: int = 1400) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _digest(items: list[dict], *, abstract_limit: int = 1400) -> str:
    lines = []
    for it in items:
        summ = it["summary"]
        title = summ.title_zh if summ else it["paper"].title
        tldr = summ.tldr if summ else ""
        contribution = summ.highlight if summ else ""
        sc = it["score"]
        paper = it["paper"]
        authors = ", ".join(paper.authors[:4]) or "（元数据未提供）"
        doi = paper.doi or paper.external_ids.get("doi", "") or "（无）"
        abstract = _abstract_excerpt(paper.abstract, abstract_limit) or "（无摘要）"
        lines.append(
            f"- paper_id={paper.id} [{sc.layer}; 优先级 {sc.score}] {title}\n"
            f"  原文标题：{paper.title}\n"
            f"  作者：{authors}；DOI：{doi}\n"
            f"  原文摘要：{abstract}\n"
            f"  标签：{', '.join(sc.tags)}；归类依据：{sc.reason}\n"
            f"  机器导读（仅用于定位，不能独立作为新闻证据）：{tldr}；{contribution}"
        )
    return "\n".join(lines)


def _validated_stories(raw_stories, valid_ids: set[str]) -> list[dict]:
    stories = []
    seen_ids = set()
    for raw in raw_stories if isinstance(raw_stories, list) else []:
        if not isinstance(raw, dict):
            continue
        paper_id = str(raw.get("paper_id", "")).strip()
        level = str(raw.get("level", "")).strip().lower()
        title = str(raw.get("title", "")).strip()
        evidence = str(raw.get("evidence", "")).strip()
        impact = str(raw.get("impact", "")).strip()
        reason = str(raw.get("reason", "")).strip()
        if (paper_id not in valid_ids or paper_id in seen_ids
                or level not in {"breaking", "headline"}
                or not all((title, evidence, impact, reason))):
            continue
        stories.append({
            "paper_id": paper_id, "level": level, "title": title,
            "evidence": evidence, "impact": impact, "reason": reason,
        })
        seen_ids.add(paper_id)
    return stories


def _legacy_story_lines(stories: list[dict]) -> str:
    return "\n".join(
        f"[{story['level'].upper()}] {story['title']}：{story['impact']}"
        for story in stories
    )


def make_daily_review(date: str, items: list[dict], llm: LLM) -> DailyReview:
    if not items:
        return DailyReview(
            date=date, overview="今日无新文献。", highlights="—", trends="—",
            editorial_version=2, stories=[], watchlist=[],
        )

    eligible_items = [it for it in items if _news_eligible(it)]
    if not eligible_items:
        return DailyReview(
            date=date,
            overview="今日无达到 BREAKING 或 HEADLINE 门槛的原始研究进展。",
            highlights="—", trends="—", editorial_version=2,
            stories=[], watchlist=[],
        )

    # The broad nomination pass sees enough of every abstract to identify
    # plausible candidates. The skeptical pass below then gets the longer
    # source material only for those candidates, keeping it focused and fast.
    digest = _digest(eligible_items, abstract_limit=1000)
    candidate_user = _CANDIDATE_TMPL.format(date=date, digest=digest)
    try:
        candidate_data = _complete_json_object(
            llm, candidate_user, required_list_key="candidates")
        candidate_payload = {
            "candidates": candidate_data.get("candidates", []),
            "watchlist": candidate_data.get("watchlist", []),
        }
        raw_candidates = candidate_payload["candidates"]
        candidate_ids = {
            str(candidate.get("paper_id", "")).strip()
            for candidate in raw_candidates if isinstance(candidate, dict)
        } if isinstance(raw_candidates, list) else set()
        candidate_items = [
            it for it in eligible_items if it["paper"].id in candidate_ids
        ]
        if not candidate_items:
            return DailyReview(
                date=date,
                overview="今日无达到 BREAKING 或 HEADLINE 门槛的进展。",
                highlights="—", trends="—", editorial_version=2,
                stories=[], watchlist=[],
            )
        verify_user = _VERIFY_TMPL.format(
            digest=_digest(candidate_items),
            candidates=json.dumps(candidate_payload, ensure_ascii=False),
        )
        verified = _complete_json_object(
            llm, verify_user, required_list_key="stories")
        valid_ids = {it["paper"].id for it in eligible_items}
        stories = _validated_stories(verified.get("stories", []), valid_ids)
        watchlist = [str(x).strip() for x in verified.get("watchlist", [])
                     if str(x).strip()]
        overview = ("今日有通过严格复核的重大进展。" if stories
                    else "今日无达到 BREAKING 或 HEADLINE 门槛的进展。")
        return DailyReview(
            date=date,
            overview=overview,
            highlights=_legacy_story_lines(stories),
            trends="\n".join(watchlist),
            editorial_version=2,
            stories=stories,
            watchlist=watchlist,
        )
    except (ValueError, TypeError):
        return DailyReview(
            date=date, overview="新闻候选复核生成失败。",
            highlights="（新闻复核生成失败）", trends="—",
            editorial_version=2, stories=[], watchlist=[],
        )
