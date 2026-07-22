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

主题赛道与编辑层级彼此独立：TDE、太阳耀斑、任务方法和多信使宇宙学等方向均可因直接服务团队目标而进入核心层；层级由直接性判断，优先级分数只负责层内排序。每日页不再复述篇数与固定主题分布，而是经两轮编辑复核筛选可由具体论文原题、原摘要支撑的 `BREAKING` / `HEADLINE`。新闻简报、评论、更正等二手条目不能借用其报道对象的重要性入选。新闻不设主头条、不设数量名额，同一等级平级展示；无充分证据时明确显示“今日无重大头条”。
