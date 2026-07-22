# Vercel 访问备线设计

## 目标

- GitHub Pages 在中国大陆访问异常时，保留一个使用自定义域名的境外入口。
- 每日流水线只生成一次 `site/`，GitHub Pages 与 Vercel 发布同一份不可变构件。
- 任一托管平台发布失败时，不阻断另一平台发布。
- 浏览器加载页面时不依赖 Google Fonts 或其他可能被阻断的关键前端资源。

这条备线解决的是“站点能否访问”。如果 GitHub Actions 整体不可用，两边仍能访问最后一次成功发布的版本，但不会产生新的日报。独立的内容生产备线应另设香港主机定时任务，并保持冷备，避免两个任务同时写入 `data/`。

## 推荐拓扑

```text
GitHub Actions: build
  ├─ 生成并测试 site/
  ├─ pages artifact ─────────> GitHub Pages
  └─ generic site artifact ──> deploy-vercel job ──> Vercel Edge CDN

公开入口
  ├─ 现有 GitHub Pages URL
  └─ review-backup.example.com ──CNAME──> Vercel 项目专用目标
```

Vercel 只接收已经生成的静态文件，不连接仓库、不重复运行抓取、总结或渲染流程。这样不会重复消耗 API 配额，也不会产生数据提交竞争。

## Vercel 项目设置

1. 在 Vercel 创建空项目，Framework Preset 选择 `Other`，关闭 Git 自动部署。
2. 绑定 `review-backup.example.com` 这类独立子域名。
3. 按 Vercel 项目域名页给出的专用 CNAME 配置 DNS。若 DNS 托管在 Cloudflare，记录必须使用 **DNS only（灰云）**，不在 Vercel 前叠加 Cloudflare 代理。
4. 保留 Vercel 自动签发的 HTTPS 证书；不要把 `*.vercel.app` 地址作为对外入口。

使用子域名而不是裸域名，可以让 Vercel 通过 CNAME 调整边缘路由，也便于以后把备线迁移到其他厂商。Vercel 官方说明，自定义域名相较 `*.vercel.app` 更不容易在中国大陆被拦截，但境外托管仍无法承诺大陆可用性。

## 流水线拆分

在 `.github/workflows/daily.yml` 中保留现有 `build` 与 GitHub Pages `deploy`，再增加一个与 Pages 部署并列的 `deploy-vercel` job：

1. `build` 在生成 `site/` 后，除 Pages 专用 artifact 外，再上传一个普通 `site` artifact。
2. `deploy-vercel` 使用 `needs: build`，下载普通 artifact。
3. 将 artifact 放入 Vercel Build Output API 的 `.vercel/output/static/`，同时生成 `.vercel/output/config.json`：

   ```json
   { "version": 3 }
   ```

4. 使用 Vercel CLI 执行预构建部署：

   ```bash
   npx vercel deploy --prebuilt --prod --archive=tgz --token="$VERCEL_TOKEN"
   ```

5. 部署后请求部署 URL 的 `/index.html` 和 `/static/fonts/fonts.css`，两者均返回 `200` 才算成功。

`deploy-vercel` 与 GitHub Pages `deploy` 必须是并列 job，不能把 Vercel 上传步骤插在现有 `build` job 尾部。否则 Vercel 故障会让 `build` 失败，反过来阻断 GitHub Pages 主线。

## 凭据

在 GitHub 的 `vercel-production` Environment 中保存：

- `VERCEL_TOKEN`：只授予目标 Vercel scope 所需权限的部署 token。
- `VERCEL_ORG_ID`：目标账户或团队 ID。
- `VERCEL_PROJECT_ID`：空项目的 project ID。

job 通过环境变量读取三个值，不提交 `.vercel/project.json`，也不把 token 写入日志。Environment 可以增加部署分支限制，只允许 `main` 发布生产备线。

## 失败行为

| 故障 | 结果 | 处理 |
| --- | --- | --- |
| GitHub Pages 访问异常 | Vercel 自定义域名继续提供最后版本 | 向用户发布备线 URL |
| Vercel 发布失败 | GitHub Pages 部署不受影响 | 单独重跑 `deploy-vercel` |
| GitHub Actions 暂停 | 两个平台继续提供旧版本 | 恢复后补跑每日流程 |
| 自定义域名解析异常 | Vercel 默认域名可能也不适合大陆访问 | 修复 DNS；GitHub Pages 仍是独立入口 |
| 页面可达但大陆加载慢 | 检查外部字体、脚本和图片 | 关键资源全部同源；从大陆网络做探测 |

## 上线顺序

1. 先创建 Vercel 项目和自定义域名，取得三个凭据值。
2. 实现独立 `deploy-vercel` job，但暂不把备线 URL 对外发布。
3. 连续观察三次定时日报，比较 GitHub Pages 与 Vercel 页面的日期和文件哈希。
4. 分别使用移动、联通、电信网络验证自定义域名、CSS 和 WOFF2 请求。
5. 验证通过后发布备线地址；是否升级为主入口另行决定。

## 官方参考

- [Vercel：从中国大陆访问 Vercel 托管站点](https://vercel.com/kb/guide/accessing-vercel-hosted-sites-from-mainland-china)
- [Vercel：配置自定义域名](https://vercel.com/docs/domains/set-up-custom-domain)
- [Vercel：Build Output API](https://vercel.com/docs/build-output-api)
- [Vercel CLI：deploy](https://vercel.com/docs/cli/deploy)
