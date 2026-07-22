# Vercel 访问备线设计

## 目标

- GitHub Pages 在中国大陆访问异常时，保留一个使用自定义域名的境外入口。
- 抓取、模型判断与总结只在 GitHub Actions 运行一次。
- Vercel 从 `main` 中已经提交的 JSON 数据重新渲染静态网页，不接触模型或数据源密钥。
- 浏览器加载页面时不依赖 Google Fonts 或其他关键外部前端资源。

## 数据与构件

`data/daily/*.json` 与 `data/seen-index.json` 是持久、可审计的内容源，由每日 GitHub Actions 提交回 `main`。`site/` 是纯派生构件，不进入 Git：

```text
data/ + templates/ + static/ + renderer
                    │
                    ▼
                  site/
```

因此不需要额外的发布分支。历史内容由 JSON 与 Git 历史保存；任何一个提交都可以重新生成对应的完整静态站。

## 构建职责

```text
GitHub Actions
  抓取 arXiv/ADS + 模型处理
          │
          ├─ 纯静态渲染 ──> GitHub Pages artifact
          │
          └─ commit data/*.json ──> push main
                                      │
                                      ▼
Vercel Git integration
  从同一 main commit 执行纯静态渲染 ──> Vercel CDN
```

这里重复的只有约零点几秒的 Jinja 静态渲染。昂贵且可能非确定的抓取与模型处理不会在 Vercel 重复执行。

## 可复现构建

两个环境共用 `gdr.site_build.build_site()`：

- `scripts/run_daily.py` 在每日同步结束后调用它，供 GitHub Pages 使用。
- `scripts/build_site.py` 是 Vercel 和本地的纯渲染入口。
- 每次构建先删除旧 `site/`，避免已经删除的数据留下过期 HTML。
- `.python-version` 将托管构建固定到 Python 3.12，GitHub Actions 也使用 Python 3.12。
- `requirements-render.txt` 只包含渲染所需的固定版本 Jinja2 与 MarkupSafe。
- 测试会连续执行两次干净构建并比较所有输出文件的 SHA-256。

纯渲染只读取仓库内的 `data/`、`templates/` 与 `static/`，不读取 API key、不访问网络，也不写回数据。

## Vercel 配置

仓库根目录的 `vercel.json` 已定义：

```json
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "installCommand": "python -m pip install --disable-pip-version-check -r requirements-render.txt",
  "buildCommand": "PYTHONPATH=src python scripts/build_site.py",
  "outputDirectory": "site"
}
```

在 Vercel 中：

1. 导入公开仓库 `hx-guo/daily-review`。
2. Production Branch 选择 `main`，Framework Preset 选择 `Other`。
3. 不配置 `OPENCODE_API_KEY`、`ADS_API_TOKEN` 或任何 GitHub Actions secret。
4. 绑定 `review.example.com` 这类自定义子域名。
5. 若 DNS 托管在 Cloudflare，记录使用 **DNS only（灰云）**，不在 Vercel 前叠加代理。

GitHub Actions 每日推送新的数据提交后，Vercel Git integration 会自动构建并部署。仓库是公开仓库，自动化提交不会触发私有仓库的团队成员校验限制。

## 失败行为

| 故障 | 结果 |
| --- | --- |
| GitHub Pages 访问异常 | Vercel 自定义域名继续提供最后一次成功部署 |
| Vercel 构建异常 | GitHub Pages 部署不受影响 |
| GitHub Actions 抓取或模型失败 | 不产生新数据提交；两个站继续提供旧版本 |
| Vercel 暂时无法拉取 GitHub | Vercel 保留旧部署，恢复后可重试该 Git commit |
| 渲染依赖或模板改变 | 确定性测试与两个托管环境的构建会暴露差异 |

## 上线顺序

1. 将本方案相关提交推送到 `main`。
2. 在 Vercel 导入仓库并完成第一次构建。
3. 绑定自定义域名，但暂不对外公布。
4. 连续观察三次日报，比较 GitHub Pages 与 Vercel 页面日期和内容。
5. 分别使用移动、联通、电信网络验证自定义域名、CSS 和 WOFF2 请求。

## 官方参考

- [Vercel：从中国大陆访问 Vercel 托管站点](https://vercel.com/kb/guide/accessing-vercel-hosted-sites-from-mainland-china)
- [Vercel：部署 Git 仓库](https://vercel.com/docs/git)
- [Vercel：配置构建](https://vercel.com/docs/builds)
- [Vercel：配置自定义域名](https://vercel.com/docs/domains/set-up-custom-domain)
