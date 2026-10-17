# -*- coding: utf-8 -*-
"""
视频语音替换主流程脚本
自动完成：音频提取 → 转写 → 音色克隆 → 新台词合成 → 音轨替换
"""
import os
import sys
import json
import argparse
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent))

from utils.audio_extractor import AudioExtractor
from utils.speech_transcriber import SpeechTranscriber
from utils.voice_cloner import VoiceCloner
from utils.audio_replacer import AudioReplacer


def load_config(config_path='config.json'):
    """加载配置文件"""
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description='视频语音替换工具')
    parser.add_argument('video', help='输入视频文件路径')
    parser.add_argument('--refer-audio', required=True, help='参考音频路径（用于克隆音色）')
    parser.add_argument('--refer-text', required=True, help='参考音频对应的文本')
    parser.add_argument('--new-script', help='新台词文本文件路径（每行一句）')
    parser.add_argument('--new-text', help='直接指定新台词文本（单句）')
    parser.add_argument('--output', help='输出视频路径')
    parser.add_argument('--config', default='config.json', help='配置文件路径')
    parser.add_argument('--keep-original', action='store_true', help='保留原音轨（混音模式）')
    parser.add_argument('--skip-transcribe', action='store_true', help='跳过转写步骤（如果已有转写结果）')
    
    args = parser.parse_args()
    
    # 加载配置
    config = load_config(args.config)
    
    video_path = Path(args.video)
    work_dir = video_path.parent / f"{video_path.stem}_workspace"
    work_dir.mkdir(exist_ok=True)
    
    print("=" * 60)
    print("视频语音替换流程启动")
    print("=" * 60)
    
    # 步骤 1: 提取音频
    print("\n[步骤 1/5] 提取原视频音频...")
    extractor = AudioExtractor()
    audio_path = work_dir / f"{video_path.stem}_original.wav"
    extractor.extract(args.video, audio_path)
    
    # 步骤 2: 转写原音频（可选，用于了解原台词时间轴）
    transcription = None
    if not args.skip_transcribe:
        print("\n[步骤 2/5] 转写原音频内容...")
        transcriber = SpeechTranscriber(
            model_name=config['whisper_model'],
            language=config['whisper_language']
        )
        transcription_json = work_dir / "transcription.json"
        transcription = transcriber.transcribe(audio_path, transcription_json)
    else:
        print("\n[步骤 2/5] 跳过转写（使用 --skip-transcribe）")
        # 尝试加载已有转写结果
        transcription_json = work_dir / "transcription.json"
        if transcription_json.exists():
            with open(transcription_json, 'r', encoding='utf-8') as f:
                transcription = json.load(f)
    
    # 步骤 3: 准备新台词
    print("\n[步骤 3/5] 准备新台词...")
    new_texts = []
    
    if args.new_script:
        # 从文件读取多行台词
        with open(args.new_script, 'r', encoding='utf-8') as f:
            new_texts = [line.strip() for line in f if line.strip()]
    elif args.new_text:
        # 单句台词
        new_texts = [args.new_text]
    else:
        raise ValueError("必须指定 --new-script 或 --new-text")
    
    print(f"  新台词共 {len(new_texts)} 句:")
    for i, text in enumerate(new_texts, 1):
        print(f"    {i}. {text}")
    
    # 步骤 4: 音色克隆和合成
    print("\n[步骤 4/5] 克隆音色并合成新语音...")
    cloner = VoiceCloner(config=config.get('gptsovits', {}))
    cloner.set_reference(
        args.refer_audio,
        args.refer_text,
        config['gptsovits'].get('prompt_language', '中文')
    )
    
    synthesis_dir = work_dir / "synthesized"
    synthesis_dir.mkdir(exist_ok=True)
    
    if len(new_texts) == 1:
        # 单句合成
        new_audio = synthesis_dir / "new_audio.wav"
        cloner.synthesize(new_texts[0], new_audio)
        merged_audio = new_audio
    else:
        # 多句合成 + 合并
        # 如果有转写信息，使用原时间轴；否则等间隔分配
        if transcription and len(transcription['segments']) >= len(new_texts):
            segments_info = transcription['segments'][:len(new_texts)]
        else:
            # 简单等分时间轴
            if transcription:
                total_duration = transcription['segments'][-1]['end']
            else:
                # 估算：每句 3 秒
                total_duration = len(new_texts) * 3.0
            
            segment_duration = total_duration / len(new_texts)
            segments_info = [
                {
                    'id': i,
                    'start': i * segment_duration,
                    'end': (i + 1) * segment_duration,
                    'text': text
                }
                for i, text in enumerate(new_texts)
            ]
        
        # 批量合成
        audio_files = cloner.synthesize_batch(
            [{'id': i, 'text': text} for i, text in enumerate(new_texts)],
            synthesis_dir
        )
        
        # 合并音频段落
        print("\n  合并音频段落...")
        replacer = AudioReplacer(fade_duration=config['output']['audio_fade_duration'] * 1000)
        merged_audio = work_dir / "merged_audio.wav"
        replacer.merge_audio_segments(audio_files, segments_info, merged_audio)
    
    # 步骤 5: 替换音轨
    print("\n[步骤 5/5] 将新音轨合并到视频...")
    replacer = AudioReplacer()
    
    if args.output:
        output_video = args.output
    else:
        output_video = video_path.parent / f"{video_path.stem}_replaced.mp4"
    
    replacer.replace_audio(
        args.video,
        merged_audio,
        output_video,
        keep_original=args.keep_original
    )
    
    print("\n" + "=" * 60)
    print("✓ 全部完成！")
    print(f"  输出视频: {output_video}")
    print(f"  工作目录: {work_dir}")
    print("=" * 60)


if __name__ == "__main__":
    main()
