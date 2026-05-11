"""
翻译客户端智能体 - A2A 客户端

TranslatorClientAgent 封装了与 A2A 远程智能体交互的全部逻辑：
1. 发现远程 Agent（获取 Agent Card）
2. 发送非流式翻译请求
3. 发送流式翻译请求

在真实场景中，客户端智能体可以同时连接多个远程 Agent，
并根据任务需求选择合适的 Agent 进行协作。
"""

import logging
from collections.abc import AsyncGenerator

import httpx

from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.helpers import new_text_message
from a2a.types import AgentCard
from a2a.types.a2a_pb2 import (
    Role,
    SendMessageRequest,
    StreamResponse,
)

logger = logging.getLogger(__name__)


class TranslatorClientAgent:
    """翻译客户端智能体。

    封装 A2A 客户端的核心功能，提供简洁的 API 供用户层调用。

    使用流程：
        1. 调用 discover() 发现远程 Agent
        2. 调用 translate() 或 translate_stream() 发送翻译请求
        3. 调用 close() 释放资源
    """

    def __init__(self, server_url: str = "http://127.0.0.1:9999"):
        """初始化客户端智能体。

        Args:
            server_url: A2A 远程智能体的服务地址
        """
        self.server_url = server_url
        self.agent_card: AgentCard | None = None

    async def discover(self) -> AgentCard:
        """发现远程 Agent — 获取 Agent Card。

        Agent Card 包含了远程 Agent 的名称、描述、技能列表等元信息。
        这是 A2A 协议交互的第一步。

        Returns:
            AgentCard: 远程 Agent 的名片信息
        """
        card_url = f"{self.server_url}/.well-known/agent-card.json"
        logger.info("📡 [客户端] ========== Agent 发现请求 ==========")
        logger.info("📡 [客户端] GET %s", card_url)

        async with httpx.AsyncClient() as httpx_client:
            resolver = A2ACardResolver(
                httpx_client=httpx_client,
                base_url=self.server_url,
            )
            self.agent_card = await resolver.get_agent_card()

        logger.info("📡 [客户端] ✅ Agent Card 响应:")
        logger.info("📡 [客户端]   名称: %s", self.agent_card.name)
        logger.info("📡 [客户端]   版本: %s", self.agent_card.version)
        logger.info("📡 [客户端]   技能数: %d", len(self.agent_card.skills) if self.agent_card.skills else 0)
        if self.agent_card.supported_interfaces:
            for iface in self.agent_card.supported_interfaces:
                logger.info("📡 [客户端]   接口: %s → %s", iface.protocol_binding, iface.url)
        logger.info("📡 [客户端] =====================================")

        return self.agent_card

    async def translate(self, text: str) -> str:
        """非流式翻译 — 发送文本并等待完整翻译结果。

        Args:
            text: 待翻译的中文文本

        Returns:
            翻译结果的文本内容

        Raises:
            ConnectionError: 无法连接到远程 Agent
            RuntimeError: 翻译过程中发生错误
        """
        if not self.agent_card:
            await self.discover()

        # 创建非流式客户端
        config = ClientConfig(streaming=False)
        client = await create_client(
            agent=self.agent_card, client_config=config
        )

        try:
            # 构造用户消息
            message = new_text_message(text, role=Role.ROLE_USER)
            request = SendMessageRequest(message=message)

            # 日志：打印底层物理请求信息
            target_url = self._resolve_rpc_url()
            logger.info("📡 [客户端] ========== 非流式翻译请求 ==========")
            logger.info("📡 [客户端] POST %s", target_url)
            logger.info("📡 [客户端] 请求方式: JSON-RPC (非流式)")
            logger.info("📡 [客户端] 用户消息: \"%s\"", text)
            logger.info("📡 [客户端] SendMessageRequest 原始内容:")
            logger.info("📡 [客户端]   message.role: %s", message.role)
            logger.info("📡 [客户端]   message.parts[0].text: \"%s\"", text)

            # 发送请求并收集响应
            result_text = ""
            chunk_index = 0
            async for chunk in client.send_message(request):
                chunk_index += 1
                payload_type = chunk.WhichOneof("payload")
                logger.info("📡 [客户端] --- 响应 chunk #%d ---", chunk_index)
                logger.info("📡 [客户端]   payload 类型: %s", payload_type)
                logger.info("📡 [客户端]   原始内容: %s", str(chunk)[:500])
                # 解析响应中的文本内容
                result_text = self._extract_text_from_response(chunk)

            logger.info("📡 [客户端] ✅ 翻译结果: \"%s\"", result_text)
            logger.info("📡 [客户端] =====================================")
            return result_text
        finally:
            if client:
                await client.close()

    async def translate_stream(
        self, text: str
    ) -> AsyncGenerator[StreamResponse, None]:
        """流式翻译 — 发送文本并逐步接收翻译结果。

        Args:
            text: 待翻译的中文文本

        Yields:
            StreamResponse: 每次收到的 A2A 流式响应 chunk
        """
        if not self.agent_card:
            await self.discover()

        # 创建流式客户端
        config = ClientConfig(streaming=True)
        client = await create_client(
            agent=self.agent_card, client_config=config
        )

        try:
            message = new_text_message(text, role=Role.ROLE_USER)
            request = SendMessageRequest(message=message)

            # 日志：打印底层物理请求信息
            target_url = self._resolve_rpc_url()
            logger.info("📡 [客户端] ========== 流式翻译请求 ==========")
            logger.info("📡 [客户端] POST %s", target_url)
            logger.info("📡 [客户端] 请求方式: JSON-RPC (SSE 流式)")
            logger.info("📡 [客户端] 用户消息: \"%s\"", text)
            logger.info("📡 [客户端] SendMessageRequest 原始内容:")
            logger.info("📡 [客户端]   message.role: %s", message.role)
            logger.info("📡 [客户端]   message.parts[0].text: \"%s\"", text)

            chunk_index = 0
            async for chunk in client.send_message(request):
                chunk_index += 1
                payload_type = chunk.WhichOneof("payload")
                logger.info("📡 [客户端] --- 流式响应 chunk #%d ---", chunk_index)
                logger.info("📡 [客户端]   payload 类型: %s", payload_type)
                logger.info("📡 [客户端]   原始内容: %s", str(chunk)[:500])
                yield chunk

            logger.info("📡 [客户端] ✅ 流式传输完成，共 %d 个 chunk", chunk_index)
            logger.info("📡 [客户端] =====================================")
        finally:
            if client:
                await client.close()

    def display_agent_info(self):
        """展示远程 Agent 的信息。"""
        if not self.agent_card:
            print("  尚未发现远程 Agent，请先调用 discover()")
            return

        print(f"  名称:    {self.agent_card.name}")
        print(f"  描述:    {self.agent_card.description}")
        print(f"  版本:    {self.agent_card.version}")
        if self.agent_card.skills:
            print(f"  技能列表:")
            for skill in self.agent_card.skills:
                print(f"    - {skill.name}: {skill.description}")
                if skill.examples:
                    examples_str = ", ".join(
                        f'"{e}"' for e in skill.examples
                    )
                    print(f"      示例输入: {examples_str}")

    def _resolve_rpc_url(self) -> str:
        """解析实际的 JSON-RPC 请求 URL。

        A2A SDK 的 create_client() 会从 AgentCard 的
        supported_interfaces 中取出 URL 作为 RPC 端点。

        Returns:
            实际发送 JSON-RPC 请求的 URL
        """
        if self.agent_card and self.agent_card.supported_interfaces:
            return self.agent_card.supported_interfaces[0].url
        return self.server_url

    @staticmethod
    def _extract_text_from_response(response) -> str:
        """从 A2A StreamResponse 中提取翻译结果文本。

        StreamResponse 使用 'payload' oneof 字段，包含以下类型之一：
        - task: 完整的 Task 对象（非流式时返回，含 artifacts）
        - message: Message 对象
        - status_update: TaskStatusUpdateEvent
        - artifact_update: TaskArtifactUpdateEvent

        Args:
            response: A2A SDK 返回的 StreamResponse 对象

        Returns:
            提取到的翻译结果文本
        """
        # 使用 WhichOneof 判断响应类型
        payload_type = response.WhichOneof("payload")

        if payload_type == "task":
            # 完整 Task 对象 — 从 artifacts 中提取翻译结果
            task = response.task
            if task.artifacts:
                for artifact in task.artifacts:
                    for part in artifact.parts:
                        if part.HasField("text"):
                            return part.text
            # 备选：从 status.message 中提取
            if task.status and task.status.message:
                for part in task.status.message.parts:
                    if part.HasField("text"):
                        return part.text

        elif payload_type == "message":
            # Message 对象
            msg = response.message
            for part in msg.parts:
                if part.HasField("text"):
                    return part.text

        elif payload_type == "artifact_update":
            # Artifact 更新事件
            artifact = response.artifact_update.artifact
            for part in artifact.parts:
                if part.HasField("text"):
                    return part.text

        elif payload_type == "status_update":
            # 状态更新事件
            status = response.status_update.status
            if status.message:
                for part in status.message.parts:
                    if part.HasField("text"):
                        return part.text

        return str(response)
