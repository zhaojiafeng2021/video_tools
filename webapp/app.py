# -*- coding: utf-8 -*-
"""
视频语音替换 Web 服务
流程：
  1. POST /api/upload        上传视频 -> 提取音频 -> 转写 -> 返回带时间戳的台词 txt
  2. GET  /api/script/<task_id>   下载当前台词 txt
  3. POST /api/apply/<task_id>    上传修改后的台词 txt -> 合成新语音 -> 替换音轨 -> 遮盖旧字幕并画新字幕 -> 返回视频下载链接
  4. GET  /api/download/<task_id> 下载最终视频
"""
import os
import sys
import json
import uuid
from pathlib import Path

import yaml
import requests
from flask import Flask, request, jsonify, send_file, render_template

# 让 webapp 能找到上一级 utils 模块
sys.path.insert(0, str(Path(__file__).parent.parent))

# 确保能找到 ffmpeg/ffprobe 可执行文件（避免依赖外部终端的 PATH 设置）
_FFMPEG_BIN_DIR = r"C:\Users\gg.zhao\Downloads\ffmpeg\ffmpeg-master-latest-win64-gpl\bin"
if _FFMPEG_BIN_DIR not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _FFMPEG_BIN_DIR + os.pathsep + os.environ.get("PATH", "")

from utils.audio_extractor import AudioExtractor
from utils.speech_transcriber import SpeechTranscriber
from utils.voice_cloner import VoiceCloner
from utils.audio_replacer import AudioReplacer
from utils.subtitle_burner import SubtitleBurner
from utils.script_io import segments_to_script, script_to_segments

BASE_DIR = Path(__file__).parent.parent
WORKSPACE_DIR = BASE_DIR / "workspace"
WORKSPACE_DIR.mkdir(exist_ok=True)

CONFIG_PATH = BASE_DIR / "config.json"
with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500MB

# GPT-SoVITS 相关路径与可选版本，用于运行时切换模型权重
GPTSOVITS_DIR = Path(r"C:\Users\gg.zhao\Downloads\GPT-SoVITS")
GPTSOVITS_API_URL = "http://127.0.0.1:9880"
TTS_INFER_CONFIG_PATH = GPTSOVITS_DIR / "GPT_SoVITS" / "configs" / "tts_infer.yaml"
SUPPORTED_GPTSOVITS_VERSIONS = {"v2", "v3", "v4"}


def switch_gptsovits_version(version):
    """调用 GPT-SoVITS API 切换到指定版本的 GPT/SoVITS 权重（无需重启服务）

    Args:
        version: "v2" / "v3" / "v4"

    Raises:
        ValueError: 版本不受支持或 tts_infer.yaml 中缺少对应配置
        RuntimeError: 调用 GPT-SoVITS API 切换权重失败
    """
    if version not in SUPPORTED_GPTSOVITS_VERSIONS:
        raise ValueError(f"不支持的 GPT-SoVITS 版本: {version}")

    with open(TTS_INFER_CONFIG_PATH, "r", encoding="utf-8") as f:
        tts_infer_config = yaml.safe_load(f)

    version_config = tts_infer_config.get(version)
    if not version_config:
        raise ValueError(f"tts_infer.yaml 中缺少版本配置: {version}")

    t2s_path = GPTSOVITS_DIR / version_config["t2s_weights_path"]
    vits_path = GPTSOVITS_DIR / version_config["vits_weights_path"]

    try:
        resp = requests.get(
            f"{GPTSOVITS_API_URL}/set_gpt_weights",
            params={"weights_path": str(t2s_path)},
            timeout=30,
        )
        resp.raise_for_status()
        resp = requests.get(
            f"{GPTSOVITS_API_URL}/set_sovits_weights",
            params={"weights_path": str(vits_path)},
            timeout=30,
        )
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"切换 GPT-SoVITS 版本失败: {e}")

    print(f"✓ 已切换 GPT-SoVITS 到 {version} 版本")


def task_dir(task_id):
    d = WORKSPACE_DIR / task_id
    if not d.exists():
        raise FileNotFoundError(f"任务不存在: {task_id}")
    return d


def load_meta(task_id):
    d = task_dir(task_id)
    with open(d / "meta.json", "r", encoding="utf-8") as f:
        return json.load(f)


def save_meta(task_id, meta):
    d = task_dir(task_id)
    with open(d / "meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/upload", methods=["POST"])
def upload_video():
    """上传视频 -> 提取音频 -> 转写 -> 截取参考音色 -> 返回台词 txt"""
    if "video" not in request.files:
        return jsonify({"error": "缺少视频文件"}), 400

    video_file = request.files["video"]
    if not video_file.filename:
        return jsonify({"error": "视频文件名为空"}), 400

    task_id = uuid.uuid4().hex[:12]
    d = WORKSPACE_DIR / task_id
    d.mkdir(parents=True, exist_ok=True)

    video_ext = Path(video_file.filename).suffix or ".mp4"
    video_path = d / f"original{video_ext}"
    video_file.save(str(video_path))

    try:
        # 1. 提取完整音频
        extractor = AudioExtractor()
        audio_path = d / "audio.wav"
        extractor.extract(video_path, audio_path)

        # 2. Whisper 转写，得到带时间轴的分段
        transcriber = SpeechTranscriber(
            model_name=CONFIG["whisper_model"],
            language=CONFIG["whisper_language"],
        )
        transcription_json = d / "transcription.json"
        transcription = transcriber.transcribe(audio_path, transcription_json)

        # 3. 自动截取参考音色片段（取第一段到前 10 秒左右的人声）
        reference_path = d / "reference.wav"
        ref_text = _extract_reference_audio(audio_path, transcription, reference_path)

        # 4. 生成带时间戳的台词 txt
        script_path = d / "script.txt"
        segments_to_script(transcription["segments"], script_path)

        meta = {
            "task_id": task_id,
            "video_ext": video_ext,
            "reference_text": ref_text,
            "prompt_language": CONFIG["gptsovits"].get("prompt_language", "中文"),
            "status": "transcribed",
        }
        save_meta(task_id, meta)

        return jsonify({
            "task_id": task_id,
            "script": script_path.read_text(encoding="utf-8"),
            "reference_text": ref_text,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _extract_reference_audio(audio_path, transcription, reference_path, max_duration=9.5, min_duration=3.0):
    """从转写结果里取开头若干段拼成参考音色片段，返回对应文本

    GPT-SoVITS 要求参考音频时长在 3~10 秒之间，这里取 9.5 秒上限留出余量，
    并保证加入下一段前先检查是否会超限，避免最终片段超过 10 秒被服务拒绝。
    """
    segments = transcription["segments"]
    if not segments:
        raise RuntimeError("未识别到任何语音内容，无法提取参考音色")

    end_time = 0.0
    texts = []
    for seg in segments:
        # 如果已有内容且满足最短时长，加入这一段会超过上限，则停止
        if texts and end_time >= min_duration and seg["end"] > max_duration:
            break
        end_time = seg["end"]
        texts.append(seg["text"])
        if end_time >= max_duration:
            break

    if end_time < min_duration:
        raise RuntimeError(f"识别到的语音片段过短（{end_time:.1f}秒），无法提取有效参考音色（需至少{min_duration}秒）")

    extractor = AudioExtractor()
    extractor.cut(audio_path, reference_path, start=0.0, end=end_time)
    return "".join(texts).strip()


@app.route("/api/script/<task_id>", methods=["GET"])
def get_script(task_id):
    d = task_dir(task_id)
    script_path = d / "script.txt"
    if not script_path.exists():
        return jsonify({"error": "台词文件不存在"}), 404
    return send_file(script_path, as_attachment=True, download_name="script.txt")


@app.route("/api/apply/<task_id>", methods=["POST"])
def apply_script(task_id):
    """上传修改后的台词 txt -> 合成新语音 -> 替换音轨 -> 遮盖旧字幕并画新字幕"""
    d = task_dir(task_id)
    meta = load_meta(task_id)

    if "script" not in request.files:
        return jsonify({"error": "缺少台词文件"}), 400

    script_file = request.files["script"]
    new_script_path = d / "new_script.txt"
    script_file.save(str(new_script_path))

    try:
        # 解析台词文件：同一时间段内若有多行（人工断句），自动归为一组，
        # 组内各子句独立合成/判断是否复用，避免整段按空格拆分触发短文本异常
        # 传入原始 script.txt 按时间戳比对文本，标记每个时间段是否被用户改动过
        original_script_path = d / "script.txt"
        segments = script_to_segments(new_script_path, original_script_path=original_script_path)
        if not segments:
            return jsonify({"error": "台词文件内容为空或格式不正确"}), 400

        video_path = d / f"original{meta['video_ext']}"
        reference_path = d / "reference.wav"
        audio_path = d / "audio.wav"

        synthesis_dir = d / "synthesized"
        synthesis_dir.mkdir(exist_ok=True)
        audio_files = [None] * len(segments)

        # 1a. 文本未改动的句子：直接从原始音轨裁剪对应时间段复用，
        # 完整保留原始音色/语气，且彻底规避 GPT-SoVITS 短文本合成异常
        # 停顿分段（is_pause）既不复用也不合成，交给合并阶段的静音底轨自然留白
        extractor = AudioExtractor()
        changed_segments = []
        for i, seg in enumerate(segments):
            if seg.get("is_pause"):
                continue
            if seg.get("changed", True):
                changed_segments.append((i, seg))
                continue
            reuse_path = synthesis_dir / f"segment_{i:03d}.wav"
            extractor.cut(audio_path, reuse_path, start=seg["start"], end=seg["end"])
            audio_files[i] = str(reuse_path)

        # 1b. 文本有改动的句子：走 GPT-SoVITS 重新合成
        # GPT-SoVITS 对部分文本会稳定返回固定短时长但内容无效的音频，
        # 仅靠时长估算无法检测，这里传入 ASR 校验器，合成后核对实际吐字内容
        if changed_segments:
            gptsovits_version = request.form.get("version", "v4")
            switch_gptsovits_version(gptsovits_version)

            verifier = SpeechTranscriber(
                model_name=CONFIG["whisper_model"],
                language=CONFIG["whisper_language"],
            )
            cloner = VoiceCloner(config=CONFIG.get("gptsovits", {}), verifier=verifier)
            cloner.set_reference(
                reference_path,
                meta["reference_text"],
                meta["prompt_language"],
            )
            _EMOTION_PARAM_KEYS = ("speed_factor", "temperature", "top_k", "top_p", "repetition_penalty")
            synthesized = cloner.synthesize_batch(
                [{"id": i, "text": seg.get("synth_text", seg["text"]), "line_id": seg.get("line_id", i),
                  **{k: seg.get(k) for k in _EMOTION_PARAM_KEYS}}
                 for i, seg in changed_segments],
                synthesis_dir,
            )
            for (i, _seg), audio_file in zip(changed_segments, synthesized):
                audio_files[i] = audio_file

        print(f"✓ 复用原音频: {len(segments) - len(changed_segments)}/{len(segments)} 句，"
              f"重新合成: {len(changed_segments)}/{len(segments)} 句")

        # 2. 按时间轴合并音频
        replacer = AudioReplacer(fade_duration=CONFIG["output"]["audio_fade_duration"] * 1000)
        merged_audio = d / "merged_audio.wav"
        replacer.merge_audio_segments(audio_files, segments, merged_audio)

        # 3. 替换视频音轨
        audio_replaced_video = d / "audio_replaced.mp4"
        replacer.replace_audio(video_path, merged_audio, audio_replaced_video)

        # 4. 遮盖旧字幕并画新字幕
        output_video = d / "output.mp4"
        burner = SubtitleBurner()
        burner.burn(audio_replaced_video, segments, output_video)

        meta["status"] = "done"
        save_meta(task_id, meta)

        return jsonify({"task_id": task_id, "download_url": f"/api/download/{task_id}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/download/<task_id>", methods=["GET"])
def download_result(task_id):
    d = task_dir(task_id)
    output_path = d / "output.mp4"
    if not output_path.exists():
        return jsonify({"error": "结果视频不存在，请先完成替换"}), 404
    return send_file(output_path, as_attachment=True, download_name=f"{task_id}_replaced.mp4")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
