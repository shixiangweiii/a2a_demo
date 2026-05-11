"""
翻译客户端智能体 - A2A 客户端

TranslatorClientAgent 封装了与 A2A 远程智能体交互的全部逻辑：
1. 发现远程 Agent（获取 Agent Card）
2. 发送非流式 / 流式翻译请求
3. 批次 B 新增：task 查询 / 取消 / 续轮 / metadata 携带

在真实场景中，客户端智能体可以同时连接多个远程 Agent，
并根据任务需求选择合适的 Agent 进行协作。
"""

import logging
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field

import httpx
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Struct, Value

from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.helpers import new_text_message
from a2a.types import AgentCard
from a2a.types.a2a_pb2 import (
    CancelTaskRequest,
    GetTaskRequest,
    ListTasksRequest,
    ListTasksResponse,
    Message,
    Part,
    Role,
    SendMessageRequest,
    StreamResponse,
    Task,
    TaskState,
)

logger = logging.getLogger(__name__)


@dataclass
class TranslateResult:
    """非流式翻译的结果包装。

    字段说明：
    - text：从响应中提取的最终文本（成功时为译文，失败/待输入时为提示文案）
    - task_id / context_id：用于后续 get_task / cancel_task / 续轮
    - final_state：终态枚举值（COMPLETED / INPUT_REQUIRED / REJECTED / CANCELED / FAILED）
    - raw_chunks：调试用，收到的所有 payload 类型序列
    """

    text: str = ""
    task_id: str = ""
    context_id: str = ""
    final_state: "TaskState.ValueType | int" = 0
    raw_chunks: list[str] = field(default_factory=list)
    # C1 新增：附带结构化输出（DataPart / FilePart）
    data: dict | None = None
    file_name: str = ""
    file_media_type: str = ""
    file_bytes: bytes = b""


class TranslatorClientAgent:
    """翻译客户端智能体。

    封装 A2A 客户端的核心功能，提供简洁的 API 供用户层调用。

    使用流程：
        1. 调用 discover() 发现远程 Agent
        2. 调用 translate() / translate_stream() / cancel_task() / get_task() / list_tasks()
    """

    def __init__(
        self,
        server_url: str = "http://127.0.0.1:9999",
        *,
        auth_token: str | None = None,
    ):
        """初始化客户端智能体。

        Args:
            server_url: A2A 远程智能体的服务地址
            auth_token: C2—所有 JSON-RPC 请求携带的 Bearer Token
                        （Agent Card 发现请求不携带，走公开端点）。
        """
        self.server_url = server_url
        self.auth_token = auth_token
        self.agent_card: AgentCard | None = None

    async def discover(self) -> AgentCard:
        """发现远程 Agent — 获取 Agent Card。"""
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
        logger.info(
            "📡 [客户端]   技能数: %d",
            len(self.agent_card.skills) if self.agent_card.skills else 0,
        )
        if self.agent_card.supported_interfaces:
            for iface in self.agent_card.supported_interfaces:
                logger.info(
                    "📡 [客户端]   接口: %s → %s",
                    iface.protocol_binding,
                    iface.url,
                )
        logger.info("📡 [客户端] =====================================")

        return self.agent_card

    # ------------------------------------------------------------------
    # 非流式
    # ------------------------------------------------------------------
    async def translate(
        self,
        text: str,
        *,
        task_id: str | None = None,
        context_id: str | None = None,
        mode: str = "normal",
        skill_id: str | None = None,
        data: dict | None = None,
    ) -> TranslateResult:
        """非流式翻译 — 发送文本并等待完整结果。

        Args:
            text: 待翻译的中文文本
            task_id：传入则属于续轮（如 input-required 后的第二次输入）
            context_id：续轮时一起传入原任务的 context_id
            mode：normal / slow（实际中 slow 建议用 translate_stream）
            skill_id：C1—指定目标 Skill（translate_batch_zh_to_en / translate_report 等）
            data：C1—附带的结构化输入（会作为 DataPart 追加到 Message.parts）
        """
        client = await self._make_client(streaming=False)
        try:
            message = self._build_user_message(
                text,
                task_id=task_id,
                context_id=context_id,
                mode=mode,
                skill_id=skill_id,
                data=data,
            )
            request = SendMessageRequest(message=message)

            target_url = self._resolve_rpc_url()
            logger.info("📡 [客户端] ========== 非流式翻译请求 ==========")
            logger.info("📡 [客户端] POST %s", target_url)
            logger.info(
                "📡 [客户端] mode=%s，skill_id=%s，task_id=%s",
                mode,
                skill_id or "(默认)",
                task_id or "(新)",
            )
            logger.info("📡 [客户端] 用户消息: \"%s\"%s", text, " + DataPart" if data is not None else "")

            result = TranslateResult()
            chunk_index = 0
            async for chunk in client.send_message(request):
                chunk_index += 1
                payload_type = chunk.WhichOneof("payload")
                result.raw_chunks.append(payload_type or "")
                logger.info(
                    "📡 [客户端] --- chunk #%d payload=%s ---",
                    chunk_index,
                    payload_type,
                )
                self._absorb_chunk_into_result(chunk, result)

            logger.info(
                "📡 [客户端] ✅ 翻译结果: \"%s\"（final_state=%s）",
                result.text,
                TaskState.Name(result.final_state) if result.final_state else "?",
            )
            logger.info("📡 [客户端] =====================================")
            return result
        finally:
            await client.close()

    # ------------------------------------------------------------------
    # 流式
    # ------------------------------------------------------------------
    async def translate_stream(
        self,
        text: str,
        *,
        task_id: str | None = None,
        context_id: str | None = None,
        mode: str = "slow",
    ) -> AsyncGenerator[StreamResponse, None]:
        """流式翻译 — 逐步接收响应 chunk。

        Args:
            mode: slow → 服务端走分段慢速翻译（可取消）；normal → 普通流式。
        """
        client = await self._make_client(streaming=True)
        try:
            message = self._build_user_message(
                text, task_id=task_id, context_id=context_id, mode=mode
            )
            request = SendMessageRequest(message=message)

            target_url = self._resolve_rpc_url()
            logger.info("📡 [客户端] ========== 流式翻译请求 ==========")
            logger.info("📡 [客户端] POST %s", target_url)
            logger.info("📡 [客户端] mode=%s，task_id=%s", mode, task_id or "(新)")
            logger.info("📡 [客户端] 用户消息: \"%s\"", text)

            chunk_index = 0
            async for chunk in client.send_message(request):
                chunk_index += 1
                payload_type = chunk.WhichOneof("payload")
                logger.info(
                    "📡 [客户端] --- 流式 chunk #%d payload=%s ---",
                    chunk_index,
                    payload_type,
                )
                yield chunk
            logger.info("📡 [客户端] ✅ 流式传输完成，共 %d 个 chunk", chunk_index)
            logger.info("📡 [客户端] =====================================")
        finally:
            await client.close()

    # ------------------------------------------------------------------
    # Task 查询 / 取消
    # ------------------------------------------------------------------
    async def get_task(self, task_id: str, *, history_length: int = 0) -> Task:
        """查询指定 Task 的最新状态。"""
        client = await self._make_client(streaming=False)
        try:
            logger.info("📡 [客户端] 🔍 tasks/get task_id=%s", task_id)
            req = GetTaskRequest(id=task_id, history_length=history_length)
            task = await client.get_task(req)
            logger.info(
                "📡 [客户端] ✅ tasks/get 返回 state=%s artifacts=%d",
                TaskState.Name(task.status.state),
                len(task.artifacts) if task.artifacts else 0,
            )
            return task
        finally:
            await client.close()

    async def list_tasks(
        self,
        *,
        context_id: str | None = None,
        page_size: int = 50,
        include_artifacts: bool = False,
    ) -> ListTasksResponse:
        """列出 Task（可按 context_id 过滤）。"""
        client = await self._make_client(streaming=False)
        try:
            kwargs: dict = {"page_size": page_size, "include_artifacts": include_artifacts}
            if context_id:
                kwargs["context_id"] = context_id
            req = ListTasksRequest(**kwargs)
            logger.info(
                "📡 [客户端] 📋 tasks/list context_id=%s page_size=%d",
                context_id or "(all)",
                page_size,
            )
            resp = await client.list_tasks(req)
            logger.info(
                "📡 [客户端] ✅ tasks/list 返回 %d 条（total=%d）",
                len(resp.tasks),
                resp.total_size,
            )
            return resp
        finally:
            await client.close()

    async def cancel_task(self, task_id: str) -> Task:
        """取消指定 Task。"""
        client = await self._make_client(streaming=False)
        try:
            logger.info("📡 [客户端] 🛑 tasks/cancel task_id=%s", task_id)
            req = CancelTaskRequest(id=task_id)
            task = await client.cancel_task(req)
            logger.info(
                "📡 [客户端] ✅ tasks/cancel 返回 state=%s",
                TaskState.Name(task.status.state),
            )
            return task
        finally:
            await client.close()

    # ------------------------------------------------------------------
    # 展示 / 辅助
    # ------------------------------------------------------------------
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

    async def _make_client(self, *, streaming: bool):
        """构造一个 A2A 客户端实例。每个高层方法自己 close ，以免串用状态。

        C2：若有 auth_token 则构造一个默认携带 Authorization 头的 httpx 客户端，
        并通过 ClientConfig.httpx_client 注入 SDK。注意该客户端由调用方负责 close。
        """
        if not self.agent_card:
            await self.discover()
        httpx_client: httpx.AsyncClient | None = None
        if self.auth_token:
            httpx_client = httpx.AsyncClient(
                headers={"Authorization": f"Bearer {self.auth_token}"},
                timeout=30.0,
            )
        config = ClientConfig(streaming=streaming, httpx_client=httpx_client)
        return await create_client(agent=self.agent_card, client_config=config)

    def _resolve_rpc_url(self) -> str:
        """解析实际的 JSON-RPC 请求 URL。"""
        if self.agent_card and self.agent_card.supported_interfaces:
            return self.agent_card.supported_interfaces[0].url
        return self.server_url

    @staticmethod
    def _build_user_message(
        text: str,
        *,
        task_id: str | None,
        context_id: str | None,
        mode: str,
        skill_id: str | None = None,
        data: dict | None = None,
    ) -> Message:
        """构造用户 Message。

        - 普通文本输入：用 new_text_message
        - C1：data 不为空时添加一个 DataPart（application/json）
        - metadata 支持 mode 与 skill_id
        """
        message = (
            new_text_message(text, role=Role.ROLE_USER)
            if text
            else Message(role=Role.ROLE_USER, message_id=str(uuid.uuid4()))
        )
        if data is not None:
            data_value = Value()
            ParseDict(data, data_value)
            message.parts.append(Part(data=data_value, media_type="application/json"))
        if task_id:
            message.task_id = task_id
        if context_id:
            message.context_id = context_id
        md_payload: dict = {}
        if mode and mode != "normal":
            md_payload["mode"] = mode
        if skill_id:
            md_payload["skill_id"] = skill_id
        if md_payload:
            md = Struct()
            md.update(md_payload)
            message.metadata.CopyFrom(md)
        return message

    @staticmethod
    def _absorb_chunk_into_result(response, result: TranslateResult) -> None:
        """将响应 chunk 的关键信息吸纳进 TranslateResult。"""
        payload_type = response.WhichOneof("payload")

        if payload_type == "task":
            task = response.task
            if task.id:
                result.task_id = task.id
            if task.context_id:
                result.context_id = task.context_id
            if task.status and task.status.state:
                result.final_state = task.status.state
            # 优先从 artifacts 取译文（文本 / Data / File）
            if task.artifacts:
                for artifact in task.artifacts:
                    for part in artifact.parts:
                        TranslatorClientAgent._absorb_part(part, result)
                if result.text or result.data is not None or result.file_bytes:
                    return
            # 其次从 status.message 取提示文案（requires_input / reject 时重要）
            if task.status and task.status.message:
                for part in task.status.message.parts:
                    if part.HasField("text"):
                        result.text = part.text
                        return

        elif payload_type == "message":
            for part in response.message.parts:
                TranslatorClientAgent._absorb_part(part, result)
                if result.text:
                    return

        elif payload_type == "artifact_update":
            for part in response.artifact_update.artifact.parts:
                TranslatorClientAgent._absorb_part(part, result)
                if result.text or result.data is not None or result.file_bytes:
                    return

        elif payload_type == "status_update":
            status = response.status_update.status
            if status and status.state:
                result.final_state = status.state
            if status and status.message:
                for part in status.message.parts:
                    if part.HasField("text"):
                        result.text = part.text
                        return

    @staticmethod
    def _absorb_part(part: Part, result: TranslateResult) -> None:
        """从单个 Part 中提取 text / data / file 到 TranslateResult。"""
        if part.HasField("text"):
            result.text = part.text
            return
        if part.HasField("data"):
            try:
                result.data = MessageToDict(part.data)
            except Exception:
                result.data = None
            return
        # FilePart（raw 字节）
        if part.HasField("raw"):
            result.file_bytes = part.raw
            result.file_name = part.filename or ""
            result.file_media_type = part.media_type or ""

