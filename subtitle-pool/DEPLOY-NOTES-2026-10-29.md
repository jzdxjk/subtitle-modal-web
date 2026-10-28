# 海南鸡字幕池上线 Runbook（待 D1 额度重置）

## 阻塞

2026-10-28 实测 D1 仍返回 `code: 7500`（免费档每日行读取上限）。重置时间：UTC 零点，
即北京时间 **2026-10-29 08:00**。重置前不要重复跑迁移，避免继续消耗。

## 回滚点

- 当前线上 Worker 版本：`abf771b7-f050-4efb-b405-fb2ce46670e2`（创建于 2026-10-28T04:30:59Z）
- 旧线上打包源码参考：`E:\E盘codex\字幕云翻译\.tmp\codex-pool-deployed\index.live-after.js`
- 回滚：`wrangler versions deploy`（按版本 ID 部署回 `abf771b7…`）

## 上线顺序（严格）

在 `subtitle-pool/` 目录、绑定正确 Cloudflare 账号后执行：

```powershell
.\node_modules\.bin\wrangler.cmd d1 migrations list chickenrice-pool --remote
.\node_modules\.bin\wrangler.cmd d1 migrations apply chickenrice-pool --remote   # 先应用 0003_pool_stats
.\node_modules\.bin\wrangler.cmd deploy                                          # 再发布 Worker
```

先迁移后发布：新 Worker 的 `/api/v1/stats` 依赖 `pool_stats` 表，未迁移会 500。

## 发布后验收

- `GET /api/v1/stats` 返回 200，`subtitle_count` 为非负整数。
- 搜索响应带 `X-Pool-Cache: MISS`，相同请求第二次为 `HIT`。
- `wrangler tail` 或 D1 指标确认重复请求的 `rows_read` 明显下降。
- `/health` 仍 200；搜索在额度恢复后返回 200 而非 500。

## 不动项

不改 Emby `ServiceUrl`；不改鉴权/限流；不改第三方 MDC-NG 容器源码。
