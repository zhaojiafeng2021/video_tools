# -*- coding: utf-8 -*-
"""
音频提取模块 - 从视频中提取音轨
"""
import os
import ffmpeg
from pathlib import Path


class AudioExtractor:
    """从视频文件中提取音频"""
    
    def __init__(self, output_format='wav', sample_rate=16000):
        """
        Args:
            output_format: 输出音频格式，默认 wav
            sample_rate: 采样率，默认 16000（Whisper 推荐）
        """
        self.output_format = output_format
        self.sample_rate = sample_rate
    
    def extract(self, video_path, output_path=None):
        """
        从视频提取音频
        
        Args:
            video_path: 输入视频路径
            output_path: 输出音频路径，如不指定则自动生成
            
        Returns:
            str: 输出音频文件路径
        """
        video_path = Path(video_path)
        
        if not video_path.exists():
            raise FileNotFoundError(f"视频文件不存在: {video_path}")
        
        # 自动生成输出路径
        if output_path is None:
            output_path = video_path.parent / f"{video_path.stem}_audio.{self.output_format}"
        else:
            output_path = Path(output_path)
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            # 使用 ffmpeg 提取音频
            stream = ffmpeg.input(str(video_path))
            stream = ffmpeg.output(
                stream, 
                str(output_path),
                acodec='pcm_s16le' if self.output_format == 'wav' else 'libmp3lame',
                ar=self.sample_rate,
                ac=1  # 转为单声道
            )
            ffmpeg.run(stream, overwrite_output=True, quiet=True)
            
            print(f"✓ 音频提取完成: {output_path}")
            return str(output_path)
            
        except ffmpeg.Error as e:
            raise RuntimeError(f"音频提取失败: {e.stderr.decode() if e.stderr else str(e)}")

    def cut(self, audio_path, output_path, start=0.0, end=None):
        """
        按时间段截取音频片段

        Args:
            audio_path: 输入音频路径
            output_path: 输出音频路径
            start: 起始时间（秒）
            end: 结束时间（秒），None 表示到结尾

        Returns:
            str: 输出音频文件路径
        """
        audio_path = Path(audio_path)
        output_path = Path(output_path)

        if not audio_path.exists():
            raise FileNotFoundError(f"音频文件不存在: {audio_path}")

        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            kwargs = {'ss': start}
            if end is not None:
                kwargs['t'] = max(end - start, 0.1)

            stream = ffmpeg.input(str(audio_path), **kwargs)
            stream = ffmpeg.output(
                stream,
                str(output_path),
                acodec='pcm_s16le' if self.output_format == 'wav' else 'libmp3lame',
                ar=self.sample_rate,
                ac=1
            )
            ffmpeg.run(stream, overwrite_output=True, quiet=True)

            print(f"✓ 音频截取完成: {output_path}")
            return str(output_path)

        except ffmpeg.Error as e:
            raise RuntimeError(f"音频截取失败: {e.stderr.decode() if e.stderr else str(e)}")


if __name__ == "__main__":
    # 测试代码
    extractor = AudioExtractor()
    # extractor.extract("test_video.mp4")
