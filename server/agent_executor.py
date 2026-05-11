"""
翻译 Agent 执行器 - A2A 协议的核心桥梁

AgentExecutor 是 A2A SDK 的核心接口，它连接了：
- A2A 协议层（接收请求、发送事件）
- 业务逻辑层（TranslatorAgent）

它负责：
1. 从 RequestContext 中提取用户消息
2. 调用 TranslatorAgent 执行翻译
3. 通过 EventQueue 发送 Task 生命周期事件
"""

import logging

from server.agent import TranslatorAgent

from a2a.helpers import (
    new_task_from_user_message,
    new_text_artifact,
    new_text_message,
)
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types.a2a_pb2 import (
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)

logger = logging.getLogger(__name__)


class TranslatorAgentExecutor(AgentExecutor):
    """翻译 Agent 执行器。

    实现 A2A SDK 的 AgentExecutor 接口，处理来自客户端的翻译请求。
    完整展示了 Task 的生命周期：创建 → WORKING → 产出 Artifact → COMPLETED
    """

    def __init__(self) -> None:
        self.agent = TranslatorAgent()

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """执行翻译任务。

        完整的 Task 生命周期：
        1. 创建或获取 Task
        2. 更新状态为 WORKING（处理中）
        3. 从用户消息中提取文本
        4. 调用 TranslatorAgent 进行翻译
        5. 发送翻译结果（Artifact）
        6. 更新状态为 COMPLETED（已完成）
        """
        # 日志：打印收到的请求上下文详情
        logger.info("🟢 [执行器] ========== AgentExecutor.execute() 被调用 ==========")
        logger.info("🟢 [执行器] task_id: %s", context.task_id)
        logger.info("🟢 [执行器] context_id: %s", context.context_id)
        logger.info("🟢 [执行器] 是否已有 Task: %s", "是" if context.current_task else "否（将创建新 Task）")
        if context.message:
            logger.info("🟢 [执行器] 收到的 Message:")
            logger.info("🟢 [执行器]   role: %s", context.message.role)
            for idx, part in enumerate(context.message.parts):
                if part.HasField("text"):
                    logger.info("🟢 [执行器]   parts[%d].text: \"%s\"", idx, part.text)
                else:
                    logger.info("🟢 [执行器]   parts[%d]: (非文本类型)", idx)

        # Step 1: 创建或获取任务
        task = context.current_task or new_task_from_user_message(
            context.message
        )
        logger.info("🟢 [执行器] Step 1: Task 已创建/获取, id=%s", task.id)
        await event_queue.enqueue_event(task)

        try:
            # Step 2: 更新任务状态为 WORKING
            logger.info("🟢 [执行器] Step 2: 发送状态更新 → WORKING")
            await event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    task_id=context.task_id,
                    context_id=context.context_id,
                    status=TaskStatus(
                        state=TaskState.TASK_STATE_WORKING,
                        message=new_text_message(
                            "正在翻译中，请稍候..."
                        ),
                    ),
                )
            )

            # Step 3: 从用户消息中提取待翻译文本
            user_text = ""
            if context.message and context.message.parts:
                for part in context.message.parts:
                    if part.HasField("text"):
                        user_text = part.text
                        break

            if not user_text:
                logger.warning(
                    "🟢 [执行器] ⚠️ 消息中无文本内容，使用默认值: '你好世界'"
                )
                user_text = "你好世界"  # 默认文本

            logger.info("🟢 [执行器] Step 3: 提取到用户文本: \"%s\"", user_text)

            # Step 4: 调用 Agent 执行翻译
            logger.info("🟢 [执行器] Step 4: 调用 TranslatorAgent.invoke(\"%s\")", user_text)
            result = await self.agent.invoke(user_text)
            logger.info("🟢 [执行器] Step 4: 翻译结果: \"%s\" → \"%s\"", user_text, result)

            # Step 5: 发送翻译结果 Artifact
            logger.info("🟢 [执行器] Step 5: 发送 Artifact (name=translation_result, text=\"%s\")", result)
            await event_queue.enqueue_event(
                TaskArtifactUpdateEvent(
                    task_id=context.task_id,
                    context_id=context.context_id,
                    artifact=new_text_artifact(
                        name="translation_result",
                        text=result,
                    ),
                )
            )

            # Step 6: 更新任务状态为 COMPLETED
            logger.info("🟢 [执行器] Step 6: 发送状态更新 → COMPLETED")
            await event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    task_id=context.task_id,
                    context_id=context.context_id,
                    status=TaskStatus(
                        state=TaskState.TASK_STATE_COMPLETED,
                        message=new_text_message(
                            f"翻译完成: {user_text} → {result}"
                        ),
                    ),
                )
            )
            logger.info("🟢 [执行器] ✅ 任务执行完成")
            logger.info("🟢 [执行器] =============================================")
        except Exception as error:
            logger.exception("🟢 [执行器] ❌ 任务执行失败: %s", error)
            await event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    task_id=context.task_id,
                    context_id=context.context_id,
                    status=TaskStatus(
                        state=TaskState.TASK_STATE_FAILED,
                        message=new_text_message(
                            f"翻译失败: {error}"
                        ),
                    ),
                )
            )
            logger.info("🟢 [执行器] =============================================")


    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        """取消任务（本 Demo 不支持取消）。"""
        raise NotImplementedError("cancel is not supported by this agent")
