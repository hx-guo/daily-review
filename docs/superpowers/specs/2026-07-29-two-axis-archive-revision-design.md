# 双轴归档与修订历史 — 设计文档

- 日期：2026-07-29
- 状态：已通过讨论评审，待用户最终确认后进入实现计划（writing-plans）
- 影响面：`gdr.pipeline` / `gdr.store` / `gdr.daily_review` / `gdr.render` / `data/` 布局 / 模板与样式

---

## 1. 背景

当天公告的文献当天并不一定能收录完。arXiv 公告滞后约两天，ADS 收录期刊论文更晚，所以每次跑批都会把论文**回填**到它自己的日期上。这个能力已经存在且被大量使用——本地 17 天、1277 篇论文里，11 天有过补录，`2026-07-19` 从首次收录的 21 篇长到了 159 篇（87% 是后来补的）。

但当前实现有三个问题：

1. **补录对读者不可见。** 首页只显示"最新一个有论文的日期"，归档页只有一列光秃秃的日期。后来补进 07-19 的 138 篇论文，只看首页的人永远看不到。
2. **补录会重掷整天的编辑复核。** `sync()` 每次都把合并后的全量论文重新送进两轮新闻复核。按历次快照篇数累计，17 天里约 **351 次纯重复的提名调用**（core/related 占 24%），且是突发式的——07-19 有 96 篇 core/related，补录一次就是 96 次调用一起打出去。副作用是昨天的头条可能在今天悄悄变掉。
3. **修订快照只留 review，不留论文清单。** `revisions` 记的是 `{synced, n_papers, review}`，无法回答"哪几篇是后来加的"。

## 2. 目标

- **一篇论文只评审一次**，补录只为新论文付费。
- **两条时间轴**：按**收录日**看新闻（首页，每天翻新），按**归档日**看历史（归档，代表那一天的文献全貌）。
- **完整保留历史版本**，可切换查看任一时刻的归档日页面。
- **区分四个日期**：预印本、被期刊接受、被期刊刊出、本站收录。

**非目标**：不改动 editorial v2 的头条排版、卡片结构、TOC 抽屉；不改动相关性打分与全文总结流程；不重跑任何已有论文的 LLM 总结或决策。

## 3. 核心设计决定

**把 LLM 产物从"一天一份综述"下沉成"一篇论文一条编辑决策"，日级综述改为纯函数派生。**

这一条同时解决目标里的四项。前提已核实：`_CANDIDATE_TMPL` 与 `_VERIFY_TMPL` 都只吃单篇 digest，提名 prompt 明写「不要与其他论文比较，也不选择主头条」，唯一的日级输入是开头的「今天是 {date}」——把它换成这篇论文自己的预印本日与收录日之后，决策与"它被渲染在哪一页"完全无关，缓存严格合法。

派生出的三个结果：

- 两条时间轴只是同一批决策的两种分组，做两份不额外花钱。
- 任一历史版本 = 加一个 `ingested <= V` 的过滤条件，不需要存快照。
- 一篇论文的判定固定下来，只增不改，头条不再无声变化。

## 4. 数据模型

### 4.1 item 结构

```jsonc
{
  "paper":   { … },
  "score":   { … },
  "summary": { … },
  "dates": {
    "preprint":  "2026-03-14",   // arXiv v1 提交日，永远日精度
    "accepted":  "2026-06-21",   // 期刊接收日，多数源不提供
    "published": "2026-07-08",   // 期刊刊出日
    "published_precision": "day | month",
    "published_source": "crossref-online | crossref-print | crossref-created | ads-pubdate",
    "received":  "2026-02-26",   // 收稿日，顺带存下，卡片不显示
    "ingested":  "2026-07-22"    // 本站首次收录跑批日
  },
  "archive_date": "2026-03-14",  // 三个学术日期中最早的非空值
  "decision": {                   // 这辈子只算一次；edge 与非原始研究为 null
    "level": "breaking | headline | reject",
    "title": "…", "evidence": "…", "impact": "…",
    "reason": "…", "watchlist": ["…"],
    "reviewed_at": "2026-07-22"
  },
  "review_attempts": 0,
  "decision_final": false
}
```

### 4.2 四个日期的来源与取值规则

| 日期 | 来源 | 备注 |
|---|---|---|
| 预印本 | arXiv API 的 v1 `published` | 日精度；ADS 记录经 `external_ids.arxiv` 反查 |
| 接收 | Crossref `assertion` 中 name/label 含 `accept` 的项 | 覆盖率有限，见 4.3 |
| 刊出 | `published-online` ?? （`published-print`，若不晚于 `created`） ?? `created` ?? ADS `pubdate` | 记 `published_source` |
| 收录 | 本站跑批日期 | 全数据源口径一致 |

- **归档日 `archive_date` = 预印本 / 接收 / 刊出 三者中最早的非空值**（本站收录日不参与）。
- 跨精度比较时，月精度按当月 1 号参与比大小；**显示时保持原精度**，`2026-08` 就写 `2026-08`，绝不补成 `2026-08-01`。
- 唯一必须补 01 的情况：论文既无预印本也无接收日，且刊出日只有月精度——此时归档日取当月 1 号，卡片上标注 `刊出 2026-07（按 07-01 归档）`。
- 已知语义瑕疵（用户已知悉并接受）：无预印本但有接收日的论文会归档到接收日，而接收日并不公开。改成"最早的公开日期"是一行的事，留待将来。

### 4.3 Crossref 实测覆盖率

对现存 24 个 ADS DOI 实测（非随机抽样，取前 24 篇）：

| 出版商 | 接收日 | 刊出日 |
|---|---|---|
| AAS（ApJ / ApJS / PSJ） | 有，5/5 | 日精度 online + print |
| AGU、Pleiades、Springer | 有 | 日精度 |
| APS（PRD / PRL） | 无（只给收稿日） | 日精度 |
| OUP（MNRAS）、World Scientific | 无 | 日精度 |
| Elsevier（JHEAP / NewAst / Dark） | 无，6/6 | 见下 |

接收日整体覆盖 9/24（38%），天体物理主刊 AAS 全覆盖，所以实际关心的那部分论文覆盖率更高。

两个必须处理的坑：

1. **日期格式不统一。** AAS/AGU 给 ISO（`2026-05-23`），Springer/Pleiades 给英文长格式（`3 June 2026`、`26 May 2026`）。两种都要能解析；**解析失败留空，不猜**。
2. **Elsevier 的 `published-print` 是未来的预定刊期。** `10.1016/j.jheap.2026.100692` 的 print 是 `2026-08` 而 `created` 是 `2026-07-06`。照搬会把已经能读到的论文归档到一个月后，故规则中 `published-print` 晚于 `created` 时改用 `created`。

### 4.4 存储布局

```
data/ingest/2026-07-29.json   =  { "ingested": "2026-07-29", "items": [ … ] }
data/seen-index.json          =  { "<identity key>": "<收录日>", … }   // 由 list 升级为 dict
```

- 正常路径下写入永远是**新建一个文件**，历史文件不改写。现状是每补录一次就重写整个发表日文件（07-19.json 有 1 MB），git 历史全是噪音。
- 收录日页 = 读一个文件；归档日页 = 全量加载后按 `archive_date` 分组（`build_site` 本来就全量加载）；历史版本 = 只取 `ingested <= V` 的文件再分组。
- `DayData.revisions` 与 `DailyReview` 的持久化一并删除，日级综述改为渲染时计算。
- seen-index 升级成 `key → 收录日` 的映射，用于跨批次 enrich 定位论文所在文件。
- **唯一改写历史文件的路径是决策补评**（见 5.3），diff 只有一个 `decision` 字段。
- 规模：现在 4.3 MB / 1277 篇，一年后约 50 MB 量级，`build_site` 全量加载仍可承受；真顶不住时再加索引文件。

## 5. 生成流程

### 5.1 sync

```
抓 7 天窗口（arXiv 按 submittedDate，ADS 按 entdate）→ dedupe
  ├─ 命中 seen-index → enrich（见 5.2），不重新入库
  └─ 未见过 → 并发处理：score → summary（全文 / edge）→ resolve_citations
                         → dates 解析 → decision（仅 core/related 且原始研究）
写 data/ingest/<run_date>.json          // 一次写入，只含本次新增
更新 seen-index（key → run_date）
```

`load_day_or_none` / merge / 整天重掷全部消失。

`daily_review.py` 拆成两半：

- `review_paper(item, llm) -> decision`：提名 +（入围时）复核。
- `compose_review(date, items) -> DailyReview`：**纯函数，不碰 LLM**。挑出 `level != reject` 的组成 stories、`_quiet_overview()` 生成 overview、watchlist 去重。收录日轴、归档日轴、任意历史版本都调它。

prompt 改动：开头的「今天是 {date}」换成「本文预印本日 {preprint}，本站于 {ingested} 收录」。`breaking` 门槛本就要求"现实的及时跟进价值"，两个日期都给出来模型才判得对——一篇发表数月后才被收录的论文不该算突发。

### 5.2 跨批次 enrich

一篇论文先以 arXiv 预印本入库、数月后期刊版被 ADS 收录时，现在 seen-index 会认出同一篇然后**直接丢弃**，刊出日与接收日永远拿不到。改为：命中 seen-index 的记录经 `key → 收录日` 定位到它所在的 ingest 文件，**只合并日期与标识符**（DOI、bibcode、`external_ids`），不重新总结、不重新评审、不改归档日。卡片上的刊出日会自己长出来。

### 5.3 失败处理（两层）

**第一层，单次跑批内重试 10 次**，指数退避 1/2/4/8/16/30/30/30/30 秒（封顶 30 秒，单篇最坏约 2.5 分钟）。`EDITORIAL_ATTEMPTS = 10`，`GDR_EDITORIAL_ATTEMPTS` 可覆盖。openai SDK 对网络错误与 5xx/429 的重试单独配到 4 次——两类失败原因不同，分开配。附带熔断：本轮连续 20 篇全部十连败时，判定上游整段不可用，剩余论文直接留 `decision = null`，避免一次跑批被拖成一小时。

**第二层，跨跑批补评。** 每次 sync 开始先扫最近 7 天的 ingest 文件，对 `decision == null && review_attempts < 3` 的 core/related 论文补评一次，成功即回填并重写该文件；连续 3 轮失败标 `decision_final = true` 放弃。`scripts/regenerate_reviews.py` 改为这个用途（它本来就是"synth 挂了之后重跑"的救援脚本，新语义更准）。

要真正丢一篇需要连续 30 次失败横跨三天；而"上游整段抽风一整天"这种发生过的场景，第二天自动补回。

**决策失败不阻止入库**：`decision = null` 的论文照常进库，摘要、总结、脉络展望都在，照常出现在核心文献里。漏掉一篇本可能入选的论文，代价远小于把论文挡在库外。edge 层与非原始研究（勘误、Research Briefing）本就不评审，同样是 `null`，不花调用。

## 6. 页面

| 轴 | URL | 首页 | 语义 |
|---|---|---|---|
| 收录日 | `/news/2026-07-29.html` | `index.html` = 最新收录日 | 今天新收了什么、其中哪些是新闻 |
| 归档日 | `/day/2026-07-19.html`（沿用现有 URL） | — | 这一天的文献全貌 |

两边结构相同（今日头条 / 核心 / 相关 / edge 折叠），都由 `compose_review()` 渲染，只是喂进去的论文集合不同。masthead 一眼可分：新闻页 kicker 为 `INGEST · 本日收录`，归档页为 `ARCHIVE · 最早日期为此日`（不写"首次公开"，因为归档日可能落在不公开的接收日上，见 4.2），Vol/No 各按各自日期计算。新闻页之间有前后日导航，日常看新闻不必再翻归档。

**版本下拉（主要）**

归档页顶部一条版本条 `版本  ● 最新 159 篇   ○ 07-22 · 21 篇`，切换后整页按 `ingested <= V` 重新渲染——论文列表、头条、继续观察全部回到那时的状态。静态生成，URL 为 `/day/2026-07-19.as-of-2026-07-19.html`，最新版永远在裸 URL 上。只为有过补录的归档日生成额外页面。

**补录徽标（次要）**

只出现在最新版页面：页头一行 `本页经 2 次补录 · 07-20 +28 · 07-22 +2`，点某一批把那批高亮（纯前端）；每张卡片序号旁一个小徽标 `07-22 补录`，仅非首版收录的才有。排序仍按 layer + 优先级分数，补录论文按重要性混在正确位置——版本下拉回答"当时长什么样"，徽标回答"这次多了什么"。

**日期链**：卡片上显示 `预印本 2026-03-14 · 接收 2026-06-21 · 刊出 2026-07-08 · 收录 2026-07-22`，缺哪个不显示哪个，月精度保持月精度。

**归档页**：按年月分组，每行显示日期、篇数、有无突发、补录次数。按归档日归档会长出"稀疏日"——现存 245 篇 ADS 论文中 163 篇有 arXiv 预印本，提交月散布在 2016-01 至 2026-07，其中落在 2026-07 的至多 9 篇，其余会各自归到自己的真实日期上，而那些日子本站从未抓过 arXiv 全量。用户已知悉并选择"该什么日子就是什么日子"；归档页在本站覆盖期（2026-07-12）之前的日子上标注「本站自 2026-07-12 起收录，此前日期仅含后期补录的论文」。

editorial v2 的头条排版、卡片结构、TOC 抽屉一律不动。

## 7. 迁移

一次性脚本 `scripts/migrate_two_axis.py`，全程不调 LLM。

**7.1 `ingested` 从 git 历史精确重建。** 遍历 `data/daily/*.json` 的每个历史版本，一篇论文的 id 第一次出现在哪个 commit，那个 commit 的日期就是它的收录日。已验证：`2026-07-16.json` 首次出现于 `f3a49fe`（2026-07-18，建站回填）、`2026-07-19.json` 首次出现于 `1ec2e4d`（2026-07-21，arXiv 滞后两天）、`2026-07-22.json` 首次出现于 `b115219`（2026-07-23）。建站时回填的 07-12～07-17 统一落到 2026-07-18，**那就是它们真实的收录日，不是近似**。`data: backfill …` 这类不新增论文的 commit 不影响结果。

（放弃的备选：按 items 追加顺序 + `revisions[].n_papers` 切分。`reclassify_day()` 也写 revisions 但不增加篇数——07-21 的快照序列 `46 / 46 / 67` 里重复的 46 就是它留下的——必须特判才不会错位。）

**7.2 三个学术日期。** arXiv 论文的 `preprint` 直接用现有 `published`（本就是 v1 提交日）。ADS 论文：`preprint` 用 `external_ids.arxiv` 查 arXiv API；`accepted` / `published` 按 DOI 查 Crossref；两处都拿不到的回 ADS 按 bibcode 补查 `pubdate`（入库时未存）。随后计算 `archive_date`。

**7.3 `decision` 回填。** `review.stories` 按 paper_id 填回对应论文；watchlist 按条目结尾的 `（paper_id）` 拆回各自论文，`2026-07-19` 那两条无 id 的归给当天唯一那条 story。其余 core/related 记 `{level: "reject", reason: "迁移：v2 复核未入选"}`，**不重跑 LLM**；edge 记 `null`。

**7.4 产出与回滚。** 写出 `data/ingest/<收录日>.json`，删除 `data/daily/`，单独一个 commit。脚本依赖 git 历史与当前 `data/daily`，只能跑一次；回滚需同时 revert 代码与数据两个 commit。

**7.5 验收**（pytest，跑在迁移产物上）：1277 篇一篇不落；每篇都有 `ingested` 与 `archive_date`；每日 stories 总数与迁移前逐日一致；人工抽 5 篇核对日期链。

## 8. 测试

基线：改造前 `pytest -q` 为 110 passed。

- **`dates.py`（新，纯函数）**：ISO 与英文长格式都能解析，解析不了留空不猜；`published-print` 晚于 `created` 时取 `created`；月精度保留 `precision`，跨精度比较按当月 1 号；`archive_date` 取最早非空。
- **`daily_review` 拆分后**：`review_paper()` 只吃单篇、prompt 含预印本日与收录日；十连重试用"前 9 次坏 JSON、第 10 次好"的假 LLM 验；熔断用"连续 20 篇全败"验；`compose_review()` 传入一个**调用即抛异常**的 LLM 仍能跑通，以此证明它是纯函数。
- **`pipeline.sync()`**：往已有 144 篇的日子补录 1 篇，断言 LLM 调用次数为 1~2 次而非上百次；历史 ingest 文件内容哈希不变；跨批次 enrich 只合并日期与标识符；决策失败的论文照常入库并累加 `review_attempts`，第二层在下一轮补上，3 次后标 final。
- **渲染**：同一篇论文在收录日页与归档日页各出现一次；历史版本页等于 `ingested <= V` 过滤后的渲染（含当时的头条）；补录徽标只出现在非首版收录的卡片上；日期链缺项不显示、月精度不补日；现有密度分级与空态断言全部保留。
- **迁移脚本**：在临时 git 仓库夹具上造三个 commit，验证 `ingested` 重建精确到 commit。
- **端到端**：迁移后全量 `build_site`，Playwright 在 1440 / 414 两个宽度核对首页、一个归档日、一个历史版本、一个带补录徽标的页面。

## 9. 落地顺序与风险

1. `dates` 模块 + 解析测试（纯函数，零风险）
2. 数据模型加字段（`models.py` 读写兼容新旧格式）
3. `daily_review` 拆成 `review_paper` / `compose_review`，加重试与熔断
4. `store` + `pipeline.sync` 改 ingest-keyed 写入、跨批次 enrich、第二层补评
5. 迁移脚本 + 验收测试 → 执行迁移 → 单独 commit
6. 渲染层：两轴页面、归档页年月分组、版本下拉、补录徽标、日期链
7. 全量 rebuild + Playwright 核对 + `gh workflow run daily-review` 部署

**风险一**：第 4、5 步之间数据格式不兼容，中间状态不可部署，这两步必须连着做完再推。

**风险二**：迁移推送必须避开 cron。每天北京时间 10:00 workflow 自动运行；若它在迁移推送之后、代码部署之前触发，就会用旧代码往新布局上写。实操上挑跑批之后的时段推送，或临时停用 workflow。

**风险三**：`gh workflow run daily-review` 会重跑整条流水线。改造后重跑不再重复评审已有论文，成本比现在低，但首次跑批会对窗口内命中 seen-index 的论文做 Crossref enrich 查询，需确认 Crossref 无 token 限流下的实际耗时。
