# -*- coding: utf-8 -*-
"""
语音转写模块 - 使用 Whisper 识别音频内容
"""
import whisper
import json
from pathlib import Path


class SpeechTranscriber:
    """使用 Whisper 进行语音识别和转写"""
    
    def __init__(self, model_name='base', language='zh'):
        """
        Args:
            model_name: Whisper 模型名称 (tiny/base/small/medium/large)
            language: 语言代码，zh=中文, en=英文
        """
        self.model_name = model_name
        self.language = language
        print(f"正在加载 Whisper 模型: {model_name}...")
        self.model = whisper.load_model(model_name)
        print("✓ Whisper 模型加载完成")
    
    def transcribe(self, audio_path, output_json=None):
        """
        转写音频内容
        
        Args:
            audio_path: 输入音频文件路径
            output_json: 输出 JSON 路径，保存详细转写结果
            
        Returns:
            dict: 转写结果，包含 text(全文) 和 segments(分段)
        """
        audio_path = Path(audio_path)
        
        if not audio_path.exists():
            raise FileNotFoundError(f"音频文件不存在: {audio_path}")
        
        print(f"开始转写音频: {audio_path.name}")
        
        # 执行转写
        # word_timestamps=True 可以获得更精细的词级时间戳
        # condition_on_previous_text=True 利用上下文提升连贯性
        result = self.model.transcribe(
            str(audio_path),
            language=self.language,
            verbose=False,
            word_timestamps=True,
            condition_on_previous_text=True,
            # 中文优化：提示模型这是正式演讲/对话场景，包含关键词提示
            initial_prompt="这是一段正式的演讲或对话内容，可能涉及历史、政治、法律等话题，包含盗窃、愤怒等词汇。"
        )
        
        # 整理输出格式
        transcription = {
            'text': result['text'],
            'language': result['language'],
            'segments': [
                {
                    'id': seg['id'],
                    'start': seg['start'],
                    'end': seg['end'],
                    'text': seg['text'].strip()
                }
                for seg in result['segments']
            ]
        }
        
        # 保存 JSON
        if output_json:
            output_json = Path(output_json)
            output_json.parent.mkdir(parents=True, exist_ok=True)
            with open(output_json, 'w', encoding='utf-8') as f:
                json.dump(transcription, f, ensure_ascii=False, indent=2)
            print(f"✓ 转写结果已保存: {output_json}")
        
        # 打印分段内容
        print("\n=== 转写内容 ===")
        for seg in transcription['segments']:
            print(f"[{seg['start']:.2f}s - {seg['end']:.2f}s] {seg['text']}")
        print("=" * 50)
        
        return transcription

    def transcribe_text(self, audio_path):
        """
        仅返回转写文本，用于合成后内容核对等轻量场景
        （不打印分段、不保存 json，避免干扰调用方日志）

        Args:
            audio_path: 输入音频文件路径

        Returns:
            str: 识别出的文本
        """
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"音频文件不存在: {audio_path}")

        result = self.model.transcribe(
            str(audio_path),
            language=self.language,
            verbose=False,
        )
        return result["text"].strip()


if __name__ == "__main__":
    # 测试代码
    transcriber = SpeechTranscriber()
    # transcriber.transcribe("test_audio.wav", "transcription.json")
