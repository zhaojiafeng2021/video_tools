# -*- coding: utf-8 -*-
"""
音轨替换模块 - 将新生成的语音合并回视频
"""
import ffmpeg
from pathlib import Path
from pydub import AudioSegment


class AudioReplacer:
    """音轨替换和合并工具"""
    
    def __init__(self, fade_duration=100):
        """
        Args:
            fade_duration: 淡入淡出时长（毫秒），避免音频衔接生硬
        """
        self.fade_duration = fade_duration
    
    def replace_audio(self, video_path, new_audio_path, output_path=None, 
                     keep_original=False, original_volume=0.1):
        """
        替换视频音轨
        
        Args:
            video_path: 原始视频路径
            new_audio_path: 新的音频文件路径
            output_path: 输出视频路径
            keep_original: 是否保留原视频音轨（混音）
            original_volume: 保留原音轨时的音量比例（0.0-1.0）
            
        Returns:
            str: 输出视频路径
        """
        video_path = Path(video_path)
        new_audio_path = Path(new_audio_path)
        
        if not video_path.exists():
            raise FileNotFoundError(f"视频文件不存在: {video_path}")
        if not new_audio_path.exists():
            raise FileNotFoundError(f"音频文件不存在: {new_audio_path}")
        
        # 自动生成输出路径
        if output_path is None:
            output_path = video_path.parent / f"{video_path.stem}_replaced.mp4"
        else:
            output_path = Path(output_path)
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        print(f"开始替换音轨: {video_path.name}")
        
        try:
            video = ffmpeg.input(str(video_path))
            audio = ffmpeg.input(str(new_audio_path))
            
            if keep_original:
                # 混音模式：保留原音轨（降低音量）+ 新音轨
                original_audio = video.audio.filter('volume', original_volume)
                mixed_audio = ffmpeg.filter([original_audio, audio], 'amix', inputs=2)
                
                output = ffmpeg.output(
                    video.video, mixed_audio,
                    str(output_path),
                    vcodec='copy',  # 视频流直接复制，不重新编码
                    acodec='aac',
                    audio_bitrate='192k',
                    ar=44100,
                    ac=2
                )
            else:
                # 完全替换模式
                output = ffmpeg.output(
                    video.video, audio,
                    str(output_path),
                    vcodec='copy',
                    acodec='aac',
                    audio_bitrate='192k',
                    ar=44100,  # 采样率 44.1kHz
                    ac=2,      # 双声道
                    shortest=None  # 以视频长度为准
                )
            
            ffmpeg.run(output, overwrite_output=True, quiet=True)
            print(f"✓ 音轨替换完成: {output_path}")
            return str(output_path)
            
        except ffmpeg.Error as e:
            raise RuntimeError(f"音轨替换失败: {e.stderr.decode() if e.stderr else str(e)}")
    
    @staticmethod
    def _stretch_audio(audio_seg, stretch):
        """用 ffmpeg atempo 滤镜将音频放慢 stretch 倍（保持音调不变）

        单个 atempo 滤镜的 tempo 参数范围是 [0.5, 100]，减速超过 2 倍时
        需要串联多个 atempo 滤镜（每级最多减速到 0.5 倍）。

        Args:
            audio_seg: pydub AudioSegment
            stretch: 放慢倍数（如 1.5 表示拉长为原来的 1.5 倍时长）
        """
        import tempfile
        remaining = stretch
        tempos = []
        while remaining > 2.0:
            tempos.append(0.5)
            remaining /= 2.0
        tempos.append(1.0 / remaining)

        with tempfile.TemporaryDirectory() as tmp_dir:
            in_path = Path(tmp_dir) / "in.wav"
            out_path = Path(tmp_dir) / "out.wav"
            audio_seg.export(in_path, format="wav")
            stream = ffmpeg.input(str(in_path))
            for tempo in tempos:
                stream = stream.filter("atempo", tempo)
            ffmpeg.output(stream, str(out_path)).run(overwrite_output=True, quiet=True)
            return AudioSegment.from_file(out_path, format="wav")

    @staticmethod
    def _normalize_audio(audio_seg, target_dbfs=-18.0, max_gain=18.0):
        """将音频响度（RMS）归一化到目标 dBFS，修正 GPT-SoVITS 合成音量普遍偏低的问题

        GPT-SoVITS 合成出的语音经常存在峰值不低但整体响度（RMS）偏低的情况
        （波形动态范围大、大部分时间很轻），按峰值归一化不起作用，必须按
        平均响度（dBFS，pydub 里基于 RMS 计算）调整增益，同时限制单段最大
        增益，避免把本来就有问题的静音/底噪段放大出明显噪声。

        Args:
            audio_seg: pydub AudioSegment
            target_dbfs: 目标平均响度（dBFS），默认 -18.0，接近正常人声响度
            max_gain: 允许施加的最大增益（dB），避免噪声被过度放大
        """
        if audio_seg.dBFS == float("-inf"):
            return audio_seg
        gain = target_dbfs - audio_seg.dBFS
        gain = max(min(gain, max_gain), -max_gain)
        return audio_seg.apply_gain(gain)

    def merge_audio_segments(self, audio_files, segments_info, output_path, 
                            total_duration=None, min_fill_ratio=0.75, max_stretch=4.0,
                            target_dbfs=-18.0):
        """
        将多段音频按时间轴合并成完整音轨

        同一行（line_id 相同）拆分出的多个子句会被视为一组，组内按各子句
        真实合成时长顺序紧密衔接播放，而不是死板地贴着按字数比例估算出的
        小时间区间播放——因为子句实际时长经常超出估算区间，硬贴区间会导致
        子句间出现大量碎片静音。组的起点锚定为该行的 line_start；若组内总
        时长明显小于该行的可用时长（line_end - line_start），则对组内音频
        整体拉伸填满，避免残留大段静音；若组内总时长超出该行区间，顺延即可
        （不做破坏性加速，避免丢字）。

        Args:
            audio_files: 音频文件路径列表
            segments_info: 段落时间信息 [{'start', 'end', 'line_id', 'line_start', 'line_end'}, ...]
                若不含 line_id（如旧调用方式），则每个 segment 各自成组。
            output_path: 输出音频路径
            total_duration: 总时长（秒），如果为 None 则自动计算
            min_fill_ratio: 音频实际时长 / 该行可用时长 低于此比例时触发拉伸，避免大段静音
            max_stretch: 最大允许的拉伸倍数（放慢倍数），避免语速被拉得过慢失真
            
        Returns:
            str: 输出音频路径
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        print("开始合并音频段落...")
        
        # 计算总时长
        if total_duration is None:
            total_duration = max(seg['end'] for seg in segments_info) * 1000
        else:
            total_duration = int(total_duration * 1000)
        
        # 创建空白音轨
        merged = AudioSegment.silent(duration=total_duration)

        # 按 line_id 分组（没有 line_id 的旧格式，每个 segment 独立成组）
        groups = {}
        for idx, (audio_file, seg_info) in enumerate(zip(audio_files, segments_info)):
            line_id = seg_info.get('line_id', idx)
            groups.setdefault(line_id, []).append((audio_file, seg_info))

        for line_id, items in groups.items():
            # 依子句原始顺序排列
            audio_segs = []
            for audio_file, seg_info in items:
                if audio_file is None:
                    continue
                seg = AudioSegment.from_file(audio_file)
                # 复用原始音轨裁剪出的片段（未改动文本）保留原始响度/音色质感，
                # 不做响度归一化；只对 GPT-SoVITS 新合成的片段做归一化修正
                if seg_info.get('changed', True):
                    seg = self._normalize_audio(seg, target_dbfs)
                audio_segs.append(seg)

            if not audio_segs:
                continue

            first_seg_info = items[0][1]
            line_start = first_seg_info.get('line_start', first_seg_info['start'])
            line_end = first_seg_info.get('line_end', items[-1][1]['end'])
            line_slot_ms = (line_end - line_start) * 1000

            # 组内子句顺序衔接，衔接处留极短间隔模拟自然停顿
            gap_ms = 80
            total_audio_ms = sum(len(s) for s in audio_segs) + gap_ms * (len(audio_segs) - 1)

            # 实际时长明显小于该行可用时长时，整体拉伸填满，避免残留大段静音
            if line_slot_ms > 0 and total_audio_ms > 0:
                fill_ratio = total_audio_ms / line_slot_ms
                if fill_ratio < min_fill_ratio:
                    stretch = min(line_slot_ms / total_audio_ms, max_stretch)
                    if stretch > 1.0:
                        audio_segs = [self._stretch_audio(s, stretch) for s in audio_segs]
                        total_audio_ms = sum(len(s) for s in audio_segs) + gap_ms * (len(audio_segs) - 1)
                        print(f"  ⚠ 第{line_id}行时长不足（填充率{fill_ratio:.0%}），整体拉伸{stretch:.2f}倍至 {total_audio_ms/1000:.2f}s")

            # 顺序衔接写入主音轨，起点锚定该行的 line_start
            cursor_ms = int(line_start * 1000)
            for i, audio_seg in enumerate(audio_segs):
                audio_seg = audio_seg.fade_in(self.fade_duration).fade_out(self.fade_duration)
                merged = merged.overlay(audio_seg, position=cursor_ms)
                cursor_ms += len(audio_seg) + (gap_ms if i < len(audio_segs) - 1 else 0)
        
        # 导出
        merged.export(output_path, format='wav')
        print(f"✓ 音频合并完成: {output_path}")
        return str(output_path)


if __name__ == "__main__":
    # 测试代码
    replacer = AudioReplacer()
    # replacer.replace_audio("original.mp4", "new_audio.wav", "output.mp4")
