# 字幕源直连搜索 API（海南鸡 / 迅雷）

面向需要跳过 Emby、直接搜索和下载字幕的工具或脚本。本文按「字幕助手 1.0.0.3」的实际调用行为整理，并于 2026-10-27 对线上接口做过只读验证。

## 快速对照

| 项目 | 海南鸡字幕 | 迅雷字幕 |
| --- | --- | --- |
| 服务性质 | 自建/共享字幕池，以中文为主 | 迅雷公开字幕检索 |
| 基址 | `https://chickenrice-subtitle-pool.jzdxjk.workers.dev` | `https://api-shoulei-ssl.xunlei.com` |
| 搜索接口 | `GET /api/v1/subtitles/search` | `GET /oracle/subtitle?name=<番号>` |
| 搜索/下载鉴权 | 不需要 | 不需要 |
| 返回特点 | JSON，含时长、大小、SHA256、下载路径 | JSON，含候选 URL；`duration` 经常为 0，需自行解析 |
| 推荐用途 | 首选，元数据完整可直取 | 补漏，候选多但需要下载后解析 |

结论：优先查海南鸡拿结构化结果，再用迅雷补漏；迅雷的时长必须以字幕文件时间轴为准，不能信任接口里的 `duration`。

## 1. 先把番号解析成别名

两个源都按番号匹配。搜索前从文件名或 `MediaPath` 提取 stem（去掉扩展名），再生成别名。字幕助手使用的规则在 `emby-unified-plugin/Core/MediaIdentifier.cs`。

常见等价写法：

| 输入 | 建议同时查询的别名 |
| --- | --- |
| `FC2-1234567` / `FC2-PPV-1234567` | `FC2-1234567`、`FC2-PPV-1234567`、`FC2PPV-1234567` |
| `MIUM-00123` | `MIUM-00123`、`300MIUM-00123` |
| `010123_001` | `010123-001`、`010123_001` |
| `HEYZO-1234` | `HEYZO-1234`、`HEYZO_1234`、`HEYZO1234` |
| `N1234` | `N1234`、`N-1234`、`N_1234` |
| `ABP-192` | `ABP-192` |

实用规则：

- 先剔除文件名里的站点域名、`CD`/`PART`/`DISC` 分片标记；工作番号本身不要带 `-CD1`。
- 仅当 stem 中能解析出唯一番号时才去搜索，避免把普通单词误当番号。
- 海南鸡 `match=work` 模式要求每个 `codes` 都是合法番号；只要有一个非法，整个请求返回 400。因此发送前先过滤掉无效别名。
- 自动补全不要改写媒体库顺序；这里只影响“查哪个源”，不涉及来源排序。

## 2. 海南鸡字幕（ChickenRice Pool）

### 2.1 搜索

```
GET {base}/api/v1/subtitles/search
```

推荐参数（工作模式，合并别名，忽略请求中的 CD 后缀）：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `match` | 是 | 固定 `work` |
| `codes` | 是 | 可重复，多个别名 |
| `duration` | 否 | 视频时长（秒，1–86400），用于按接近程度排序 |

```text
/api/v1/subtitles/search?match=work&codes=MIUM-00123&codes=300MIUM-00123&duration=7200
```

旧版单番号模式（保留兼容）：

| 参数 | 说明 |
| --- | --- |
| `code` | 单个番号，按精确规范化匹配 |
| `duration` | 可选，秒 |
| `limit` | 可选，1–200，默认 200；只在单番号模式生效 |

`match=work` 模式忽略 `limit`，会返回全部有效候选；调用方自己截断展示数量。

### 2.2 响应

下面是字段示例（数值为占位，不是真实记录）：

```json
{
  "code": "ABP-192",
  "items": [
    {
      "id": "0b6c2f3e-7a51-4d8e-9f0a-2b8c6d4e1f23",
      "code": "ABP-192-CD1",
      "canonical_code": "abp-192-cd1",
      "language": "zh",
      "format": "srt",
      "duration_seconds": 6364,
      "size_bytes": 71257,
      "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
      "uploaded_at": 1730000000000,
      "download_url": "/api/v1/subtitles/0b6c2f3e-7a51-4d8e-9f0a-2b8c6d4e1f23/download"
    }
  ]
}
```

说明：

- `code` 是本次第一个规范化后的别名，不保证等于你传入的第一个原样字符串。
- 没有命中时仍返回 HTTP 200，`items` 为 `[]`。
- 服务端排序：已知时长的优先；然后按 `abs(duration_seconds - duration)` 升序；再按 `size_bytes` 降序、`uploaded_at` 降序。
- 响应带 `Cache-Control: public, max-age=30`，可缓存 30 秒。
- 仅收录 SRT / ASS / SSA，且上传内容要求中文。

### 2.3 下载

```
GET {base}{download_url}
```

返回原始字幕字节（不包 JSON）。响应头：

- `Content-Type`：`text/plain; charset=utf-8`（SRT）或 `text/x-ssa; charset=utf-8`（ASS/SSA）
- `Content-Disposition`：附件文件名
- `ETag`、`X-Content-SHA256`：内容 SHA256

下载后建议校验 `sha256` 与搜索结果一致。

### 2.4 错误

| HTTP | `error` | 含义 |
| --- | --- | --- |
| 400 | `invalid_code` | 番号缺失或某个别名非法 |
| 400 | `invalid_duration` | `duration` 不是 1–86400 的有限数字 |
| 404 | `not_found` | 路由不存在 |
| 500 | `internal_error` | 服务端异常 |

搜索和下载是公开接口，不需要 Bearer。上传需要 `UPLOAD_KEY`，删除需要 `ADMIN_KEY`，与本文的搜索场景无关，不要在任何客户端里内置这些密钥。

### 2.5 调用示例

PowerShell：

```powershell
$base = "https://chickenrice-subtitle-pool.jzdxjk.workers.dev"
$codes = @("MIUM-00123", "300MIUM-00123")
$query = ($codes | ForEach-Object { "codes=" + [uri]::EscapeDataString($_) }) -join "&"
$result = Invoke-RestMethod "$base/api/v1/subtitles/search?match=work&$query&duration=7200"
$result.items | Select-Object code, format, language, duration_seconds, size_bytes, sha256, download_url

$item = $result.items | Select-Object -First 1
if ($item) { Invoke-WebRequest ($base + $item.download_url) -OutFile ("subtitle." + $item.format) }
```

curl：

```bash
curl -sS "https://chickenrice-subtitle-pool.jzdxjk.workers.dev/api/v1/subtitles/search?match=work&codes=MIUM-00123&codes=300MIUM-00123&duration=7200"
```

## 3. 迅雷字幕

### 3.1 搜索

```
GET https://api-shoulei-ssl.xunlei.com/oracle/subtitle?name=<番号>
```

每个别名单独请求一次，然后合并结果。示例：

```
https://api-shoulei-ssl.xunlei.com/oracle/subtitle?name=ABP-192
```

线上实测返回（节选，2026-10-27）：

```json
{
  "code": 0,
  "data": [
    {
      "gcid": "C085376F32E2E02578202FAE3D6400DCB7E0924C",
      "cid": "C085376F32E2E02578202FAE3D6400DCB7E0924C",
      "url": "https://subtitle.v.geilijiasu.com/C0/85/C085376F32E2E02578202FAE3D6400DCB7E0924C.srt",
      "ext": "srt",
      "name": "ABP-192.XLSUB.srt",
      "duration": 0,
      "languages": [""],
      "extra_name": "（网友上传）"
    }
  ],
  "result": "ok"
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `code` | `0` 表示成功；非 0 视为无结果 |
| `data[]` | 候选列表 |
| `name` | 展示名，通常包含番号 |
| `url` | 字幕下载地址（可能是 SRT/ASS/SSA，也可能是 ZIP） |
| `ext` | 未解析前的扩展名 |
| `duration` | 字幕助手按毫秒处理；**线上经常为 0，不可作为真实时长** |
| `languages` | 语言提示数组，常见空字符串 |
| `extra_name` / `extraname` | 额外名称/来源，可用于匹配番号 |
| `cid` / `gcid` | 内部标识；**不要用来去重**，不同文件可能相同 |

注意：接口无鉴权，但属于第三方公开服务，可能限流、改字段或失效。请设置超时（插件默认 15 秒）、限制并发并做缓存。

### 3.2 必须做的后处理

1. 对每个别名各查一次，合并 `data`。
2. 只保留 `code` / `name` + `extra_name`（或 `extraname`）能匹配目标番号的候选，拒绝错号结果。
3. 按 `url` 去重后再下载；不要按 `cid`/`gcid` 去重。
4. 下载每个候选并解析字幕：
   - 时长：取所有 cue 的最大结束时间（SRT 取 `-->` 右侧；ASS/SSA 取 `Dialogue` 的 `End` 字段）。
   - 语言：优先从文件名提示，其次按正文文字检测；无判断时回退到 `languages` 提示。
   - SHA256 与字节数：下载后计算。
5. 若 `url` 返回 ZIP，可包含多个字幕文件；逐个解出后分别成为候选。

时长取值规则（与插件一致）：

- 有可解析的字幕时间轴 → 用时间轴，标记 `字幕轴`。
- 没有时间轴、但接口 `duration > 0` → 用 `duration / 1000` 秒，标记 `迅雷API`。
- 两者都没有 → `duration_seconds = null`，标记 `迅雷API`，展示为 `unknown`。

实测例子：`ABP-192` 的接口 `duration` 是 `0`；下载第一个 SRT 候选后解析出 485 个 cue、最大结束时间约 `6364.1` 秒。同一次搜索里的另一个候选只有约 2 KB、29 个 cue，内容明显不同，可见必须逐个候选解析。直接拿 API 时长会得到错误结果。

### 3.3 调用示例

PowerShell：

```powershell
$code = "ABP-192"
$r = Invoke-RestMethod ("https://api-shoulei-ssl.xunlei.com/oracle/subtitle?name=" + [uri]::EscapeDataString($code))
if ($r.code -eq 0) {
  $r.data | Select-Object name, ext, duration, url, extra_name
}
```

Python：下载候选并解析真实时长（SRT/ASS/SSA）：

```python
import re
import urllib.request

def max_end_seconds(data: bytes, fmt: str):
    text = data.decode("utf-8", "replace")
    ends = []
    if fmt == "srt":
        for m in re.finditer(
            r"\d{1,3}:\d{2}:\d{2}[,.]\d{1,3}\s*-->\s*"
            r"(\d{1,3}:\d{2}:\d{2}[,.]\d{1,3})", text):
            ends.append(m.group(1))
    else:
        end_index = 2
        for line in text.splitlines():
            line = line.strip()
            if line.lower().startswith("format:"):
                fields = [x.strip() for x in line[7:].split(",")]
                if "end" in [x.lower() for x in fields]:
                    end_index = [x.lower() for x in fields].index("end")
            if line.lower().startswith("dialogue:"):
                cols = line[9:].split(",")
                if len(cols) > end_index:
                    ends.append(cols[end_index].strip())
    def sec(v):
        v = v.replace(",", ".")
        h, m, s = v.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)
    return max((sec(x) for x in ends), default=None)

url = "https://subtitle.v.geilijiasu.com/C0/85/C085376F32E2E02578202FAE3D6400DCB7E0924C.srt"
body = urllib.request.urlopen(url, timeout=20).read()
print(max_end_seconds(body, "srt"))  # 6364.117
```

## 4. 统一结果模型

建议把两个源归一成同一结构，便于上层排序和展示：

```json
{
  "source": "pool",
  "id": "0b6c2f3e-7a51-4d8e-9f0a-2b8c6d4e1f23",
  "code": "ABP-192",
  "name": "ABP-192.srt",
  "format": "srt",
  "language": "chi",
  "duration_seconds": 6364,
  "duration_source": "字幕轴",
  "size_bytes": 71257,
  "sha256": "…",
  "download_url": "https://chickenrice-subtitle-pool.jzdxjk.workers.dev/api/v1/subtitles/…/download"
}
```

对应关系：

- 海南鸡：字段直接映射；`language` 把 `zh`/`zho` 归一为 `chi`。
- 迅雷：`id` 可用 `sha256` 或 `url`；`duration_source` 按第 3.2 节填写。
- `source` 取 `pool` 或 `thunder`。

推荐排序（与插件 `SubtitleRanking` 一致）：

1. 已知视频时长时，按 `abs(duration_seconds - runtime)` 升序，未知时长排最后。
2. 再按是否有 `size_bytes` 降序。
3. 再按 `size_bytes` 降序。
4. 再按原始稳定顺序（`StableOrder`）。

未知视频时长时，实际就是按大小降序、稳定顺序排序。

## 5. 限制与注意事项

- 海南鸡搜索/下载是公开的；不要泄露上传/删除密钥。
- 海南鸡响应没有 `Access-Control-Allow-Origin`，浏览器跨域直连会被拦；请由服务端代理，或把页面部署在同源下。
- 迅雷是第三方接口，稳定性不由本项目保证；务必设置超时、退避重试和缓存。
- 单次响应体上限：插件按 16 MiB 限制；ZIP 内单个文件上限 16 MiB、展开总量上限 64 MiB。
- 建议并发：迅雷候选下载最多 4 个并发（插件使用 4 个信号量）。
- 下载后校验 SHA256（海南鸡提供；迅雷自行计算）。
- 只处理 SRT / ASS / SSA；其他格式忽略。
- 不要把 `cid`/`gcid` 当唯一键；不要用接口 `duration` 代替真实时间轴。

## 6. 与字幕助手行为对照

| 行为 | 海南鸡 | 迅雷 |
| --- | --- | --- |
| 查询别名 | `match=work` 一次带多个 `codes` | 每个别名一次 `name=` |
| 元数据来源 | 服务端索引 | 下载后解析 |
| 时长来源 | `duration_seconds`（服务端解析） | 字幕时间轴优先，API 毫秒兜底 |
| 去重 | `sha256` + 格式 + 语言 | 内容 SHA256 + 格式 + 语言 |
| 语言 | 服务端 `language` | 文件名/正文检测，回退 `languages` |
| 展示排序 | 插件统一 `SubtitleRanking` | 插件统一 `SubtitleRanking` |

参考实现：

- `emby-unified-plugin/Providers/PoolSubtitleProvider.cs`
- `emby-unified-plugin/Providers/ThunderSubtitleProvider.cs`
- `emby-unified-plugin/Core/MediaIdentifier.cs`
- `emby-unified-plugin/Core/SubtitleContent.cs`
- `subtitle-pool/src/index.js`

