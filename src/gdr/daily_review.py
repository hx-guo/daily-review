from gdr.jsonutil import extract_json
from gdr.llm import LLM, tier_model
from gdr.models import DailyReview

_SYSTEM = "你是高能天体物理领域的资深综述编辑，用简洁中文写作，只输出 JSON。"

_USER_TMPL = """今天（{date}）收录了以下文献（按相关性分层）：
{digest}

请写当日总览综述，输出 JSON：
{{
  "overview": "今日概览：多少篇、各主题分布",
  "highlights": "今日亮点：挑 2-4 篇最值得读的，逐条说明为什么亮",
  "trends": "趋势与联系：共同趋势、与近期/经典研究的呼应、值得注意的方向"
}}
"""


def _digest(items: list[dict]) -> str:
    lines = []
    for it in items:
        summ = it["summary"]
        title = summ.title_zh if summ else it["paper"].title
        tldr = summ.tldr if summ else ""
        sc = it["score"]
        lines.append(f"- [{sc.layer}] {title}（标签：{', '.join(sc.tags)}）{tldr}")
    return "\n".join(lines)


def make_daily_review(date: str, items: list[dict], llm: LLM) -> DailyReview:
    if not items:
        return DailyReview(date=date, overview="今日无新文献。", highlights="—", trends="—")
    user = _USER_TMPL.format(date=date, digest=_digest(items))
    text = llm.complete(model=tier_model("synth"), system=_SYSTEM, user=user)
    try:
        d = extract_json(text)
        return DailyReview(
            date=date,
            overview=str(d.get("overview", "")),
            highlights=str(d.get("highlights", "")),
            trends=str(d.get("trends", "")),
        )
    except (ValueError, TypeError):
        return DailyReview(date=date, overview=f"今日收录 {len(items)} 篇。",
                           highlights="（综述生成失败）", trends="—")
