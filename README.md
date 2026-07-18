# GECAM Daily Review

每天自动抓取 arXiv 新文献，按 GECAM 科学画像打分、综述，并发布静态站。

## 本地运行

```bash
pip install -e ".[dev]"
export OPENCODE_API_KEY=sk-...
python scripts/list_models.py          # 确认模型 id，如与默认不符用 GDR_MODEL_* 环境变量覆盖
python scripts/run_daily.py --date 2026-07-17
open site/index.html
```

## 测试

```bash
pytest -q
```

## 部署

- 仓库 Settings → Pages → Source 选 **GitHub Actions**。
- 仓库 Settings → Secrets and variables → Actions 新增 `OPENCODE_API_KEY`。
- `.github/workflows/daily.yml` 每天 02:00 UTC（北京 10:00）自动运行，也可在 Actions 页手动 `Run workflow`。

## 架构

见 `docs/superpowers/specs/2026-07-18-gecam-daily-review-design.md`。数据 JSON 提交进 `data/`；渲染 HTML 作为 Pages 构件部署，不进 git。
