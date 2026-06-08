# 🎬 Subtitle Modal Web

基于 Modal 云端 GPU 的自动化字幕翻译平台。将视频放入监听目录，自动抽取音频、云端推理、生成字幕。

---

## ✨ 功能

- 📁 **目录监听** — 视频放入指定目录自动触发翻译
- ☁️ **云端推理** — 基于 Modal GPU（T4/A100）运行 Faster-Whisper
- 📝 **多格式输出** — 支持 SRT / ASS / VTT 字幕格式
- 🎨 **Emby 风格海报墙** — 自动匹配 JavDB 封面，按日期分组展示
- 📱 **PWA 移动端** — 支持添加到手机主屏幕，底部导航栏
- 🌗 **亮/暗主题** — 一键切换

---

## 🚀 快速部署

```bash
git clone https://github.com/jzdxjk/subtitle-modal-web.git
cd subtitle-modal-web
```

### 1. 修改密钥

编辑 `docker-compose.yml`，把 `ak-YOUR_TOKEN_ID` 和 `as-YOUR_TOKEN_SECRET` 替换为你的 [Modal](https://modal.com) API 密钥。

```yaml
MODAL_TOKEN_ID: "ak-YOUR_TOKEN_ID"        # ← 改这里
MODAL_TOKEN_SECRET: "as-YOUR_TOKEN_SECRET"  # ← 改这里
```

### 2. 修改路径

```yaml
volumes:
  - /your/video/path:/mnt/115        # 视频存放目录
  - /your/output/path:/output        # 字幕输出目录
```

### 3. 启动

```bash
docker-compose up -d
```

访问 `http://NAS_IP:9198`

---

## 🔧 海报封面

启动后在 Web 界面 → **配置** → 填写 DBO API 地址和密钥，主界面即可显示 JavDB 封面海报。

---

## 📄 License

MIT © jzdxjk
