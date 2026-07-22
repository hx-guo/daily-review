import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from gdr import config
from gdr.jsonutil import extract_json
from gdr.llm import LLM, tier_model
from gdr.models import DailyReview


_SYSTEM = "你是审慎的高能天体物理新闻编辑。严格依据给定论文材料，只输出 JSON。"

_CANDIDATE_TMPL = """今天是 {date}。只复核下面这一篇文献：
{digest}

请独立判断这篇论文是否达到新闻门槛；不要与其他论文比较，也不选择主头条：
- breaking：摘要明确支持的新暂现事件、首次/突破性探测、异常极端结果、重要联合对应体，或需要及时跟进的重大任务结果。
- headline：足以显著改变科学认识、观测能力或任务实践的重大进展，但不具有突发性。
- headline 是极少数领域级重大进展，不是 core、高分论文或“有意义工作”的同义词。首次只是必要性线索，不是充分条件。
- 常规增量、把已知规律拓展到新样本/尺度、单源参数或形态更新、未经真实数据验证的方法、纯理论可观测预测、宽泛综述，以及仅凭 first/new/unprecedented 等宣传词的结果，原则上 reject；只有明确推翻长期关键认识或带来此前不可能的已证实能力时例外。
- 新闻简报、Research Briefing、News & Views、社论、评论、更正和撤稿说明不能借用其报道对象的重要性进入候选；候选必须是材料中原始研究自身给出的结果。
- reason 中的事实性主张必须由所给原题或原摘要直接支持；“通常如此”或“标准推断”不能代替证据。

只输出一个很短的 JSON 对象：
{{
  "paper_id": "必须原样复制材料中的 paper_id",
  "decision": "reject|breaking|headline",
  "reason": "一句话说明为何拒绝或提名"
}}
不要输出标题、证据、影响、数组或任何额外字段。不要为了填栏目提名。
"""

_VERIFY_TMPL = """请作为第二位、更加怀疑的资深科学编辑，只复核下面这一篇候选新闻。

原始论文材料：
{digest}

第一轮候选：
{candidate}

逐条执行质量门槛：
1. evidence 必须能由材料直接支持，而非从标题修辞推断。
2. title、impact 和 reason 中的事实性前提也必须由材料支持；不接受材料之外的“标准推断”、源类确认或影响外推。
3. 新闻简报、Research Briefing、News & Views、社论、评论、更正和撤稿说明不是原始结果，必须删除，不能把其报道对象的结论算到本条目名下。
4. breaking 必须兼具明确的新观测/事件或突破性首次结果、重大影响，以及现实的及时跟进价值；否则降为 headline 或删除。
5. headline 必须是会实质改变领域级认识、能力或实践的重大进展，而不只是扎实、新颖或团队相关。仅拓展已知标度到新样本/尺度、单源增量、未由真实数据验证的方法、纯理论预测，原则上拒绝；除非材料直接表明它否定长期关键假设或实现此前不可能的能力。
6. 不与其他候选比较，不选主头条；每篇论文独立过同一质量门槛。
7. 只能保留、降级或拒绝第一轮候选，不能升级 headline 为 breaking。
8. 若 impact 主要依赖“未来若验证”“有望”“可用于”等尚未发生的影响，而论文当前结果本身不足以改变认识或能力，必须拒绝。

只输出一个 JSON 对象。拒绝时 title/evidence/impact 为空字符串；保留时必须完整填写：
{{
  "paper_id": "必须原样复制材料中的 paper_id",
  "decision": "reject|breaking|headline",
  "title": "克制、准确的中文新闻标题，拒绝时为空",
  "evidence": "原摘要明确给出的关键结果或数值，拒绝时为空",
  "impact": "这项结果将改变什么或为何需要关注，拒绝时为空",
  "reason": "通过、降级或拒绝的理由",
  "watchlist": ["与保留新闻直接相关、需要后续确认的具体信号"]
}}
"""


_NON_RESEARCH_TITLE = re.compile(
    r"^(?:publisher\s+|author\s+)?(?:correction|erratum|corrigendum|retraction)\b"
    r"|^(?:editorial|news\s*&\s*views|research\s+(?:briefing|highlight))\b",
    re.IGNORECASE,
)


def _complete_json_object(
        llm: LLM, user: str, validate: Callable[[dict], dict]) -> dict:
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
            return validate(data)
        except (ValueError, TypeError) as exc:
            last_error = exc
    raise TypeError("daily review returned invalid JSON twice") from last_error


def _candidate_decision(data: dict, paper_id: str) -> dict:
    returned_id = str(data.get("paper_id", "")).strip()
    decision = str(data.get("decision", "")).strip().lower()
    reason = str(data.get("reason", "")).strip()
    if (returned_id != paper_id
            or decision not in {"reject", "breaking", "headline"}
            or not reason):
        raise TypeError("invalid per-paper candidate decision")
    return {"paper_id": paper_id, "decision": decision, "reason": reason}


def _verified_decision(data: dict, paper_id: str,
                       proposed_level: str) -> dict:
    returned_id = str(data.get("paper_id", "")).strip()
    decision = str(data.get("decision", "")).strip().lower()
    title = str(data.get("title", "")).strip()
    evidence = str(data.get("evidence", "")).strip()
    impact = str(data.get("impact", "")).strip()
    reason = str(data.get("reason", "")).strip()
    raw_watchlist = data.get("watchlist", [])
    if (returned_id != paper_id
            or decision not in {"reject", "breaking", "headline"}
            or not reason or not isinstance(raw_watchlist, list)):
        raise TypeError("invalid per-paper verification decision")
    if proposed_level == "headline" and decision == "breaking":
        raise TypeError("verification cannot upgrade a headline candidate")
    if decision != "reject" and not all((title, evidence, impact)):
        raise TypeError("retained story is missing required evidence")
    return {
        "paper_id": paper_id,
        "decision": decision,
        "title": title,
        "evidence": evidence,
        "impact": impact,
        "reason": reason,
        "watchlist": [str(x).strip() for x in raw_watchlist if str(x).strip()],
    }


def _parallel_map(fn, values: list, max_workers: int) -> list:
    if max_workers <= 1 or len(values) <= 1:
        return [fn(value) for value in values]
    with ThreadPoolExecutor(max_workers=min(max_workers, len(values))) as pool:
        return list(pool.map(fn, values))


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


def _abstract_excerpt(text: str, limit: int | None = None) -> str:
    text = " ".join(text.split())
    if limit is None or len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _digest(items: list[dict], *, abstract_limit: int | None = None,
            include_machine_guide: bool = True) -> str:
    lines = []
    for it in items:
        summ = it["summary"]
        title = (summ.title_zh if summ and include_machine_guide
                 else it["paper"].title)
        tldr = summ.tldr if summ else ""
        contribution = summ.highlight if summ else ""
        sc = it["score"]
        paper = it["paper"]
        authors = ", ".join(paper.authors[:4]) or "（元数据未提供）"
        doi = paper.doi or paper.external_ids.get("doi", "") or "（无）"
        abstract = _abstract_excerpt(paper.abstract, abstract_limit) or "（无摘要）"
        line = (
            f"- paper_id={paper.id} [{sc.layer}; 优先级 {sc.score}] {title}\n"
            f"  原文标题：{paper.title}\n"
            f"  作者：{authors}；DOI：{doi}\n"
            f"  原文摘要：{abstract}\n"
            f"  标签：{', '.join(sc.tags)}；归类依据：{sc.reason}"
        )
        if include_machine_guide:
            line += ("\n  机器导读（仅用于第一轮定位，不能作为第二轮新闻证据）："
                     f"{tldr}；{contribution}")
        lines.append(line)
    return "\n".join(lines)


def _legacy_story_lines(stories: list[dict]) -> str:
    return "\n".join(
        f"[{story['level'].upper()}] {story['title']}：{story['impact']}"
        for story in stories
    )


def make_daily_review(date: str, items: list[dict], llm: LLM,
                      editorial_workers: int | None = None) -> DailyReview:
    if not items:
        return DailyReview(
            date=date, overview="今日无新文献。", highlights="—", trends="—",
            editorial_version=2, stories=[], watchlist=[],
        )

    editorial_workers = editorial_workers or config.EDITORIAL_MAX_CONCURRENCY
    eligible_items = []
    seen_ids = set()
    for item in items:
        paper_id = item["paper"].id
        if paper_id not in seen_ids and _news_eligible(item):
            eligible_items.append(item)
            seen_ids.add(paper_id)
    if not eligible_items:
        return DailyReview(
            date=date,
            overview="今日无达到 BREAKING 或 HEADLINE 门槛的原始研究进展。",
            highlights="—", trends="—", editorial_version=2,
            stories=[], watchlist=[],
        )

    try:
        def nominate(item: dict) -> dict:
            paper_id = item["paper"].id
            user = _CANDIDATE_TMPL.format(
                date=date, digest=_digest([item]))
            return _complete_json_object(
                llm, user,
                lambda data: _candidate_decision(data, paper_id),
            )

        nominations = _parallel_map(
            nominate, eligible_items, editorial_workers)
        candidates = [item for item in nominations
                      if item["decision"] != "reject"]
        if not candidates:
            return DailyReview(
                date=date,
                overview="今日无达到 BREAKING 或 HEADLINE 门槛的进展。",
                highlights="—", trends="—", editorial_version=2,
                stories=[], watchlist=[],
            )
        item_by_id = {item["paper"].id: item for item in eligible_items}

        def verify(candidate: dict) -> dict:
            paper_id = candidate["paper_id"]
            user = _VERIFY_TMPL.format(
                digest=_digest(
                    [item_by_id[paper_id]], include_machine_guide=False),
                candidate=json.dumps(candidate, ensure_ascii=False),
            )
            return _complete_json_object(
                llm, user,
                lambda data: _verified_decision(
                    data, paper_id, candidate["decision"]),
            )

        decisions = _parallel_map(verify, candidates, editorial_workers)
        stories = [
            {
                "paper_id": decision["paper_id"],
                "level": decision["decision"],
                "title": decision["title"],
                "evidence": decision["evidence"],
                "impact": decision["impact"],
                "reason": decision["reason"],
            }
            for decision in decisions if decision["decision"] != "reject"
        ]
        watchlist = []
        for decision in decisions:
            if decision["decision"] != "reject":
                watchlist.extend(decision["watchlist"])
        watchlist = list(dict.fromkeys(watchlist))
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
