# 字幕助手实施计划（用户已于本对话确认实施）

## 目标与不变量

- 同一 Emby.SubtitleAssistant.dll，版本 1.0.0.0，netstandard2.1 / SDK 4.8.11.0。
- 单插件，五标签（本地、迅雷、海南鸡、字幕云、全局代理）；三个原生下载器。
- 实测 4.8.11.0 / 4.9.1.80 / 4.9.5.0 / 4.10.0.40 / 4.10.2.0。编译与静态检查不等于运行验收。
- 不重置原 E: 工作区，不覆盖现有未提交修改。变更先在本隔离工作树完成。

## 编号与搜索

- 仅文件名提取；SSIS-157-LTX【2021-08-19】（小宵虎南）出差和一直蔑视的中年性骚扰上司共处一室…直到早晨的绝伦性交HCUP新入社员.mp4 必须仅提取 SSIS-157。
- SSIS-157-c-无码破解.mp4 仅以 SSIS-157 查询，但保存字幕保留完整视频 stem，按 Emby 规则加语言与实际字幕扩展名，随后单项刷新。
- 普通有码格式归一；忽略 CD/Part；无号、多个冲突号返回空，禁止整文件名/演员/标题/hash兜底。
- FC2 任意输入必须查询 FC2-PPV-N、FC2PPV-N、FC2-N 全集；素人通过内置 JSON 的已确认前缀表双向展开，首批含 MIUM/300MIUM、GANA/200GANA、JNT/390JNT、IDOL/250IDOL。
- 日期式无码查询六位日期-序号与六位日期_序号，保留数字前导零并忽略厂商；HEYZO 查询横杠/下划线/紧凑三式；Tokyo-Hot N 编号同理。
- 别名全部搜索，汇总后同号校验、同源内容去重、排序，再截取展示。三个来源各自 MaxResults=5，正整数；不以展示数截断候选获取。
- 时长绝对差升序，大小降序，再固定稳定顺序。迅雷只用 API duration，完整预下载同号候选求大小并缓存正文供下载复用。本地/海南鸡使用真实最大字幕结束时间，修正 ASS/SSA 开始时间误取。
- 未知候选时长在后，视频时长未知则按大小；未知大小在同等时差的已知大小之后。按 Emby 请求语言筛选，未知语言保留并标记。

## 自动补全与下载刷新

- 只用自家三个已启用的原生来源，遵守本库顺序；全部关闭即跳过，不借用其它插件。
- 保留入库延迟60秒和原生缺字幕计划任务；已有中文字幕跳过，无结果结束，不自动创建云任务。
- 自动补全用完整候选，不受展示上限约束；异步调用作用域区分用途，不能用跨请求全局bool。
- 单影片互斥并重检已有字幕；下载成功后仅刷新该项，EnableSubtitleDownloading=false，不覆盖全部元数据/图片。
- 原生手动下载也要保持完整视频stem命名并在实际写入成功后刷新，不能在仅获取下载流时提前刷新。

## 外部接口与设置

- 海南鸡保留旧单code/CD精确语义；新增 codes 重复参数和 match=work，批量归一并查base及合法-CDn，合并全量返回后排序。新模式不用展示上限；旧上传数据、ID、客户端保持兼容，无强制DB迁移。
- 保留字幕云提交/任务/完成单项刷新，服务仍外置；所有云操作、设置、代理、更新限管理员；密钥不回显不记录。
- HTTP CONNECT / SOCKS5 可选认证；统一 HttpClient 层只管本插件；下载器和更新可分别启用，Cloud/LAN默认直连，支持bypass/测试；代理失败不直连。
- 旧四插件及额外 Emby.MeiamSub.Thunder.dll 备份停用，迁入指定 ThunderSubtitle 的配置和媒体库顺序/禁用键；导入一次且保留原备份。

## 更新、默认值和验收

- 原生更新任务每24小时，正式版，独立tag emby-subtitle-assistant-v...；固定更新清单由本仓库发布，校验SHA256/程序集身份/版本/兼容范围后备份替换，原生待重启提示，用户决定重启。
- 预取并发4、单项5秒、正文缓存24小时/128MiB；新装自动入库关闭，迁移继承；缺字幕任务无默认触发器。
- 红绿测试、跨5个真实Emby版本完整加载/页面/菜单/原生搜索下载/原生任务更新；HTTP/SOCKS/认证/bypass失败、坏包/取消/错误哈希/替换失败；源关闭零调用、顺序逆转、UI5条而补全能使用第6条。
- 静态测试或代理报告不能代替宿主运行证据。验证通过才发布并迁移NAS；NAS sudo 使用用户已配置的凭据助手，绝不索取/回显口令。

## 执行分工与进度

- [x] 插件基础配置、统一HTTP、更新、迁移、自动补全（主代理与search/cloud协作）。
- [x] 共享番号/字幕解析/排序/缓存/三个提供器（search代理）。
- [x] 海南鸡向后兼容接口与测试（pool/cloud代理）。
- [x] 字幕云桥接、五标签Web与权限（cloud代理）。
- [x] 集成构建、独立审查、5版本实机验证（主代理协调）。
- [x] 正式发布（GitHub 版本包 + 更新清单）与 NAS 生产迁移（主代理协调）。

## 验证结论：五版本运行矩阵已通过

- Release候选03：1.0.0.0，SHA256 `2694f2991f040f5603d88ab6d250ccf9650e8c7aa3a173bab848726ee981de31`。
- 全套Release测试152项通过；Node池端24项通过；真实C#→Worker→SQLite→C#候选匹配43组闭环。
- 同一 DLL 在 4.8.11.0 / 4.9.1.80 / 4.9.5.0 / 4.10.0.40 / 4.10.2.0 五个官方隔离宿主全部通过加载、五标签页、三下载器、两个原生任务与展示上限5。
- 每版均通过：原生手动搜索下载 `SSIS-157-c-无码破解` 并保留完整视频 stem；HTTP/SOCKS5 代理、独立模块开关、不直连回退、bypass；管理员/普通用户/未认证权限边界；字幕云提交/任务/完成与单项刷新；自动补全（60秒延迟、第六候选、源禁用跳过）；原生更新（坏哈希拒绝、校验安装、备份、待重启、不自动重启容器）；旧插件迁移。
- 真实浏览器登录、五标签、默认值、保存/重载、密钥掩码、更新按钮绑定均通过，浏览器错误与失败资源为 0。
- 证据全部归档在隔离工作树：`emby-unified-plugin/validation/reports/candidate-03-*.json`（45 份 API 报告）、`emby-unified-plugin/validation/browser-output/{4811,49180,495,410040,4102}-report.json` 与对应 PNG。NAS 原始证据位于 `/volume1/docker/emby-subtitle-assistant-validation-20261027/`。
- 真实4.8已抓出并修复公开IService异步返回必须Task<object>的204空响应问题；五版现已同哈希验证。
- 真实4.10.2源码仅声明未发SubtitlesDownloaded，已用原响应流释放后的落盘快照观察弥补，专门回归覆盖无落盘/旧文件不误刷新。
- 独立审查的别名400、legacy零填充漏查、中文混合语言误筛、Cloud自定义认证头跨源跳转均已红绿验证修复。
- 4.9.5 早期失败是旧验证容器 UID 2 无法写入 NAS 私有 bind 的验证环境问题；用 `plugin_smoke.py ... --install` 以 UID 0 重建自有验证容器后全部通过，非插件缺陷。
- 生产已暂存新 DLL 并移出五个旧 DLL，等待管理员手动重启 Emby 后才加载；未自动重启生产容器。

## 发布与生产迁移记录（2026-10-27）

- 功能分支：`codex/subtitle-assistant`，发布提交 `befc5bc0dd695fb6a16da077aec6bcc560311600`。
- GitHub 版本 release：`emby-subtitle-assistant-v1.0.0.0`（含 `Emby.SubtitleAssistant.dll` / `update.json` / `SHA256SUMS.txt`，DLL digest `sha256:2694f299...de31`）。
- GitHub 指针 release：`emby-subtitle-assistant-update` 的 `update.json` 已指向 1.0.0.0，sha256 与版本包一致。
- 草稿 PR：https://github.com/jzdxjk/subtitle-modal-web/pull/1 （`codex/subtitle-assistant` → `dev`）。
- 池端 Worker：`chickenrice-subtitle-pool` 已部署（Version `2cb5022d-c723-49e3-9803-af7264046fdb`）；生产 D1 无待应用迁移；线上 `/health`、`match=work&codes=`（200）、旧单号搜索（200）、非法编号（400）均符合预期。
- NAS 生产暂存：备份目录 `/volume1/docker/emby/backups/subtitle-assistant-20261027T080421Z-ba21a7a8`（含 5 个旧 DLL、5 个旧配置、91MB `library.snapshot.db`、`stage.json`）。生产 `emby` 容器未重启（StartedAt 仍为 2026-10-22）。
- 回滚路径：按 `stage.json` 从备份目录恢复五个旧 DLL 与原配置；新 DLL 对应文件为 `Emby.SubtitleAssistant.dll`。回滚同样需要手动重启。
