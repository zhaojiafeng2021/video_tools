# 使用示例

本文档提供详细的使用示例和场景说明。

## 快速开始

### 场景 1：替换单句台词

假设你有一个视频 `interview.mp4`，想把其中某句话改掉。

**步骤：**

1. 从原视频中截取一小段清晰的人声作为参考音频（3-30秒）
   ```bash
   # 用 FFmpeg 截取 5-15 秒的片段作为参考
   ffmpeg -i interview.mp4 -ss 00:00:05 -to 00:00:15 -vn reference.wav
   ```

2. 听一下这段参考音频，记下文字内容（比如："大家好，我是张三"）

3. 运行替换脚本
   ```bash
   python main.py interview.mp4 \
     --refer-audio reference.wav \
     --refer-text "大家好，我是张三" \
     --new-text "欢迎收看本期节目"
   ```

4. 查看输出视频 `interview_replaced.mp4`

---

### 场景 2：替换多句台词

视频有多句台词要改，准备一个文本文件。

**准备 `new_script.txt`:**
```
欢迎来到我的频道
今天我要分享一个有趣的话题
让我们开始吧
```

**运行：**
```bash
python main.py tutorial.mp4 \
  --refer-audio reference.wav \
  --refer-text "原参考音频的文字" \
  --new-script new_script.txt
```

---

### 场景 3：保留背景音乐和环境音

如果视频有背景音乐或环境音（BGM、风声、键盘声等），想保留它们，只替换人声。

**使用混音模式：**
```bash
python main.py vlog.mp4 \
  --refer-audio ref.wav \
  --refer-text "参考文本" \
  --new-text "新台词" \
  --keep-original
```

这会保留原音轨（音量降低到 10%），叠加新的人声。

---

### 场景 4：跨语言配音

参考音频是中文，新台词想用英文。

```bash
python main.py video_cn.mp4 \
  --refer-audio ref_chinese.wav \
  --refer-text "这是中文参考音频" \
  --new-text "This is the new English dialogue"
```

GPT-SoVITS 支持跨语言音色迁移，会保留原音色特征。

---

## 高级用法

### 调整合成质量

编辑 `config.json`:

```json
{
  "gptsovits": {
    "temperature": 0.8,  // 降低随机性，更稳定（0.5-1.5）
    "top_k": 10,         // 增加采样范围，更自然（5-20）
    "top_p": 0.9         // 调整采样策略（0.8-1.0）
  }
}
```

- `temperature` 越低越稳定，越高越有变化
- `top_k` 和 `top_p` 控制生成多样性

### 使用更好的 Whisper 模型

编辑 `config.json`:

```json
{
  "whisper_model": "medium"  // tiny < base < small < medium < large
}
```

模型越大识别越准，但占用内存越多。中文推荐 `base` 或 `small`。

### 手动指定时间轴

如果自动转写的时间轴不准，可以手动编辑 `<视频名>_workspace/transcription.json`:

```json
{
  "segments": [
    {
      "id": 0,
      "start": 1.5,   // 手动调整开始时间
      "end": 4.2,     // 手动调整结束时间
      "text": "第一句话"
    },
    {
      "id": 1,
      "start": 4.5,
      "end": 7.8,
      "text": "第二句话"
    }
  ]
}
```

然后用 `--skip-transcribe` 跳过重新转写：

```bash
python main.py video.mp4 \
  --refer-audio ref.wav \
  --refer-text "参考" \
  --new-script new.txt \
  --skip-transcribe
```

---

## 常见问题排查

### 问题：音色不够像

**解决：**
1. 用更长的参考音频（15-30秒）
2. 确保参考音频清晰、无背景噪音
3. 参考文本必须准确对应音频（一字不差）
4. 如果参考音频里有多人说话，截取只有目标人物的片段

### 问题：合成语音断断续续

**解决：**
1. 检查 GPT-SoVITS 服务是否正常运行
2. 降低 `temperature` 参数到 0.7
3. 确保参考文本没有特殊字符或乱码

### 问题：视频输出音画不同步

**解决：**
1. 检查原视频是否为可变帧率（VFR），建议先转为固定帧率（CFR）：
   ```bash
   ffmpeg -i input.mp4 -r 30 -c:v libx264 -crf 18 output_cfr.mp4
   ```
2. 使用 `--keep-original` 保留原时间基准

### 问题：内存不足

**解决：**
1. 使用 `tiny` Whisper 模型
2. 分段处理长视频
3. 关闭其他占用内存的程序

---

## 最佳实践

### 参考音频选择

✅ **好的参考音频：**
- 3-30 秒，清晰连贯
- 只有目标人物说话
- 无背景噪音、音乐
- 语速正常，情绪平稳

❌ **不好的参考音频：**
- 太短（< 2 秒）
- 多人对话混杂
- 嘈杂环境录音
- 语速过快或情绪激动

### 台词撰写

- 避免过长的单句（超过 50 字）
- 标点符号会影响停顿，合理使用
- 专有名词可能发音不准，试听后调整

### 输出管理

每次处理会生成工作目录 `<视频名>_workspace/`，包含：
- 提取的音频
- 转写结果 JSON
- 合成的语音片段
- 合并后的音轨

可以保留这些中间文件，方便调试和二次处理。

---

## 性能参考

| 配置 | Whisper 模型 | 处理 1 分钟视频耗时 |
|------|-------------|-------------------|
| CPU（i7-12700） | base | ~3 分钟 |
| GPU（RTX 3060） | base | ~30 秒 |
| GPU（RTX 4090） | medium | ~15 秒 |

*仅供参考，实际时间取决于台词数量和合成长度*

---

## 脚本集成

可以在自己的 Python 脚本中调用模块：

```python
from utils.audio_extractor import AudioExtractor
from utils.voice_cloner import VoiceCloner
from utils.audio_replacer import AudioReplacer

# 提取音频
extractor = AudioExtractor()
audio = extractor.extract("video.mp4")

# 克隆和合成
cloner = VoiceCloner()
cloner.set_reference("ref.wav", "参考文本")
new_audio = cloner.synthesize("新台词", "output.wav")

# 替换音轨
replacer = AudioReplacer()
replacer.replace_audio("video.mp4", new_audio, "result.mp4")
```

---

## 更多资源

- GPT-SoVITS 官方文档: https://github.com/RVC-Boss/GPT-SoVITS
- Whisper 模型说明: https://github.com/openai/whisper
- FFmpeg 使用指南: https://ffmpeg.org/documentation.html
