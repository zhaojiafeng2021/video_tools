# -*- coding: utf-8 -*-
"""
台词脚本读写模块
负责在 Whisper 转写得到的分段(segments) 和 人类可编辑的 txt 文件之间转换。

txt 格式（每行一句）：
[开始秒-结束秒] 文本内容
例如：
[0.00-3.20] 在全世界面前
[3.20-6.50] 该不该愤怒呢
"""
import re
from pathlib import Path

LINE_PATTERN = re.compile(r"^\[(?P<start>[\d.]+)-(?P<end>[\d.]+)\]\s*(?P<text>.*)$")

# 行首情绪标记 -> 语气符号，紧跟在时间戳之后、正文之前，例如：
# [0.00-5.92] [激昂]你们狗队 在全世界面前 献祭了所有散户
EMOTION_MARKER_PATTERN = re.compile(r"^\[(?P<emotion>激昂|低沉|平稳)\]\s*(?P<rest>.*)$")

# 情绪 -> 合成参数映射
# GPT-SoVITS 的 speed_factor 只改变播放速度（纯变速/变调），不影响 GPT 阶段
# 语义 token 的采样过程，单独调它只会让语速变快，听感是"快读"而不是"激昂"。
# 真正决定抑扬顿挫、情绪张力的是 GPT 采样参数：temperature/top_k/top_p 越大，
# 韵律起伏越丰富；repetition_penalty 适度调高可避免采样随机性变大后出现
# 重复拖腔。因此激昂/低沉主要靠这组采样参数制造语气差异，speed_factor 只
# 做轻度辅助（激昂略快、低沉略慢），不作为情绪的主控参数。
EMOTION_PARAMS = {
    "激昂": {"speed_factor": 1.15, "temperature": 1.4, "top_k": 25, "top_p": 1.0, "repetition_penalty": 1.5},
    "低沉": {"speed_factor": 0.85, "temperature": 0.75, "top_k": 10, "top_p": 0.8, "repetition_penalty": 1.3},
    "平稳": {"speed_factor": 1.0, "temperature": 1.0, "top_k": 15, "top_p": 1.0, "repetition_penalty": 1.35},
}


def segments_to_script(segments, output_path, merge_short=True, min_duration=1.5):
    """
    将转写分段写成带时间戳的 txt 文件
    
    Args:
        segments: [{'start': float, 'end': float, 'text': str}, ...]
        output_path: 输出 txt 路径
        merge_short: 是否合并过短的片段（默认 True）
        min_duration: 最小片段时长（秒），低于此时长会尝试与相邻片段合并
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 如果需要合并短句，先进行预处理
    if merge_short:
        segments = _merge_short_segments(segments, min_duration)

    lines = []
    for seg in segments:
        text = seg["text"].strip()
        lines.append(f"[{seg['start']:.2f}-{seg['end']:.2f}] {text}")

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(output_path)


def _merge_short_segments(segments, min_duration=1.5, max_gap=0.5):
    """
    合并过短的分段，提升语义完整性

    文本为空的分段是停顿标记（换行停顿），原样保留、不参与合并，
    也不与前后分段合并，避免停顿被吞掉。

    Args:
        segments: 原始分段列表
        min_duration: 最小片段时长（秒）
        max_gap: 允许合并的最大时间间隔（秒）

    Returns:
        list: 合并后的分段列表
    """
    if not segments:
        return []

    merged = []
    buffer = None

    for seg in segments:
        # 停顿分段（空文本）直接原样保留，不参与合并
        if not seg['text'].strip():
            if buffer:
                merged.append(buffer)
                buffer = None
            merged.append(seg.copy())
            continue

        duration = seg['end'] - seg['start']

        # 如果缓冲区为空，先放入
        if buffer is None:
            buffer = seg.copy()
            continue

        # 计算与缓冲区的时间间隔
        gap = seg['start'] - buffer['end']

        # 如果当前片段很短，或缓冲区很短且间隔不大，则合并
        if (duration < min_duration or
            (buffer['end'] - buffer['start'] < min_duration and gap <= max_gap)):
            # 合并到缓冲区
            buffer['end'] = seg['end']
            buffer['text'] = buffer['text'] + seg['text']
        else:
            # 缓冲区已足够长，输出并替换
            merged.append(buffer)
            buffer = seg.copy()

    # 最后一个缓冲区
    if buffer:
        merged.append(buffer)

    return merged


def _normalize_text_for_compare(text):
    """去除空白，仅用于判断文本内容是否发生变化（不影响实际合成/显示用的文本）"""
    return re.sub(r"\s", "", text or "")


def _load_original_lines_by_time(original_script_path):
    """读取原始 script.txt，按 (start, end) 时间戳建立文本索引

    用于判断新台词文件里的某个时间段是否被用户改动过文本内容。
    """
    index = {}
    original_script_path = Path(original_script_path)
    if not original_script_path.exists():
        return index
    for line in original_script_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        m = LINE_PATTERN.match(line)
        if not m:
            continue
        key = (round(float(m.group("start")), 2), round(float(m.group("end")), 2))
        index[key] = m.group("text").strip()
    return index


def _apply_pause_marker(line_text):
    """解析行内的 "^^" 轻微停顿标记

    用户在编辑台词时可在词间插入 "^^" 提示此处需要语气上的轻微停顿。
    GPT-SoVITS 没有真正的停顿/韵律控制标签，只认标点符号来触发停顿效果，
    因此 "^^" 不能直接传给合成引擎，而是转换成它能识别的逗号。
    字幕显示仍用不含标记、不含逗号的原始文本，保持画面文本自然可读。

    Args:
        line_text: 从 txt 行中解析出的原始文本（可能包含 "^^"）

    Returns:
        tuple: (display_text, synth_text)
            display_text: 用于字幕显示的文本（标记已去除）
            synth_text: 用于送入 TTS 合成的文本（标记已替换为逗号）
    """
    display_text = line_text.replace("^^", "")
    synth_text = line_text.replace("^^", ",")
    return display_text, synth_text


def _apply_emotion_marker(line_text):
    """解析行首的情绪标记 "[激昂]"/"[低沉]"/"[平稳]"

    供人工标注辅助模型自行判断的语气倾向，用于校正或指定某一句的朗读
    情绪。标记必须出现在行首（时间戳之后），不写则视为默认"平稳"。

    Args:
        line_text: 从 txt 行中解析出的原始文本（可能带情绪标记前缀）

    Returns:
        tuple: (rest_text, emotion_params)
            rest_text: 去除情绪标记前缀后剩余的文本（可能仍含 "^^" 标记）
            emotion_params: dict，映射到的合成参数（speed_factor/temperature）
    """
    match = EMOTION_MARKER_PATTERN.match(line_text)
    if not match:
        return line_text, dict(EMOTION_PARAMS["平稳"])
    emotion = match.group("emotion")
    return match.group("rest"), dict(EMOTION_PARAMS[emotion])


def script_to_segments(script_path, original_script_path=None):
    """
    解析带时间戳的 txt 文件，还原成分段列表

    每个 [start-end] 时间戳对应唯一一行，整行文本作为一个不可再拆分的
    合成单位（即使行内含有空格断句标记，也整行一次性发送合成，不再按
    空格拆分成多个子句分别合成）——这是因为过短的子句单独送入
    GPT-SoVITS 合成时失败率显著更高，且合并多个短子句重新合成的成功率
    也不理想，整行合成是当前最稳妥的粒度。行内空格仅作为断句的视觉提示
    保留在文本中，不影响合成请求的内容切分。

    行内可用 "^^" 标记提示语气上的轻微停顿，解析后拆成两份文本：字幕
    显示用的 text（标记已去除）和合成用的 synth_text（标记转换成
    GPT-SoVITS 能识别的逗号，间接触发停顿效果）。

    行首（时间戳之后）可用 "[激昂]"/"[低沉]"/"[平稳]" 标记人工指定这一句
    的朗读情绪，辅助模型自行判断的语气倾向。标记会映射成 speed_factor/
    temperature 合成参数（见 EMOTION_PARAMS），不写则默认按"平稳"处理；
    标记本身会从字幕显示文本和合成文本中去除，不会出现在画面或吐字中。

    Args:
        script_path: txt 文件路径
        original_script_path: 可选，原始（未编辑）台词 txt 路径。若提供，
            会按 (start, end) 时间戳与 script_path 中对应行的文本比对，
            标记该行是否被用户改动过（changed 字段），供上层决定是否
            可以直接复用原始音频而无需重新合成。

    Returns:
        list: [{'id': int, 'start': float, 'end': float, 'text': str,
                'synth_text': str, 'changed': bool,
                'speed_factor': float, 'temperature': float}, ...]
    """
    script_path = Path(script_path)
    text = script_path.read_text(encoding="utf-8")

    original_index = {}
    if original_script_path is not None:
        original_index = _load_original_lines_by_time(original_script_path)

    segments = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        match = LINE_PATTERN.match(line)
        if not match:
            # 不符合时间戳格式的行，跳过（或可以选择报错，这里选择容错跳过）
            continue

        start = float(match.group("start"))
        end = float(match.group("end"))
        line_text = match.group("text").strip()

        # 空文本行是停顿标记，不参与合成/复用判断，直接用静音填充该时间段
        is_pause = not line_text
        if is_pause:
            segments.append({
                "id": len(segments),
                "start": start,
                "end": end,
                "text": "",
                "synth_text": "",
                "line_id": len(segments),
                "line_start": start,
                "line_end": end,
                "changed": False,
                "is_pause": True,
            })
            continue

        line_text, emotion_params = _apply_emotion_marker(line_text)
        display_text, synth_text = _apply_pause_marker(line_text)

        key = (round(start, 2), round(end, 2))
        original_text = original_index.get(key)
        if original_text is not None:
            changed = _normalize_text_for_compare(line_text) != _normalize_text_for_compare(original_text)
        else:
            # 原始文件里找不到完全匹配的时间戳（如用户调整了时间轴），
            # 保守地视为改动，走重新合成
            changed = True

        segments.append({
            "id": len(segments),
            "start": start,
            "end": end,
            "text": display_text,
            "synth_text": synth_text,
            "line_id": len(segments),
            "line_start": start,
            "line_end": end,
            "changed": changed,
            "is_pause": False,
            **emotion_params,
        })

    return segments
