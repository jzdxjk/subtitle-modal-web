# NAS Docker + Modal 云端字幕 Web

这个项目把 `TransWithAI/Faster-Whisper-TransWithAI-ChickenRice` 的 **v1.7 / Chickenrice Edition** 包成一个 NAS 可用的 Web 控制台，面向 AV 字幕场景。

- NAS/Docker 负责 Web UI、任务队列、读取 `/watch`、抽音频、保存字幕。
- Modal 云端 GPU 负责实际推理。
- 默认访问地址：`http://NAS_IP:8898`。

## 部署

1. 修改 `docker-compose.yml` 里的三个挂载路径：
   - `/watch:ro`：你的 CD2/115 视频目录，只读。
   - `/output`：字幕输出目录。
   - `/cache`：NAS 本地缓存目录，建议不要放在 115 网盘挂载里。
2. 填入 `MODAL_TOKEN_ID` 和 `MODAL_TOKEN_SECRET`。
3. 启动：

```bash
docker compose up -d --build
```

## 临时第二实例

如果你本机已经有一个 `subtitle-modal-web` 在跑，又想临时起一个隔离测试实例，不要动现有容器，直接用仓库里的第二套 compose：

1. 复制环境文件：

```bash
cp .env.temp-second-instance.example .env.temp-second-instance
```

2. 填入 `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET`。
3. 启动临时实例：

```bash
docker compose --env-file .env.temp-second-instance -f docker-compose.temp-second-instance.yml up -d --build
```

4. 打开 `http://localhost:9199`。

说明：

- 这套配置不会复用现有容器名，因此不会和正在运行的主实例冲突。
- 临时实例使用独立挂载目录：`./temp-second-instance/media`、`./temp-second-instance/output`、`./temp-second-instance/cache`、`./temp-second-instance/config`。
- 容器内监听端口仍是 `8898`，只是在宿主机上映射到 `9199`。
- 用完可单独停止：

```bash
docker compose --env-file .env.temp-second-instance -f docker-compose.temp-second-instance.yml down
```

## 使用

1. 打开 `http://NAS_IP:8898`。
2. 在“配置”里确认 GPU、模型、格式。模型默认是 `chickenrice`。
3. 在“提交任务”里填写 `/watch` 下的视频文件或文件夹路径。
4. 点“加入队列”，等待任务状态变为 `done`。

## 注意

- 这个方案默认锁定 **海南鸡版 / Chickenrice Edition**，不是普通 faster-whisper 泛用模型。
- 项目会先用 `ffmpeg` 把视频抽成音频，再上传到 Modal，避免大视频直接上传。
- 默认已有字幕不覆盖。
- 原项目的 `modal_infer.py --non-interactive` 尚未真正实现，所以这里生成桥接脚本直接复用它的 Modal 函数，绕开交互式 `questionary`。
- 首次 Modal 运行会慢，因为要构建/拉模型。
