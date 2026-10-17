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


def script_to_segments(script_path, original_script_path=None):
    """
    解析带时间戳的 txt 文件，还原成分段列表

    每个 [start-end] 时间戳对应唯一一行，整行文本作为一个不可再拆分的
    合成单位（即使行内含有空格断句标记，也整行一次性发送合成，不再按
    空格拆分成多个子句分别合成）——这是因为过短的子句单独送入
    GPT-SoVITS 合成时失败率显著更高，且合并多个短子句重新合成的成功率
    也不理想，整行合成是当前最稳妥的粒度。行内空格仅作为断句的视觉提示
    保留在文本中，不影响合成请求的内容切分。

    Args:
        script_path: txt 文件路径
        original_script_path: 可选，原始（未编辑）台词 txt 路径。若提供，
            会按 (start, end) 时间戳与 script_path 中对应行的文本比对，
            标记该行是否被用户改动过（changed 字段），供上层决定是否
            可以直接复用原始音频而无需重新合成。

    Returns:
        list: [{'id': int, 'start': float, 'end': float, 'text': str, 'changed': bool}, ...]
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
            "text": line_text,
            "line_id": len(segments),
            "line_start": start,
            "line_end": end,
            "changed": changed,
        })

    return segments
