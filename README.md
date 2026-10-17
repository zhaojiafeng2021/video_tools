# 视频语音替换工具

基于 GPT-SoVITS + Whisper + FFmpeg 的免费视频配音替换方案。保留人物音色，修改台词，无需对口型。

## 功能特性

- ✅ 从视频提取音频
- ✅ 使用 Whisper 自动转写原台词（可选）
- ✅ 使用 GPT-SoVITS 克隆人物音色
- ✅ 合成新台词语音
- ✅ 自动替换视频音轨
- ✅ 支持单句或多句台词替换
- ✅ 支持混音模式（保留原音轨背景音）

## 环境要求

- Python 3.8+
- FFmpeg（需要添加到系统 PATH）
- 至少 4GB 显存（GPU 推荐，CPU 也可以但速度较慢）

## 安装步骤

### 1. 安装 FFmpeg

**Windows:**
```powershell
# 使用 Chocolatey
choco install ffmpeg

# 或下载安装包
# https://ffmpeg.org/download.html
```

**Linux/Mac:**
```bash
# Ubuntu/Debian
sudo apt install ffmpeg

# Mac
brew install ffmpeg
```

### 2. 安装 Python 依赖

```bash
cd video-voice-replacer
pip install -r requirements.txt
```

### 3. 安装 GPT-SoVITS

```bash
# 克隆 GPT-SoVITS 仓库
git clone https://github.com/RVC-Boss/GPT-SoVITS.git
cd GPT-SoVITS

# 安装依赖
pip install -r requirements.txt

# 下载预训练模型（首次运行时会自动下载，也可以手动下载）
# 模型地址: https://huggingface.co/lj1995/GPT-SoVITS
```

### 4. 启动 GPT-SoVITS API 服务

```bash
cd GPT-SoVITS
python api.py -a 127.0.0.1 -p 9880
```

保持这个服务运行，然后在另一个终端使用本工具。

默认 API 地址是 `http://127.0.0.1:9880`，由 [utils/voice_cloner.py](utils/voice_cloner.py) 中的 `VoiceCloner.__init__` 的 `api_url` 参数指定；如果 GPT-SoVITS 跑在别的地址/端口，初始化时传入对应 `api_url` 即可。

### 5. 启动 Web 服务（可选，推荐）

除了命令行脚本 `main.py`，本项目还提供了一个带界面的 Web 服务，可以上传视频、编辑台词、在线查看合成结果：

```bash
cd webapp
python app.py
```

默认监听 `http://127.0.0.1:5000`，用浏览器打开即可使用。使用前同样需要先启动 GPT-SoVITS API 服务（见上一步）。

## 使用方法

### 基本用法

```bash
python main.py <视频路径> \
  --refer-audio <参考音频> \
  --refer-text "参考音频的文字内容" \
  --new-text "这是新的台词"
```

### 示例 1：单句替换

```bash
python main.py my_video.mp4 \
  --refer-audio reference.wav \
  --refer-text "我是原来的台词" \
  --new-text "我是新的台词"
```

### 示例 2：多句替换（从文件读取）

创建 `new_script.txt`:
```
这是第一句新台词
这是第二句新台词
这是第三句新台词
```

运行：
```bash
python main.py my_video.mp4 \
  --refer-audio reference.wav \
  --refer-text "我是参考音频的内容" \
  --new-script new_script.txt
```

### 示例 3：保留原音轨背景音（混音模式）

```bash
python main.py my_video.mp4 \
  --refer-audio reference.wav \
  --refer-text "参考文本" \
  --new-text "新台词" \
  --keep-original
```

### 参数说明

| 参数 | 必填 | 说明 |
|------|------|------|
| `video` | ✅ | 输入视频文件路径 |
| `--refer-audio` | ✅ | 参考音频路径（几秒到几十秒，用于克隆音色） |
| `--refer-text` | ✅ | 参考音频对应的文字内容 |
| `--new-text` | ✅* | 新台词文本（单句） |
| `--new-script` | ✅* | 新台词文本文件（多句，每行一句） |
| `--output` | ❌ | 输出视频路径（默认自动生成） |
| `--keep-original` | ❌ | 保留原音轨（混音模式） |
| `--skip-transcribe` | ❌ | 跳过 Whisper 转写步骤 |
| `--config` | ❌ | 配置文件路径（默认 config.json） |

*注：`--new-text` 和 `--new-script` 二选一

## 配置说明

编辑 `config.json` 可以调整参数：

```json
{
  "whisper_model": "base",  // tiny/base/small/medium/large
  "whisper_language": "zh",  // 语言代码
  "gptsovits": {
    "prompt_language": "中文",
    "text_language": "中文",
    "top_k": 5,
    "top_p": 1,
    "temperature": 1
  },
  "output": {
    "audio_fade_duration": 0.1  // 音频淡入淡出时长（秒）
  }
}
```

## 工作流程

```
┌─────────────┐
│  输入视频    │
└──────┬──────┘
       │
       ▼
┌─────────────────┐
│ 1. 提取音频      │
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│ 2. Whisper转写   │ (可选)
│    识别原台词    │
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│ 3. 准备新台词    │
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│ 4. GPT-SoVITS   │
│    音色克隆+合成 │
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│ 5. 音轨替换     │
│    输出新视频    │
└─────────────────┘
```

## 常见问题

### Q1: 提示 "无法连接到 GPT-SoVITS 服务"

**A:** 确保已启动 GPT-SoVITS 的 API 服务：
```bash
cd GPT-SoVITS
python api.py -a 127.0.0.1 -p 9880
```

### Q2: FFmpeg 报错

**A:** 检查 FFmpeg 是否已安装并添加到 PATH：
```bash
ffmpeg -version
```

### Q3: 音色不够相似

**A:** 尝试：
- 使用更长的参考音频（10-30秒）
- 确保参考音频清晰、无噪音
- 参考文本要准确对应音频内容
- 调整 `config.json` 中的 `temperature` 参数

### Q4: Whisper 下载模型很慢

**A:** 可以手动下载模型文件放到 `~/.cache/whisper/` 目录：
- tiny: ~39 MB
- base: ~74 MB  (推荐)
- small: ~244 MB
- medium: ~769 MB
- large: ~1550 MB

### Q5: 内存不足

**A:** 降级 Whisper 模型：
```json
"whisper_model": "tiny"  // 改用 tiny 模型
```

### Q6: 简体/繁体识别比对总是不通过

**A:** 内容校验环节依赖 `opencc-python-reimplemented` 做繁简归一化，确保执行过 `pip install -r requirements.txt`，若单独安装可以用：
```bash
pip install opencc-python-reimplemented
```

## 项目结构

```
video-voice-replacer/
├── main.py                      # 主流程脚本
├── config.json                  # 配置文件
├── requirements.txt             # Python 依赖
├── utils/
│   ├── __init__.py
│   ├── audio_extractor.py       # 音频提取
│   ├── speech_transcriber.py    # 语音转写
│   ├── voice_cloner.py          # 音色克隆
│   └── audio_replacer.py        # 音轨替换
└── README.md                    # 说明文档
```

## 技术栈

- **音频提取**: FFmpeg
- **语音识别**: OpenAI Whisper
- **音色克隆**: GPT-SoVITS
- **音频处理**: pydub, librosa
- **视频处理**: ffmpeg-python, moviepy

## 开源协议

本项目基于 MIT 协议开源。

依赖项目协议：
- GPT-SoVITS: MIT
- Whisper: MIT
- FFmpeg: LGPL/GPL

## 致谢

- [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) - 音色克隆核心
- [OpenAI Whisper](https://github.com/openai/whisper) - 语音识别
- [FFmpeg](https://ffmpeg.org/) - 音视频处理

## 贡献

欢迎提 Issue 和 PR！

## 免责声明

本工具仅供学习研究使用。请勿用于非法用途，如伪造他人声音、制作虚假内容等。使用者需遵守当地法律法规，并承担相应法律责任。
