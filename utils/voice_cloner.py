# -*- coding: utf-8 -*-
"""
音色克隆和合成模块 - GPT-SoVITS 集成封装
"""
import os
import re
import sys
import json
import wave
import difflib
import requests
import opencc
from pathlib import Path

_T2S = opencc.OpenCC('t2s')  # 繁体转简体，用于 ASR 内容比对前的归一化


class _SynthesisFailed(RuntimeError):
    """合成重试耗尽仍未通过内容校验时抛出，携带目前为止最接近的候选结果

    供 synthesize_batch 在无法再与相邻子句合并时，用这个兜底候选保存，
    避免该句完全没有音频（静音）。
    """

    def __init__(self, message, best_bytes=None, best_duration=-1.0, best_ratio=-1.0):
        super().__init__(message)
        self.best_bytes = best_bytes
        self.best_duration = best_duration
        self.best_ratio = best_ratio


class VoiceCloner:
    """GPT-SoVITS 音色克隆和语音合成封装"""
    
    def __init__(self, api_url="http://127.0.0.1:9880", config=None, verifier=None):
        """
        Args:
            api_url: GPT-SoVITS API 地址
            config: 配置字典
            verifier: 可选的 ASR 校验器（需提供 transcribe_text(wav_path) -> str 方法），
                用于合成后核对实际吐字内容是否与台词文本一致。不传则跳过内容校验，
                仅依赖时长估算（无法检测"固定短时长但内容无效"的合成异常）。
        """
        self.api_url = api_url
        self.config = config or {}
        self.verifier = verifier
        self.check_service()
    
    def check_service(self):
        """检查 GPT-SoVITS 服务是否运行"""
        try:
            response = requests.get(f"{self.api_url}/", timeout=3)
            # 200 或 404 都说明服务在运行（404只是路由不匹配）
            if response.status_code in [200, 404]:
                print(f"✓ GPT-SoVITS 服务已连接: {self.api_url}")
                return True
        except:
            pass
        
        print(f"⚠ 警告: 无法连接到 GPT-SoVITS 服务 ({self.api_url})")
        print("请确保已启动 GPT-SoVITS 的 API 服务")
        print("启动命令: python api.py -a 127.0.0.1 -p 9880")
        return False
    
    def set_reference(self, refer_wav_path, prompt_text, prompt_language="中文"):
        """
        设置参考音频（用于克隆音色）
        
        Args:
            refer_wav_path: 参考音频路径（几秒到几十秒的样本）
            prompt_text: 参考音频对应的文本内容
            prompt_language: 参考音频语言
        """
        refer_wav_path = Path(refer_wav_path)
        
        if not refer_wav_path.exists():
            raise FileNotFoundError(f"参考音频不存在: {refer_wav_path}")
        
        self.config.update({
            'refer_wav_path': str(refer_wav_path.absolute()),
            'prompt_text': prompt_text,
            'prompt_language': prompt_language
        })
        
        print(f"✓ 已设置参考音频: {refer_wav_path.name}")
        print(f"  参考文本: {prompt_text}")
    
    @staticmethod
    def _estimate_min_duration(text, chars_per_second=3.0, safety_ratio=0.6, pause_seconds=0.15):
        """按文字数估算合理的最短语音时长（秒），用于检测合成异常截断

        标点数量额外计入少量停顿时间预期，避免逗号停顿被重复计入字数
        估算；safety_ratio 保持较严格，时长校验是第一道防线，用于快速
        拦截明显异常的坏结果，不能放得太松——放松后会让更多"内容错乱但
        时长凑巧合适"的坏结果混入 ASR 校验，而 ASR 校验本身无法做到
        100% 识别内容错误，反而降低最终输出质量。
        """
        stripped = re.sub(r"\s", "", text or "")
        punct_count = len(re.findall(r"[，,。.;；！!？?﹔、]", stripped))
        char_count = len(re.sub(r"[，,。.;；！!？?﹔、]", "", stripped))
        if char_count == 0:
            return 0.0
        return (char_count / chars_per_second) * safety_ratio + punct_count * pause_seconds

    @staticmethod
    def _get_wav_duration(wav_path):
        """读取 wav 文件实际时长（秒）"""
        try:
            with wave.open(str(wav_path), 'rb') as f:
                frames = f.getnframes()
                rate = f.getframerate()
                return frames / float(rate) if rate else 0.0
        except Exception:
            return 0.0

    @staticmethod
    def _normalize_for_compare(text):
        """去除空白/标点并统一转为简体，仅保留用于内容比对的文字字符

        ASR 转写结果常简繁混杂（如"读"识别成"讀"），不归一化会导致
        difflib 相似度被繁简字差异拉低，掩盖真正的内容错误或放过真正的异常。
        """
        text = re.sub(r"[\s\W]", "", text or "")
        return _T2S.convert(text)

    def _content_matches(self, expected_text, wav_path, min_ratio=0.75, edge_chars=2):
        """
        用 ASR 转写合成结果，核对实际吐字内容是否与台词文本一致。
        GPT-SoVITS 对部分文本会稳定返回固定短时长的无效音频（内容无法被
        ASR 识别），这种异常无法通过时长估算检测出来，必须核对实际内容。

        除整体相似度外，额外检查预期文本的开头/结尾若干字是否能在 ASR
        结果中找到——GPT-SoVITS 的短文本异常常表现为开头吞字（如"A股的
        四万万股民"被念成"苦的四万万股民"），这种局部错误有时整体相似度
        仍落在及格线附近，必须单独校验首尾关键字才能可靠拦截。

        Returns:
            (bool, str): (是否通过校验, ASR 识别出的文本)
        """
        if self.verifier is None:
            return True, None
        try:
            asr_text = self.verifier.transcribe_text(str(wav_path))
        except Exception:
            # ASR 本身失败不应阻塞合成流程，视为无法判断，放行
            return True, None

        expected_norm = self._normalize_for_compare(expected_text)
        asr_norm = self._normalize_for_compare(asr_text or "")

        if not expected_norm:
            return True, asr_text
        if not asr_norm:
            return False, asr_text

        ratio = difflib.SequenceMatcher(None, expected_norm, asr_norm).ratio()
        if ratio < min_ratio:
            return False, asr_text

        # 首尾关键字检查：预期文本开头/结尾的若干字符必须能在 ASR 文本中
        # 找到（允许顺序错位，不要求位置完全一致），防止局部吞字被整体相似度掩盖
        n = min(edge_chars, len(expected_norm))
        head = expected_norm[:n]
        tail = expected_norm[-n:]
        if head not in asr_norm or tail not in asr_norm:
            return False, asr_text

        return True, asr_text

    def synthesize(self, text, output_path, text_language="中文", max_retries=15, **kwargs):
        """
        合成语音

        Args:
            text: 要合成的文本内容（新台词）
            output_path: 输出音频路径
            text_language: 文本语言
            max_retries: 合成结果时长异常偏短/内容校验不通过时的最大重试次数
            **kwargs: 其他参数（top_k, top_p, temperature 等）

        Returns:
            str: 输出音频路径

        Raises:
            RuntimeError: 重试耗尽后仍未产生内容校验通过的音频。调用方
                （synthesize_batch）捕获后会尝试把本句与同一行的相邻子句
                合并成更长的文本重新合成——合并后文本变长能大幅降低短文本
                合成异常的概率，这是针对 GPT-SoVITS 短文本缺陷的主要应对
                手段，比单纯增加重试次数更有效。
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 映射语言名称（API v2 使用缩写）
        lang_map = {"中文": "zh", "英文": "en", "日文": "ja", "韩文": "ko", "粤语": "yue"}
        text_lang = lang_map.get(text_language, text_language)
        prompt_lang = lang_map.get(self.config.get('prompt_language', '中文'), 'zh')

        # 准备请求参数（适配 API v2）
        params = {
            'ref_audio_path': self.config.get('refer_wav_path', ''),
            'prompt_text': self.config.get('prompt_text', ''),
            'prompt_lang': prompt_lang,
            'text': text,
            'text_lang': text_lang,
        }

        # 合并额外参数
        params.update(kwargs)

        # speed_factor 会直接按比例改变输出音频时长（如 1.3 倍速对应约 1/1.3
        # 时长），时长校验的预期下限需按此折算，否则情绪标记调快语速后会被
        # 误判为"偏短异常"而不断重试
        speed_factor = params.get('speed_factor') or 1.0
        min_duration = self._estimate_min_duration(text) / speed_factor
        print(f"正在合成语音: {text[:30]}...")

        best_duration = -1.0
        best_bytes = None
        best_ratio = -1.0
        for attempt in range(1, max_retries + 1):
            try:
                # 调用 GPT-SoVITS API v2
                response = requests.post(
                    f"{self.api_url}/tts",
                    json=params,
                    timeout=600  # v3 含 super_sampling，比 v4 更慢，需要更长超时
                )
            except requests.exceptions.RequestException as e:
                raise RuntimeError(f"语音合成失败: {str(e)}")

            if response.status_code != 200:
                raise RuntimeError(f"API 返回错误: {response.status_code}, {response.text}")

            # 用临时文件读取时长，避免覆盖已保存的最佳结果
            tmp_path = output_path.with_suffix(".tmp.wav")
            with open(tmp_path, 'wb') as f:
                f.write(response.content)
            duration = self._get_wav_duration(tmp_path)

            # 时长校验不通过：直接重试，不浪费一次 ASR 调用
            if duration < min_duration:
                if best_bytes is None and duration > best_duration:
                    best_duration = duration
                    best_bytes = response.content
                tmp_path.unlink(missing_ok=True)
                print(f"⚠ 第{attempt}次合成结果偏短（{duration:.2f}s < 预期{min_duration:.2f}s），重试...")
                continue

            # 时长达标后，用 ASR 核对实际吐字内容是否与台词一致。
            # GPT-SoVITS 对部分文本会稳定返回固定短时长但内容无效的音频，
            # 仅看时长无法发现，必须核对内容才能确认合成真正成功。
            content_ok, asr_text = self._content_matches(text, tmp_path)

            # 计算相似度分数，用于重试耗尽后挑选最佳兜底结果
            expected_norm = self._normalize_for_compare(text)
            asr_norm = self._normalize_for_compare(asr_text or "")
            ratio = difflib.SequenceMatcher(None, expected_norm, asr_norm).ratio() if expected_norm else 1.0

            # 优先保留相似度更高的结果作为兜底候选，相似度相同时比较时长
            if ratio > best_ratio or (ratio == best_ratio and duration > best_duration):
                best_ratio = ratio
                best_duration = duration
                best_bytes = response.content

            tmp_path.unlink(missing_ok=True)

            if content_ok:
                with open(output_path, 'wb') as f:
                    f.write(response.content)
                print(f"✓ 语音合成完成: {output_path} ({duration:.2f}s)")
                return str(output_path)

            print(f"⚠ 第{attempt}次合成内容校验未通过（预期: {text[:20]!r}, ASR: {asr_text!r}），重试...")

        # 重试耗尽仍未通过内容校验：抛出异常交给上层决定是否合并相邻子句
        # 重新合成（见 synthesize_batch）。把目前为止最佳的候选结果通过异常
        # 对象带出去，供上层在彻底无法合并时兜底保存，避免变成完全静音。
        raise _SynthesisFailed(
            f"语音合成失败：{max_retries}次尝试内容校验均未通过，文本: {text[:30]}",
            best_bytes=best_bytes,
            best_duration=best_duration,
            best_ratio=best_ratio,
        )
    
    def synthesize_batch(self, text_segments, output_dir, **kwargs):
        """
        批量合成多段语音

        每个 text_segment 对应一整行字幕文本，逐行独立合成。若某行重试
        耗尽仍无法通过内容校验，用重试过程中相似度/时长最佳的候选结果
        兜底保存，确保该行始终有音频产出，不会变成完全静音。

        每个 text_segment 字典除 'text'/'id' 外，还可以携带自己的合成参数
        （如 'speed_factor'、'temperature'），用于实现逐句不同的语气/语速
        控制（如情绪标记映射）。这些逐句参数会覆盖 **kwargs 中的同名全局
        参数，不影响其他句子。

        Args:
            text_segments: 文本段落列表
                [{'text': '...', 'id': 0, 'speed_factor': 1.3, ...}, ...]
            output_dir: 输出目录
            **kwargs: 全局合成参数（应用于所有未单独指定的句子）
            
        Returns:
            list: 生成的音频文件路径列表
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        texts = [seg.get('text', seg) if isinstance(seg, dict) else seg for seg in text_segments]
        seg_ids = [seg.get('id', i) if isinstance(seg, dict) else i for i, seg in enumerate(text_segments)]
        # 每句独立的合成参数（如 speed_factor/temperature），覆盖全局 kwargs 中的同名项
        _RESERVED_KEYS = {'text', 'id', 'line_id'}
        per_seg_kwargs = [
            {k: v for k, v in seg.items() if k not in _RESERVED_KEYS and v is not None}
            if isinstance(seg, dict) else {}
            for seg in text_segments
        ]

        audio_files = [None] * len(text_segments)
        for idx, text in enumerate(texts):
            output_path = output_dir / f"segment_{seg_ids[idx]:03d}.wav"
            merged_kwargs = {**kwargs, **per_seg_kwargs[idx]}
            try:
                audio_files[idx] = self.synthesize(text, output_path, **merged_kwargs)
            except _SynthesisFailed as e:
                if e.best_bytes is not None:
                    with open(output_path, 'wb') as f:
                        f.write(e.best_bytes)
                    audio_files[idx] = str(output_path)
                    print(f"  ⚠ 段落 {seg_ids[idx]} 内容校验未通过，"
                          f"已保存最佳结果兜底（{e.best_duration:.2f}s, 相似度{e.best_ratio:.2f}）")
                else:
                    print(f"✗ 段落 {seg_ids[idx]} 合成失败: {str(e)}")

        print(f"\n✓ 批量合成完成: {len([a for a in audio_files if a])}/{len(text_segments)}")
        return audio_files


if __name__ == "__main__":
    # 测试代码
    cloner = VoiceCloner()
    # cloner.set_reference("reference.wav", "这是参考音频的文本")
    # cloner.synthesize("这是新的台词", "output.wav")
