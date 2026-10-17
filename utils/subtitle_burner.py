# -*- coding: utf-8 -*-
"""
字幕遮盖重绘模块 - 用于处理视频里烧录在画面上的硬字幕

原理：原字幕是画面像素的一部分，无法直接编辑文字内容。
这里用简易方案：在字幕区域画一个不透明色块盖住旧字幕，再在同一位置画上新文本。
效果说明：只适合背景简单/非正式场合，无法做到无痕替换（原字幕位置会出现明显色块）。
"""
import subprocess
from pathlib import Path

FFMPEG_BIN = "ffmpeg"


class SubtitleBurner:
    """字幕区域遮盖 + 重绘新文字"""

    def __init__(self, box_color="black@0.97", font_size=42, font_color="white",
                 box_y_ratio=0.80, box_height_ratio=0.25, font_path=None):
        """
        Args:
            box_color: 遮盖色块颜色（ffmpeg color 格式，支持透明度）
            font_size: 新字幕字号
            font_color: 新字幕颜色
            box_y_ratio: 遮盖条顶部位置占视频高度的比例（字幕通常在画面下方）
            box_height_ratio: 遮盖条高度占视频高度的比例
            font_path: 字体文件路径，None 则使用 ffmpeg 默认字体
        """
        self.box_color = box_color
        self.font_size = font_size
        self.font_color = font_color
        self.box_y_ratio = box_y_ratio
        self.box_height_ratio = box_height_ratio
        self.font_path = font_path

    def burn(self, video_path, segments, output_path):
        """
        对视频按时间段遮盖旧字幕并画上新文本

        Args:
            video_path: 输入视频路径（已完成音轨替换）
            segments: [{'start': float, 'end': float, 'text': str}, ...]
            output_path: 输出视频路径

        Returns:
            str: 输出视频路径
        """
        video_path = Path(video_path)
        output_path = Path(output_path)

        if not video_path.exists():
            raise FileNotFoundError(f"视频文件不存在: {video_path}")

        output_path.parent.mkdir(parents=True, exist_ok=True)

        if not segments:
            # 没有台词需要画字幕，直接复制
            subprocess.run(
                [FFMPEG_BIN, "-y", "-i", str(video_path), "-c", "copy", str(output_path)],
                check=True, capture_output=True
            )
            return str(output_path)

        filter_str = self._build_filter(segments)

        cmd = [
            FFMPEG_BIN, "-y",
            "-i", str(video_path),
            "-vf", filter_str,
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "copy",
            str(output_path),
        ]

        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            raise RuntimeError(f"字幕烧录失败: {result.stderr.decode(errors='ignore')}")

        print(f"✓ 字幕遮盖重绘完成: {output_path}")
        return str(output_path)

    def _build_filter(self, segments):
        """构建 drawbox + drawtext 的 filter 链"""
        # drawbox 滤镜上下文里画面尺寸变量是小写 ih/iw
        box_y_drawbox = f"ih*{self.box_y_ratio}"
        box_h_drawbox = f"ih*{self.box_height_ratio}"
        # drawtext 滤镜上下文里画面尺寸变量是大写 H/W（text 尺寸才是小写 text_w/text_h）
        box_y_drawtext = f"H*{self.box_y_ratio}"
        box_h_drawtext = f"H*{self.box_height_ratio}"

        filters = []
        for seg in segments:
            start, end = seg["start"], seg["end"]
            # 遮盖条：覆盖整个画面宽度
            filters.append(
                f"drawbox=x=0:y={box_y_drawbox}:w=iw:h={box_h_drawbox}:color={self.box_color}:t=fill:"
                f"enable='between(t,{start},{end})'"
            )

        for seg in segments:
            start, end = seg["start"], seg["end"]
            text = self._escape_text(seg["text"])
            font_option = f"fontfile='{self.font_path}':" if self.font_path else ""
            filters.append(
                f"drawtext={font_option}text='{text}':fontsize={self.font_size}:"
                f"fontcolor={self.font_color}:x=(w-text_w)/2:y=({box_y_drawtext})+(({box_h_drawtext})-text_h)/2:"
                f"enable='between(t,{start},{end})'"
            )

        return ",".join(filters)

    @staticmethod
    def _escape_text(text):
        """转义 ffmpeg drawtext 的特殊字符"""
        text = text.replace("\\", "\\\\")
        text = text.replace(":", "\\:")
        text = text.replace("'", "\u2019")  # 用右单引号替代，避免破坏 filter 语法
        text = text.replace("%", "\\%")
        return text


if __name__ == "__main__":
    # 测试代码
    burner = SubtitleBurner()
    # burner.burn("audio_replaced.mp4", [{'start': 0, 'end': 3, 'text': '新字幕'}], "output.mp4")
