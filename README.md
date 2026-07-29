# GECAM Daily Review

每天自动抓取 arXiv 预印本与 NASA ADS 新收录期刊论文，按 GECAM 科学画像打分、综述，并发布静态站。

## 本地运行

```bash
pip install -e ".[dev]"
export OPENCODE_API_KEY=sk-...
export ADS_API_TOKEN=...              # 可选；未设置时仅抓 arXiv
python scripts/list_models.py          # 确认模型 id，如与默认不符用 GDR_MODEL_* 环境变量覆盖
python scripts/run_daily.py --date 2026-07-17
python scripts/build_site.py             # 仅从已保存数据重建静态站，不访问网络或模型
open site/index.html
```

## 测试

```bash
pytest -q
```

## 部署

- 仓库 Settings → Pages → Source 选 **GitHub Actions**。
- 仓库 Settings → Secrets and variables → Actions 新增 `OPENCODE_API_KEY`；如需 ADS
  期刊数据源，再新增 `ADS_API_TOKEN`（在 ADS 账户中生成）。
- `.github/workflows/daily.yml` 每天 02:00 UTC（北京 10:00）自动运行，也可在 Actions 页手动 `Run workflow`。
- Vercel 自定义域名备线的隔离部署方案见 [`docs/vercel-backup.md`](docs/vercel-backup.md)。

站点字体已存放在 `static/fonts/` 并随静态页面同源发布，不依赖 Google Fonts。
需要升级字体版本时运行：

```bash
python scripts/vendor_fonts.py
```

## 架构

见 `docs/superpowers/specs/2026-07-18-gecam-daily-review-design.md`。数据 JSON 提交进 `data/`；渲染 HTML 作为 Pages 构件部署，不进 git。

数据源通过统一适配器合并。ADS 默认跨期刊查询命中高能暂现源与多信使主题的正式论文；可通过 `GDR_ADS_QUERY` 覆盖查询表达式。

主题赛道与编辑层级彼此独立：TDE、太阳耀斑、任务方法和多信使宇宙学等方向均可因直接服务团队目标而进入核心层；层级由直接性判断，优先级分数只负责层内排序。每日页不再复述篇数与固定主题分布，而是经两轮编辑复核筛选可由具体论文原题、原摘要支撑的 `BREAKING` / `HEADLINE`。每篇论文独立生成一个短 JSON 决策，只有入围论文才逐篇进入第二轮，最终由程序校验、合并和去重；不存在整日大 JSON。新闻简报、评论、更正等二手条目不能借用其报道对象的重要性入选。新闻不设主头条、不设数量名额，同一等级平级展示；无充分证据时明确显示“今日无通过复核的重大进展”。

头条区按密度分级排版：`BREAKING` 始终完整展示，`HEADLINE` 仅在当日无突发时给前两条完整展示，其余压缩为排序清单，避免重稿日连续排十条完整条目。`impact` 是正文级正文（无标签），`证据` 为脚注级支撑，`入选依据` 默认折叠；`继续观察` 的每条信号由程序附上被复核论文自己的 id，渲染为指向该论文的引用链接。

每篇论文携带四个日期（预印本、期刊接收、期刊刊出、本站收录）与一条一次性生成的编辑决策，
数据按收录日存放于 `data/ingest/<收录日>.json`，正常路径只新增文件、不改写历史。站点由此渲染
两条时间轴：`/news/<收录日>.html`（每日新闻，首页指向最新收录日）与 `/day/<归档日>.html`
（文献归档，归档日取预印本／接收／刊出中最早的一个）。归档日页面带版本条，可切换到任一历史
收录时刻的状态；最新版页面用徽标标出后续补录的论文。补录只为新论文调用模型，已有决策不再重算。
