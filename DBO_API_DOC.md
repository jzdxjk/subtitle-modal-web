# DB Online API 接口文档

> **DBO 服务**: `http://<your-dbo-host>:9090` | **标题**: "DB Online - 私人影片订阅系统"  
> **API Key**: `<your-api-key>` (通过 `X-API-Key` 请求头传递)  
> **数据库**: PostgreSQL | **后端语言**: Go  
> **文档版本**: v2 | 生成时间: 2026-06-28 | 基于 DBO 前端 JS 逆向 + 全流程实测验证

---

## ⚡ 快速开始（3 步拿到磁力链接）

```bash
# 1. 登录获取 session cookie
curl -c cookies.txt -H "Content-Type: application/json" \
     -H "X-API-Key: <your-api-key>" \
     -d '{"password":"<dbo登录密码>"}' \
     "http://<your-dbo-host>:9090/api/auth/login"
# → {"success":true,"data":{"token":"eyJ...","expires_in":2592000}}

# 2. 按番号搜索（不需要登录）
curl -H "X-API-Key: <your-api-key>" \
     "http://<your-dbo-host>:9090/api/search?q=SSIS-001&limit=1"
# → 返回 movie.number, magnets_count, cover_url 等

# 3. 获取影片详情（含完整磁力链接 + ED2K）
curl -b cookies.txt -H "X-API-Key: <your-api-key>" \
     "http://<your-dbo-host>:9090/api/video/SSIS-001"
# → 返回 magnets[] 数组，每条包含 magnet 链接、size_mb、tags、date
```

> **⚠️ 重要**: `/api/video/{code}` 的路径参数是**番号**（如 `SSIS-001`），不是搜索返回的内部 `id`。

---

## 认证体系

DBO 使用双层认证：

| 层级 | 方式 | 适用范围 |
|------|------|----------|
| **API Key** | Header `X-API-Key: <your-api-key>` | `/api/search`、`/api/ready`、`/api/health`、`/api/config`、`/api/auth/status`、`/api/auth/login` |
| **Session Cookie** | `-c cookies.txt` (login 后获取) | `/api/video/*`、`/api/download`、`/api/users/*`、`/api/subs/*` 等绝大部分接口 |

**认证状态查询** (公开):
```
GET /api/auth/status
→ {"success":true,"data":{"enabled":true,"configured":true,"password_login_disabled":false,"token_expire_hours":720,...}}
```

---

## 1. 搜索 & 影片发现（公开 / API Key）

### 1.1 搜索影片

```
GET /api/search?q={keyword}&limit={n}&page={p}&movie_type={type}&movie_sort_by={sort}&movie_filter_by={filter}
```

**参数**:
| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `q` | ✅ | - | 搜索关键词（番号/标题/资源名） |
| `limit` | ❌ | 24 | 每页数量 |
| `page` | ❌ | 1 | 页码 |
| `movie_type` | ❌ | `all` | 影片类型: `all`, `censored`, `uncensored`, `western`, `fc2`, `anime` |
| `movie_sort_by` | ❌ | `relevance` | 排序: `relevance`, `release_date`, `update`, `magnets_count` |
| `movie_filter_by` | ❌ | `all` | 筛选: `all`, `has_magnets`, `has_subtitles`, `no_resources`, `single_actor` |
| `type` | ❌ | `movie` | 搜索类型: `movie`, `actor` |

**响应示例** (实测):
```json
{
  "success": true,
  "data": {
    "movies": [
      {
        "id": "ZY5eq",
        "number": "SSIS-001",
        "title": "刺激您五感的三上悠亞頂級自慰協助",
        "origin_title": "一ヶ月間の禁欲の果てに...",
        "cover_url": "/api/image?url=https://tp.spfcas.com/rhe951l4q/covers/zy/ZY5eq.jpg",
        "thumb_url": "/api/image?url=https://tp.spfcas.com/rhe951l4q/small_covers/zy/ZY5eq.jpg",
        "duration": 150,
        "release_date": "2021-02-19",
        "magnets_count": 26,
        "new_magnets": false,
        "has_cnsub": true,
        "has_preview_images": true,
        "has_preview_video": true,
        "can_play": true,
        "play_subtitle": 1,
        "ranking": 0,
        "library": {"in_library": false}
      }
    ]
  },
  "source": "api"
}
```

### 1.2 最新影片

```
GET /api/latest?page={n}&limit={n}&type={type}&sort_by={sort}&filter_by={filter}
```

`filter_by` 可选: `all`, `magnets`, `subtitles`, `no_resources`, `single_actor`

### 1.3 搜索演员

```
GET /api/search/actors?q={keyword}
```

### 1.4 排行榜

```
GET /api/rankings?period={period}&type={type}
GET /api/top250?type={type}&type_value={val}&page={n}&limit={n}
```

---

## 2. 认证接口

### 2.1 登录 ✅ 已实测

```
POST /api/auth/login
Content-Type: application/json
X-API-Key: <your-api-key>

{"password": "<dbo登录密码>"}
```

**实测响应**:
```json
{
  "success": true,
  "data": {
    "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "expires_in": 2592000
  }
}
```

- 同时会设置 `Set-Cookie`，后续请求用 `curl -b cookies.txt` 携带
- token 有效期 30 天 (2592000 秒)
- 登录接口本身也支持纯 API Key 访问（不需要预先登录）

### 2.2 登出

```
POST /api/auth/logout
```

### 2.3 JavDB Token 获取

```
POST /api/get-token
Content-Type: application/json

{"username": "<javdb_user>", "password": "<javdb_pass>"}
```

### 2.4 其他认证接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/auth/verify` | 验证当前 session |
| POST | `/api/auth/totp/begin` | TOTP 两步验证开始 |
| POST | `/api/auth/totp/finish` | TOTP 两步验证完成 |
| DELETE | `/api/auth/totp` | 删除 TOTP |
| POST | `/api/auth/webauthn/register/begin` | WebAuthn 注册开始 |
| POST | `/api/auth/webauthn/register/finish` | WebAuthn 注册完成 |
| POST | `/api/auth/webauthn/login/begin` | WebAuthn 登录开始 |
| POST | `/api/auth/webauthn/login/finish` | WebAuthn 登录完成 |

---

## 3. 影片详情 & 磁力链接 🔥（需登录 Session）

### 3.1 影片详情（含完整磁力数据）✅ 已实测

```
GET /api/video/{code}?refresh={true|false}
```

> **路径参数 `{code}` 是番号**（如 `SSIS-001`），不是搜索返回的内部 `id`。

**实测响应** (SSIS-001):
```json
{
  "success": true,
  "data": {
    "code": "SSIS-001",
    "title": "刺激您五感的三上悠亞頂級自慰協助 讓腦袋充滿快感的6個療癒勃起場景",
    "overview": "S1瘦身美女演员的豪华共演情感剧作！...",
    "video_id": "ZY5eq",
    "date": "2021-02-19",
    "duration": 150,
    "score": 4.43,
    "cover_url": "/api/image?url=https://tp.spfcas.com/...",
    "thumb_url": "/api/image?url=https://tp.spfcas.com/...",
    "previews": ["/api/image?url=...", ...],
    "director": {"external_id": "rqk", "name": "苺原"},
    "maker": {"external_id": "7R", "name": "S1 NO.1 STYLE"},
    "series": {"external_id": "ZvDJ", "name": "一ヶ月間の禁欲の果てに..."},
    "categories": [
      {"external_id": "91", "name": "美乳"},
      {"external_id": "348", "name": "无码破解"}
    ],
    "actors": [
      {"external_id": "AGR0", "name": "乙白さやか", "gender": "♀"},
      {"external_id": "A5yq", "name": "葵つかさ", "gender": "♀"}
    ],

    "magnets": [
      {
        "name": "SSIS-001-UC.torrent.无码破解",
        "size_mb": 6480,
        "file_count": 1,
        "date": "2023-11-18 00:00:00",
        "magnet": "magnet:?xt=urn:btih:fcef4eb87ac04a85c5285f8377b2856e9e40b9f1",
        "tags": ["高清", "破解", "字幕"],
        "site": "JavDB",
        "source_key": "javdb"
      },
      {
        "name": "ssis-001-uncensored.torrent 无码破解",
        "size_mb": 7040,
        "file_count": 3,
        "date": "2021-07-13 00:00:00",
        "magnet": "magnet:?xt=urn:btih:0960e54f96706714265f3a2139c1cdda526a1eb5",
        "tags": ["高清", "破解"],
        "site": "JavDB",
        "source_key": "javdb"
      }
      // ... 共 26 条磁力链接
    ],

    "ed2ks": [
      {
        "name": "[SSIS-001].Bluray.Upscaled.mkv",
        "size_mb": 12958.094,
        "date": "2026-01-28 09:53:02",
        "ed2k": "ed2k://|file|[SSIS-001].Bluray.Upscaled.mkv|13587545881|164C197568012C9F7B748D3300401E4A|...",
        "tags": ["高清", "UHD"],
        "site": "",
        "source_key": "ed2k",
        "source_user_id": 535166,
        "source_username": "11qwerty"
      }
    ],

    "library": {"in_library": false}
  },
  "source": "database"
}
```

**magnets 数组字段说明**:
| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 资源名称（含清晰度/字幕/破解等标注） |
| `size_mb` | number | 文件大小 (MB) |
| `file_count` | number | 文件数量 (0=未知) |
| `date` | string | 资源发布日期 |
| `magnet` | string | **磁力链接** (magnet:?xt=urn:btih:...) |
| `tags` | array | 标签: 高清/破解/字幕/UHD 等 |
| `site` | string | 来源站点 (JavDB 等) |
| `source_key` | string | 来源类型: `javdb` / `ed2k` |

### 3.2 按内部 ID 查询

```
GET /api/video/id/{encoded_id}?refresh={true|false}
GET /api/v/{path}
```

### 3.2 用户评分

```
GET /api/video/{id}/score
PUT /api/video/{id}/score   Body: {"score": 1-5}
```

### 3.3 影片下载历史

```
GET /api/video/{id}/download-history
```

---

## 4. 磁力 & 资源相关 🔥（需登录 Session）

### 4.1 用户提交的资源（磁力/ED2K）

```
GET /api/users/{username}/resources?page={n}&limit={n}&username={filter_user}
```

获取指定用户或所有用户提交的磁力/ED2K 资源列表。

### 4.2 资源元数据

```
POST /api/users/resources/metadata
Body: {"items": [{"id": "...", "type": "magnet"}, ...]}
```

### 4.3 外部磁力源

```
GET /api/external-magnets/custom/{encoded_id}     # 自定义磁力库
GET /api/external-magnets/nyaa/{encoded_code}     # Nyaa 磁力源
GET /api/external-magnets/stats                   # 磁力源统计
```

### 4.4 下载磁力链接

```
POST /api/download
Content-Type: application/json

{
  "urls": ["magnet:?xt=urn:btih:..."],
  "downloader": "aria2" | "qbittorrent" | "thunder" | "pan115",
  "save_path": "/downloads/movie_name",
  "video_info": {
    "code": "SSIS-001",
    "title": "...",
    ...
  },
  "record_resources": [...]
}
```

### 4.5 下载记录

```
GET /api/download-records?resource_types=magnet,ed2k&page={n}&limit={n}
DELETE /api/download-records
```

---

## 5. 下载器管理（需登录 Session）

### 5.1 下载器列表

```
GET /api/downloaders
```

### 5.2 Aria2

```
GET  /api/aria2/tasks
POST /api/aria2/action    # 操作任务 (pause/resume/remove)
POST /api/aria2/test      # 测试连接
```

### 5.3 qBittorrent

```
GET  /api/qbittorrent/tasks?filter={all|downloading|completed|...}
POST /api/qbittorrent/action
POST /api/qbittorrent/test
```

### 5.4 迅雷

```
GET  /api/thunder/tasks
POST /api/thunder/action
POST /api/thunder/select-options
POST /api/thunder/test
```

### 5.5 115 网盘

```
GET  /api/pan115/tasks?filter={}&page={n}&page_size={n}
POST /api/pan115/directories
POST /api/pan115/tasks/clear
POST /api/pan115/test
GET  /api/pan115/test
```

---

## 6. 订阅系统（需登录 Session）

### 6.1 影片订阅

```
GET    /api/subs                          # 列出订阅
POST   /api/subs                          # 创建订阅
PUT    /api/subs/{id}                     # 更新订阅
DELETE /api/subs/{id}                     # 删除订阅
POST   /api/subs/check/{id}              # 检查单个订阅
POST   /api/subs/check                   # 批量检查  Body: {"codes": [...]}
POST   /api/subs/status                  # 批量状态  Body: Ww(e)
POST   /api/subs/sync                    # 同步在线订阅
```

### 6.2 订阅配置

```
GET  /api/subs/auto-sync
PUT  /api/subs/auto-sync
GET  /api/subs/preset
PUT  /api/subs/preset
POST /api/subs/preset/overwrite
GET  /api/subs/matrix?...
GET  /api/subs/ranking
PUT  /api/subs/ranking
GET  /api/subs/live-sub
GET  /api/subs/watched
GET  /api/subs/tags?filter_by={}&page={n}&limit={n}&sort_by={}&order_by={}
```

### 6.3 订阅分享

```
POST /api/subs/share/export
POST /api/subs/share/analyze
POST /api/subs/share/import
```

### 6.4 订阅日志

```
GET    /api/subs/logs
DELETE /api/subs/logs?date={date}
```

---

## 7. 演员订阅

```
GET    /api/actor-subs
POST   /api/actor-subs
GET    /api/actor-subs/{id}
PUT    /api/actor-subs/{id}
DELETE /api/actor-subs/{id}
POST   /api/actor-subs/check/{id}
POST   /api/actor-subs/check            Body: {"actor_ids": [...]}
POST   /api/actor-subs/run
POST   /api/actor-subs/run/{id}
POST   /api/actor-subs/{id}/videos/skip              Body: {"codes": [...]}
POST   /api/actor-subs/{id}/videos/restore           Body: {"codes": [...]}
PUT    /api/actor-subs/{id}/videos/{video_id}
```

---

## 8. 系列订阅

```
GET    /api/series-subs
POST   /api/series-subs
GET    /api/series-subs/{id}
PUT    /api/series-subs/{id}
DELETE /api/series-subs/{id}
POST   /api/series-subs/check/{id}
POST   /api/series-subs/check            Body: {"external_ids": [...], "sub_type": "..."}
POST   /api/series-subs/run
POST   /api/series-subs/run/{id}
POST   /api/series-subs/{id}/videos/skip
POST   /api/series-subs/{id}/videos/restore
PUT    /api/series-subs/{id}/videos/{video_id}
```

---

## 9. 字幕（需登录 Session）

```
GET  /api/subtitle/find/{code}                           # 查找字幕
GET  /api/subtitle/download?id={id}                      # 下载字幕 (blob)
GET  /api/subtitle/preview?id={id}&enc={encoding}        # 预览字幕
GET  /api/subtitle/external/search/{code}                # 外部字幕搜索
GET  /api/subtitle/external/download?url={}&name={}&ext={}
GET  /api/subtitle/external/preview?url={}&name={}&enc={}
GET  /api/subtitle/stats
GET  /api/subtitle/progress
POST /api/subtitle/scan?mode={incremental|full}         # 扫描字幕
POST /api/subtitle/clear                                 # 清除字幕缓存
```

---

## 10. 分类 & 选项

```
GET /api/options/categories            # 所有分类
GET /api/options/categories/{id}       # 特定分类的演员
GET /api/options/actors                # 演员选项
GET /api/actors?type={0|1|2}          # 演员列表
GET /api/actors/{id}/movies?page={}&limit={}
GET /api/directors/{id}/movies
GET /api/makers/{id}/movies
GET /api/publishers/{id}/movies
GET /api/series/{id}/movies
GET /api/lists/{id}/movies
GET /api/lists/related?movie_id={id}&page={n}&limit={n}
```

---

## 11. 黑名单

```
GET    /api/blacklist
POST   /api/blacklist              Body: {...}
DELETE /api/blacklist/{code}
DELETE /api/blacklist              Body: {"video_codes": [...]}
POST   /api/blacklist/test         Body: {"video_codes": [...]}
```

---

## 12. 媒体库（Emby/Jellyfin/Plex）

```
POST /api/emby/test              # 测试 Emby 连接
POST /api/emby/libraries         # 获取 Emby 库列表
POST /api/jellyfin/test
POST /api/jellyfin/libraries
POST /api/fnmedia/test
POST /api/fnmedia/libraries
POST /api/clouddrive2/test
GET  /api/library/cache/stats
POST /api/library/cache/refresh
GET  /api/library/cache/refresh/progress
GET  /api/library/stream/{id}
```

---

## 13. 系统 & 配置

```
GET  /api/ready                              # 健康检查
GET  /api/health                             # 健康状态 (200-600)
GET  /api/metrics                            # 指标
GET  /api/stats                              # 统计
GET  /api/config                             # 读取配置
PUT  /api/config                             # 更新配置
GET  /api/logs                               # 日志
GET  /api/setup/status                       # 安装状态
POST /api/setup/test-connection              # 测试数据库连接
POST /api/setup/list-databases               # 列出数据库
POST /api/setup/create-database              # 创建数据库
POST /api/setup/initialize                   # 初始化
POST /api/setup/restart                      # 重启
```

---

## 14. 其他

```
GET  /api/login/covers?limit={n}             # 登录页封面
POST /api/url-presets/probe                  # URL 预设探测
POST /api/openlist/test                      # OpenList 测试
POST /api/openlist/tool-paths                # OpenList 工具路径
GET  /api/following/presets                  # 关注预设
POST /api/following/presets
PUT  /api/following/presets/{id}
DELETE /api/following/presets/{id}
PUT  /api/following/presets/reorder
GET  /api/following/users                   # 关注的用户
GET  /api/following/users/{id}
POST /api/following/users
DELETE /api/following/users                  Body: {"user_ids": [...]}
GET  /api/recommend?page={n}&limit={n}      # 推荐
POST /api/top250/subscribe
GET  /api/review-probe-history
GET  /api/telegram/test-notification
POST /api/ai/models
POST /api/ai/test
GET  /api/settings/player
PUT  /api/settings/player
POST /api/scheduler/cancel
POST /api/scheduler/cancel-queued            Body: {"taskId": "..."}
GET  /api/image/stats
DELETE /api/image/cache
POST /api/search/image?target=actor          # 演员图片搜索
GET  /api/videos?page={n}&pageSize={n}&sort_by={}&order_by={}&...
GET  /api/videos/filter?...
POST /api/videos/batch/delete                Body: {"codes": [...]}
POST /api/videos/batch/recollect             Body: {"codes": [...]}
POST /api/videos/recheck                     Body: {...}
```

---

## 对接建议：获取磁力链接的最佳路径 ✅ 已实测验证

```
┌─────────────────────────────────────────────────────────┐
│  1. POST /api/auth/login  {"password":"..."}            │
│     → 获取 session cookie (有效期 30 天)                  │
│                                                         │
│  2. GET  /api/search?q={番号}                            │
│     → 拿到 magnets_count, cover_url 等（无需登录）         │
│                                                         │
│  3. GET  /api/video/{番号}   (带 cookie)                 │
│     → 拿到完整 magnets[] + ed2ks[] 数组                  │
│     → 每条包含 magnet 链接、size_mb、tags、date            │
│                                                         │
│  4. POST /api/download       (带 cookie)                 │
│     → 推送磁力到 aria2/qbittorrent/迅雷/115              │
└─────────────────────────────────────────────────────────┘
```

**关键点**:
- `/api/video/{番号}` 的路径参数用**番号**（如 `SSIS-001`），不用内部 `id`
- 搜索是公开的（只需 API Key），影片详情需要登录 session
- Token 有效期 30 天，可以缓存复用，不用每次都登录
- 搜索返回的 `magnets_count` 和视频详情返回的 `magnets[]` 数量一致
