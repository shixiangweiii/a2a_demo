"""
翻译 Agent - A2A 远程智能体的核心业务逻辑

这是 A2A 服务器端的“大脑”，负责实际的翻译业务处理。
在真实场景中，这里可以接入 LLM、翻译 API 等服务。
本 Demo 使用模拟翻译来演示 A2A 协议的完整流程，并新增：
- classify_input：对输入打分，用于演示 input-required / reject 流转
- slow_translate：分段慢速输出，用于演示 Cancel
"""

import asyncio
from collections.abc import AsyncGenerator
from typing import TypedDict


class InputVerdict(TypedDict, total=False):
    """输入仲裁结果。

    ok 为 True 时表示可续执行翻译；
    ok 为 False 时必附带 reason（"empty" / "ambiguous" / "not_chinese"）与 hint（面向用户的提示文案）。
    """

    ok: bool
    reason: str
    hint: str


class TranslatorAgent:
    """模拟翻译 Agent — 将中文翻译为英文。

    在真实场景中，这里可以替换为调用大语言模型或翻译 API。
    本 Demo 使用预设词典 + 简单规则来模拟翻译过程。
    """

    # 预设翻译词典
    MOCK_TRANSLATIONS: dict[str, str] = {
        "你好": "Hello",
        "世界": "World",
        "你好世界": "Hello World",
        "谢谢": "Thank you",
        "早上好": "Good morning",
        "晚安": "Good night",
        "我是一个AI助手": "I am an AI assistant",
        "今天天气怎么样": "How is the weather today",
        "人工智能": "Artificial Intelligence",
        "机器学习": "Machine Learning",
        # 用于慢速翻译演示的长句子
        "科技与艺术的完美结合": "The perfect combination of technology and art",
    }

    # --- 输入仲裁（服务于 input-required / reject 演示） ------------------
    _AMBIGUOUS_PROMPTS = {"翻译", "请翻译", "帮我翻译", "翻译一下"}

    def classify_input(self, text: str) -> InputVerdict:
        """判断输入是否满足翻译前提。

        三种不合格情形：
        - empty：文本为空或只有空白 → input-required
        - ambiguous：只发了 "翻译" / "请翻译" 等模糊指令 → input-required
        - not_chinese：内容不含任何中文字符 → reject（本 Agent 仅接中→英）
        """
        stripped = text.strip()
        if not stripped:
            return {
                "ok": False,
                "reason": "empty",
                "hint": "请提供您要翻译的中文内容。",
            }
        if stripped in self._AMBIGUOUS_PROMPTS:
            return {
                "ok": False,
                "reason": "ambiguous",
                "hint": "您想翻译什么内容？请直接发送待翻译的中文文本。",
            }
        has_chinese = any("\u4e00" <= ch <= "\u9fff" for ch in stripped)
        if not has_chinese:
            return {
                "ok": False,
                "reason": "not_chinese",
                "hint": "本 Agent 仅支持中→英翻译，请输入中文内容。",
            }
        return {"ok": True}

    async def invoke(self, text: str) -> str:
        """同步翻译 — 接收中文文本，返回完整的英文翻译结果。

        Args:
            text: 待翻译的中文文本

        Returns:
            翻译后的英文文本
        """
        # 模拟翻译处理延时（真实场景中是 API 调用耗时）
        await asyncio.sleep(0.5)

        # 查找预设翻译，找不到则返回带标记的原文
        result = self.MOCK_TRANSLATIONS.get(
            text.strip(),
            f"[Translated] {text.strip()}"
        )
        return result

    async def stream(self, text: str) -> AsyncGenerator[str, None]:
        """流式翻译 — 逐词返回翻译结果。

        模拟流式输出的效果，每个词之间有短暂延迟，
        类似于大语言模型逐 token 输出的体验。
        """
        result = await self.invoke(text)
        words = result.split()
        for i, word in enumerate(words):
            await asyncio.sleep(0.3)  # 模拟逐词生成的延迟
            if i < len(words) - 1:
                yield word + " "
            else:
                yield word  # 最后一个词不加空格

    # --- 批次 C新增：批量翻译 & 翻译报告业务方法 ---
    async def translate_batch(
        self, items: list[str]
    ) -> list[dict[str, str]]:
        """批量翻译 — 配合 DataPart 演示。

        Args:
            items: 待翻译的中文文本列表。

        Returns:
            每项包含 source/target/hit 的字典列表，hit 表示是否命中预设词典。
        """
        results: list[dict[str, str]] = []
        for item in items:
            stripped = (item or "").strip()
            if not stripped:
                results.append({"source": item, "target": "", "hit": "skip"})
                continue
            if stripped in self.MOCK_TRANSLATIONS:
                target = self.MOCK_TRANSLATIONS[stripped]
                hit = "dict"
            else:
                target = f"[Translated] {stripped}"
                hit = "fallback"
            # 统一模拟少量延迟，贴近真实批处理体验
            await asyncio.sleep(0.1)
            results.append({"source": stripped, "target": target, "hit": hit})
        return results

    async def build_translation_report(
        self, text: str
    ) -> tuple[str, str, str]:
        """翻译报告 — 配合 FilePart 演示。

        返回 (filename, media_type, content_bytes_utf8)，供 executor 打包成 FilePart。
        """
        target = await self.invoke(text)
        lines = [
            "==== Translator Agent Report ====",
            f"source: {text.strip()}",
            f"target: {target}",
            f"dict_hit: {text.strip() in self.MOCK_TRANSLATIONS}",
            f"char_count: {len(text.strip())}",
            "=================================",
        ]
        content = "\n".join(lines) + "\n"
        filename = "translation_report.txt"
        media_type = "text/plain; charset=utf-8"
        return filename, media_type, content

    async def slow_translate(
        self,
        text: str,
        cancel_event: asyncio.Event | None = None,
        step_delay: float = 0.8,
    ) -> AsyncGenerator[tuple[int, int, str], None]:
        """慢速翻译 — 分段逐步产出，用于演示 Cancel 流程。

        每次循环会检查 cancel_event，若已 set 则提前结束。

        Yields:
            (segment_index, total_segments, accumulated_text)
        """
        result = await self.invoke(text)
        # 凑足 ≥10 段：若英文词数不够，则按字符粗粒度拆分
        words = result.split()
        if len(words) < 10:
            # 按字符粉碑，拆为不少于 10 段（给 Cancel 留出时间窗）
            seg_len = max(1, len(result) // 10) or 1
            words = [result[i:i + seg_len] for i in range(0, len(result), seg_len)]

        total = len(words)
        accumulated_parts: list[str] = []
        for idx, w in enumerate(words, start=1):
            if cancel_event is not None and cancel_event.is_set():
                return
            await asyncio.sleep(step_delay)
            if cancel_event is not None and cancel_event.is_set():
                return
            accumulated_parts.append(w)
            accumulated = (
                " ".join(accumulated_parts)
                if " ".join(words) == result  # 原本就是按词拆
                else "".join(accumulated_parts)
            )
            yield idx, total, accumulated
