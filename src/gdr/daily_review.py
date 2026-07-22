from gdr.jsonutil import extract_json
from gdr.llm import LLM, tier_model
from gdr.models import DailyReview

_SYSTEM = "你是高能天体物理新闻编辑。依据给定论文证据判断当天是否有头条，只输出 JSON。"

_USER_TMPL = """今天（{date}）收录了以下文献（按相关性分层）：
{digest}

页面已单独展示论文总数和主题标签，不要复述篇数，不要写每天都成立的泛泛方向总结。

先判断有无真正的编辑头条：
- breaking：摘要明确支持的新暂现事件、首次/突破性探测、异常极端结果、重要联合对应体或正式重大任务结果。
  必须有具体论文和结果证据；不得仅凭标题中的“first/new/unprecedented”或模型推测使用 breaking。
- headline：当天最值得优先阅读、对团队科学或任务有明确影响的进展，但尚不足以称为突发。
- none：没有足够强的单篇头条。不要硬造热点；标题写“今日无突发头条”，随后仍可列出值得跟进的进展。

输出 JSON：
{{
  "headline_level": "breaking|headline|none",
  "headline": "新闻式标题；无头条时固定为‘今日无突发头条’",
  "headline_paper_id": "支撑头条的 paper_id；none 时可为空",
  "headline_reason": "2-4 句：发生了什么、证据是什么、为什么值得团队关注；避免宣传腔",
  "developments": [
    {{"paper_id": "paper_id", "title": "简短中文标题", "reason": "这项进展新增了什么信息，为什么值得读"}}
  ],
  "watchlist": ["1-3 条需要后续数据、独立验证或持续观察的具体信号；没有则为空"]
}}
developments 选 2-4 项，不得重复头条措辞；所有 paper_id 必须来自下方材料。不要臆造论文之外的实时事件。
"""


def _digest(items: list[dict]) -> str:
    lines = []
    for it in items:
        summ = it["summary"]
        title = summ.title_zh if summ else it["paper"].title
        tldr = summ.tldr if summ else ""
        contribution = summ.highlight if summ else ""
        sc = it["score"]
        lines.append(
            f"- paper_id={it['paper'].id} [{sc.layer}; 优先级 {sc.score}] {title}\n"
            f"  标签：{', '.join(sc.tags)}；归类依据：{sc.reason}\n"
            f"  一句话：{tldr}；具体贡献：{contribution}"
        )
    return "\n".join(lines)


def _legacy_lines(developments: list[dict]) -> str:
    return "\n".join(
        f"{i}. {item.get('title', '')}：{item.get('reason', '')}"
        for i, item in enumerate(developments, 1)
    )


def make_daily_review(date: str, items: list[dict], llm: LLM) -> DailyReview:
    if not items:
        return DailyReview(date=date, overview="今日无新文献。", highlights="—", trends="—",
                           headline_level="none", headline="今日无新文献")
    user = _USER_TMPL.format(date=date, digest=_digest(items))
    text = llm.complete(model=tier_model("synth"), system=_SYSTEM, user=user)
    try:
        d = extract_json(text)
        valid_ids = {it["paper"].id for it in items}
        level = str(d.get("headline_level", "none")).lower()
        if level not in {"breaking", "headline", "none"}:
            level = "none"
        headline = str(d.get("headline", "")).strip()
        if level == "none":
            headline = "今日无突发头条"
        elif not headline:
            headline = "今日值得关注的进展"
        headline_paper_id = str(d.get("headline_paper_id", "")).strip()
        if headline_paper_id not in valid_ids:
            headline_paper_id = ""
        if level in {"breaking", "headline"} and not headline_paper_id:
            level = "none"
            headline = "今日无突发头条"
        developments = []
        for raw in d.get("developments", [])[:4]:
            if not isinstance(raw, dict):
                continue
            paper_id = str(raw.get("paper_id", "")).strip()
            if paper_id not in valid_ids:
                continue
            developments.append({
                "paper_id": paper_id,
                "title": str(raw.get("title", "")).strip(),
                "reason": str(raw.get("reason", "")).strip(),
            })
        watchlist = [str(x).strip() for x in d.get("watchlist", [])
                     if str(x).strip()][:3]
        reason = str(d.get("headline_reason", "")).strip()
        legacy_developments = _legacy_lines(developments)
        legacy_watch = "\n".join(f"{i}. {x}" for i, x in enumerate(watchlist, 1))
        return DailyReview(
            date=date, overview=reason or headline, highlights=legacy_developments,
            trends=legacy_watch, headline_level=level, headline=headline,
            headline_paper_id=headline_paper_id, headline_reason=reason,
            developments=developments, watchlist=watchlist,
        )
    except (ValueError, TypeError):
        return DailyReview(date=date, overview="头条判断生成失败。",
                           highlights="（综述生成失败）", trends="—",
                           headline_level="none", headline="今日无可靠头条判断")
