"""
翻译 Agent - A2A 远程智能体的核心业务逻辑

这是 A2A 服务器端的"大脑"，负责实际的翻译业务处理。
在真实场景中，这里可以接入 LLM、翻译 API 等服务。
本 Demo 使用模拟翻译来演示 A2A 协议的完整流程。
"""

import asyncio
from collections.abc import AsyncGenerator


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
    }

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

        注意：当前 Demo 中 AgentExecutor 仅使用了 invoke() 方法。
        stream() 方法保留供扩展使用，展示如何实现流式业务逻辑。
        若要启用，可在 TranslatorAgentExecutor.execute() 中替换
        invoke() 调用为 stream() 调用。

        Args:
            text: 待翻译的中文文本

        Yields:
            翻译结果的每个单词
        """
        result = await self.invoke(text)
        words = result.split()
        for i, word in enumerate(words):
            await asyncio.sleep(0.3)  # 模拟逐词生成的延迟
            if i < len(words) - 1:
                yield word + " "
            else:
                yield word  # 最后一个词不加空格
