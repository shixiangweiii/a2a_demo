"""
翻译 Agent 执行器 - A2A 协议的核心桥梁

AgentExecutor 是 A2A SDK 的核心接口，它连接了：
- A2A 协议层（接收请求、发送事件）
- 业务逻辑层（TranslatorAgent）

它负责：
1. 从 RequestContext 中提取用户消息
2. 调用 TranslatorAgent 执行翻译
3. 通过 EventQueue 发送 Task 生命周期事件（借助 SDK 原生 TaskUpdater）

===== TaskUpdater — 统一的生命周期事件出口 =====
SDK 提供的 TaskUpdater 封装了标准动作：
    submit / start_work / requires_input / requires_auth /
    reject / cancel / complete / failed / add_artifact / update_status
自动带上时间戳、终态锁等保护，替代手写 TaskStatusUpdateEvent。

===== 批次 B 扩展：Task 生命周期进阶 =====
1. input-required：输入缺信息时下发 requires_input，等用户用同一 task_id 续轮。
2. reject：输入不合法（非中文）直接 reject。
3. cancel：慢速翻译中，客户端发 tasks/cancel → self.cancel() 回调会
   ① set asyncio.Event 让循环尽快退出，② 自行下发 CANCELED 终态。
"""

import asyncio
import logging

from server.agent import TranslatorAgent

from a2a.helpers import new_task_from_user_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types.a2a_pb2 import Part, TaskState
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Value

logger = logging.getLogger(__name__)


class TranslatorAgentExecutor(AgentExecutor):
    """翻译 Agent 执行器。

    实现 A2A SDK 的 AgentExecutor 接口，处理来自客户端的翻译请求。
    完整展示了 Task 的生命周期以及进阶的 input-required / reject / cancel。
    """

    def __init__(self) -> None:
        self.agent = TranslatorAgent()
        # task_id → cancel_event（供慢速循环探测 Cancel）
        self._cancel_events: dict[str, asyncio.Event] = {}

    # ------------------------------------------------------------------
    # execute
    # ------------------------------------------------------------------
    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """执行翻译任务。

        主干：
        1. 创建/复用 Task（续轮时 context.current_task 不为空）
        2. 取出用户文本 + metadata.mode（normal / slow）
        3. 输入仲裁：empty / ambiguous → requires_input；not_chinese → reject
        4. 用 TaskUpdater 逐步推进状态与 Artifact
        """
        self._log_incoming(context)

        # Step 1: 创建或获取任务
        task = context.current_task or new_task_from_user_message(
            context.message
        )
        is_followup = context.current_task is not None
        logger.info(
            "🟢 [执行器] Step 1: Task id=%s，%s",
            task.id,
            "续轮（已有 Task）" if is_followup else "首轮（新建 Task）",
        )
        if not is_followup:
            # 首轮需要把 Task 初始快照入队，让 result_aggregator 知道 Task 已存在；
            # 续轮时 SDK 已经从 TaskStore 恢复了 current_task，不能再 enqueue，
            # 否则 result_aggregator 会把旧快照（state=INPUT_REQUIRED）当作响应返回。
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(
            event_queue=event_queue,
            task_id=task.id,
            context_id=task.context_id,
        )

        # Step 2: 解析用户输入与模式
        user_text = self._extract_user_text(context)
        mode = self._extract_mode(context)
        logger.info(
            "🟢 [执行器] Step 2: user_text=\"%s\"，mode=%s",
            user_text,
            mode,
        )

        try:
            # Step 3：按 skill_id 分流。批量 / 报告 种输入形态差异大，跳过中文校验。
            skill_id = self._extract_skill_id(context)
            if skill_id == "translate_batch_zh_to_en":
                await self._run_batch(updater, context)
                return
            if skill_id == "translate_report":
                await self._run_report(updater, user_text)
                return

            # Step 4：默认翻译技能（文本输入）的仲裁
            verdict = self.agent.classify_input(user_text)
            if not verdict.get("ok"):
                await self._handle_invalid_input(updater, verdict)
                return

            # Step 5: 慢速 / 正常 两条分支
            if mode == "slow":
                await self._run_slow(updater, user_text, task.id)
            else:
                await self._run_normal(updater, user_text)
        except asyncio.CancelledError:
            # handler 在 cancel() 回调后会 cancel 本协程。
            # CANCELED 终态已由 cancel() 下发，这里不再写入。
            logger.info("🟢 [执行器] ℹ️  execute 协程被取消（task_id=%s）", task.id)
            raise
        except Exception as error:
            logger.exception("🟢 [执行器] ❌ 任务执行失败: %s", error)
            try:
                await updater.failed(
                    message=updater.new_agent_message(
                        parts=[Part(text=f"翻译失败: {error}")]
                    )
                )
            except RuntimeError:
                # 若已经写入过终态（如 cancel 竞争），忽略。
                pass
        finally:
            self._cancel_events.pop(task.id, None)
            logger.info("🟢 [执行器] =============================================")

    # ------------------------------------------------------------------
    # cancel
    # ------------------------------------------------------------------
    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        """处理 tasks/cancel 请求。

        SDK 的 DefaultRequestHandler 会先调用本方法，然后 cancel
        背后的 execute 协程（会抛 CancelledError）。所以本方法需要
        自己下发 CANCELED 终态，否则 handler 的 result_aggregator
        会因未见到 CANCELED 而报错。
        """
        logger.info("🟢 [执行器] 🛑 收到 cancel，task_id=%s", context.task_id)

        # 通知慢速循环尽快退出
        ev = self._cancel_events.get(context.task_id)
        if ev is not None:
            ev.set()

        # 下发 CANCELED 终态事件（给 result_aggregator 消费）
        updater = TaskUpdater(
            event_queue=event_queue,
            task_id=context.task_id,
            context_id=context.context_id,
        )
        try:
            await updater.cancel(
                message=updater.new_agent_message(
                    parts=[Part(text="任务已被取消")]
                )
            )
        except RuntimeError:
            # 竞争情况：execute 已提前写入终态
            logger.warning("🟢 [执行器] ⚠️  CANCELED 下发失败（任务可能已终结）")

    # ------------------------------------------------------------------
    # 内部分支
    # ------------------------------------------------------------------
    async def _run_normal(self, updater: TaskUpdater, user_text: str) -> None:
        """正常翻译路径（阶段 2/3 复用）。"""
        logger.info("🟢 [执行器] [正常] TaskUpdater.start_work() → WORKING")
        await updater.start_work(
            message=updater.new_agent_message(
                parts=[Part(text="正在翻译中，请稍候...")],
            )
        )

        result = await self.agent.invoke(user_text)
        logger.info("🟢 [执行器] [正常] 翻译结果: \"%s\" → \"%s\"", user_text, result)

        await updater.add_artifact(
            parts=[Part(text=result)],
            name="translation_result",
        )
        await updater.complete(
            message=updater.new_agent_message(
                parts=[Part(text=f"翻译完成: {user_text} → {result}")]
            )
        )
        logger.info("🟢 [执行器] [正常] ✅ COMPLETED")

    async def _run_slow(
        self, updater: TaskUpdater, user_text: str, task_id: str
    ) -> None:
        """慢速翻译路径（服务于阶段 5 Cancel 演示）。"""
        logger.info("🟢 [执行器] [慢速] TaskUpdater.start_work() → WORKING")
        await updater.start_work(
            message=updater.new_agent_message(
                parts=[Part(text="启动慢速翻译（分段输出，可随时 cancel）...")],
            )
        )

        cancel_event = asyncio.Event()
        self._cancel_events[task_id] = cancel_event

        async for idx, total, accumulated in self.agent.slow_translate(
            user_text, cancel_event=cancel_event
        ):
            if cancel_event.is_set():
                logger.info("🟢 [执行器] [慢速] 🛑 检测到 cancel，尽快退出循环")
                return  # 终态由 cancel() 回调写入
            logger.info(
                "🟢 [执行器] [慢速] 下发分段 %d/%d: \"%s\"",
                idx,
                total,
                accumulated,
            )
            await updater.add_artifact(
                parts=[Part(text=accumulated)],
                name="translation_partial",
                metadata={"segment": idx, "total": total},
                append=idx > 1,
                last_chunk=(idx == total),
            )

        if cancel_event.is_set():
            # 循环正常结束后再检一次，防止最后一次 yield 后才收到 cancel
            return

        await updater.complete(
            message=updater.new_agent_message(
                parts=[Part(text=f"慢速翻译完成：{user_text}")]
            )
        )
        logger.info("🟢 [执行器] [慢速] ✅ COMPLETED")

    # ------------------------------------------------------------------
    # C1 新增分支：批量翻译（DataPart）/ 翻译报告（FilePart）
    # ------------------------------------------------------------------
    async def _run_batch(
        self, updater: TaskUpdater, context: RequestContext
    ) -> None:
        """批量翻译：从输入 DataPart 读 items → 输出结果 DataPart。"""
        logger.info("🟢 [执行器] [批量] TaskUpdater.start_work() → WORKING")
        await updater.start_work(
            message=updater.new_agent_message(
                parts=[Part(text="批量翻译中...")],
            )
        )

        items = self._extract_batch_items(context)
        if not items:
            logger.info("🟢 [执行器] [批量] ✕ 输入缺失 items，reject")
            await updater.reject(
                message=updater.new_agent_message(
                    parts=[Part(text="批量翻译需要 DataPart 中包含 items 数组。")]
                )
            )
            return

        results = await self.agent.translate_batch(items)
        logger.info("🟢 [执行器] [批量] 翻译完成 %d 项", len(results))

        data_value = Value()
        ParseDict({"count": len(results), "results": results}, data_value)
        await updater.add_artifact(
            parts=[Part(data=data_value, media_type="application/json")],
            name="translation_batch_result",
        )
        await updater.complete(
            message=updater.new_agent_message(
                parts=[Part(text=f"批量翻译完成，共 {len(results)} 条。")]
            )
        )
        logger.info("🟢 [执行器] [批量] ✅ COMPLETED")

    async def _run_report(self, updater: TaskUpdater, user_text: str) -> None:
        """翻译报告：输入中文 → 输出 FilePart（text/plain）。"""
        logger.info("🟢 [执行器] [报告] TaskUpdater.start_work() → WORKING")
        await updater.start_work(
            message=updater.new_agent_message(
                parts=[Part(text="生成翻译报告中...")],
            )
        )

        verdict = self.agent.classify_input(user_text)
        if not verdict.get("ok"):
            await self._handle_invalid_input(updater, verdict)
            return

        filename, media_type, content = await self.agent.build_translation_report(
            user_text
        )
        logger.info(
            "🟢 [执行器] [报告] 翻译报告生成：filename=%s, %d bytes",
            filename,
            len(content.encode("utf-8")),
        )
        await updater.add_artifact(
            parts=[
                Part(
                    raw=content.encode("utf-8"),
                    filename=filename,
                    media_type=media_type,
                )
            ],
            name="translation_report_file",
        )
        await updater.complete(
            message=updater.new_agent_message(
                parts=[Part(text=f"翻译报告已生成：{filename}")]
            )
        )
        logger.info("🟢 [执行器] [报告] ✅ COMPLETED")

    @staticmethod
    def _extract_batch_items(context: RequestContext) -> list[str]:
        """从输入 Message 的第一个 DataPart 中读取 items 数组。"""
        msg = context.message
        if not msg or not msg.parts:
            return []
        for part in msg.parts:
            if part.HasField("data"):
                try:
                    payload = MessageToDict(part.data)
                except Exception:
                    payload = {}
                if isinstance(payload, dict):
                    items = payload.get("items")
                    if isinstance(items, list):
                        return [str(x) for x in items]
                return []
        return []

    async def _handle_invalid_input(
        self,
        updater: TaskUpdater,
        verdict: dict,
    ) -> None:
        """处理不合格输入：empty/ambiguous → requires_input；not_chinese → reject。"""
        reason = verdict.get("reason", "")
        hint = verdict.get("hint", "输入不合法")
        if reason == "not_chinese":
            logger.info("🟢 [执行器] ✘ reject（not_chinese）: %s", hint)
            await updater.reject(
                message=updater.new_agent_message(
                    parts=[Part(text=f"拒绝接受任务：{hint}")]
                )
            )
            return
        # empty / ambiguous 都归为 requires_input
        logger.info("🟢 [执行器] ✍ input-required（%s）: %s", reason, hint)
        await updater.requires_input(
            message=updater.new_agent_message(
                parts=[Part(text=hint)]
            )
        )

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_user_text(context: RequestContext) -> str:
        """从 RequestContext.message.parts 中抽取第一个 text Part 的文本。"""
        if not context.message or not context.message.parts:
            return ""
        for part in context.message.parts:
            if part.HasField("text"):
                return part.text
        return ""

    @staticmethod
    def _extract_skill_id(context: RequestContext) -> str:
        """从 Message.metadata 中取 skill_id 字段（默认空，即默认翻译技能）。"""
        msg = context.message
        if not msg:
            return ""
        try:
            v = msg.metadata.fields.get("skill_id")
        except Exception:
            return ""
        if v is None:
            return ""
        if v.HasField("string_value"):
            return v.string_value or ""
        return ""

    @staticmethod
    def _extract_mode(context: RequestContext) -> str:
        """从 Message.metadata 中取 mode 字段（默认 normal）。支持取值：normal / slow。

        Message.metadata 是 google.protobuf.Struct，值通过 .fields[key].string_value 访问。
        """
        msg = context.message
        if not msg:
            return "normal"
        try:
            mode_val = msg.metadata.fields.get("mode")
        except Exception:
            return "normal"
        if mode_val is None:
            return "normal"
        # 优先 string_value
        if mode_val.HasField("string_value"):
            return mode_val.string_value or "normal"
        return "normal"

    @staticmethod
    def _log_incoming(context: RequestContext) -> None:
        logger.info("🟢 [执行器] ========== AgentExecutor.execute() 被调用 ==========")
        logger.info("🟢 [执行器] task_id: %s", context.task_id)
        logger.info("🟢 [执行器] context_id: %s", context.context_id)
        logger.info(
            "🟢 [执行器] 是否已有 Task: %s",
            "是" if context.current_task else "否（将创建新 Task）",
        )
        if context.current_task:
            logger.info(
                "🟢 [执行器] 续轮任务原状态: %s",
                TaskState.Name(context.current_task.status.state),
            )
        if context.message:
            logger.info("🟢 [执行器] 收到的 Message:")
            logger.info("🟢 [执行器]   role: %s", context.message.role)
            for idx, part in enumerate(context.message.parts):
                if part.HasField("text"):
                    logger.info("🟢 [执行器]   parts[%d].text: \"%s\"", idx, part.text)
                else:
                    logger.info("🟢 [执行器]   parts[%d]: (非文本类型)", idx)