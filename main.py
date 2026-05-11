"""
A2A 教程 Demo — 用户交互入口

本脚本模拟完整的 A2A 协议闭环交互流程，包含三个角色：
  1. 用户（User）        — 发起翻译请求
  2. 客户端智能体（Client Agent） — 发现远程 Agent、转发请求
  3. 远程智能体（Remote Agent）   — 执行翻译并返回结果

Demo 覆盖的 A2A 能力：
  阶段 1  Agent 发现
  阶段 2  非流式翻译
  阶段 3  流式翻译
  阶段 4  input-required 多轮（Task 续轮）
  阶段 5  Cancel（流式慢速翻译中途取消）
  阶段 6  Reject（非法输入直接拒绝）
  阶段 7  tasks/get + tasks/list（任务查询）
  阶段 8  多样性 Part：批量翻译（DataPart）+ 翻译报告（FilePart）
  阶段 9  Bearer 鉴权（security_schemes + 错误 token 演示）

运行前请确保 A2A 服务器已启动：
    python -m server

然后运行本脚本：
    python main.py
"""

import asyncio
import logging

from a2a.types.a2a_pb2 import TaskState
from client.client_agent import TranslatorClientAgent


# 默认 Bearer Token（与 server/__main__.py 的 VALID_BEARER_TOKENS 一致）
DEFAULT_AUTH_TOKEN = "demo-secret-token"


def print_banner(title: str):
    """打印带边框的标题。"""
    print()
    print("=" * 60)
    print(f"  {title}")
    print("=" * 60)


def print_role(role: str, message: str):
    """打印带角色标识的消息。"""
    role_icons = {
        "用户": "👤 [用户]",
        "客户端": "🤖 [客户端智能体]",
        "服务器": "🌐 [远程智能体]",
        "系统": "⚙️  [系统]",
    }
    icon = role_icons.get(role, f"[{role}]")
    print(f"  {icon} {message}")


def _state_name(state_value) -> str:
    """将 TaskState 枚举值转为可读名称。"""
    try:
        return TaskState.Name(state_value)
    except Exception:
        return str(state_value)


async def stage_discovery(client_agent: TranslatorClientAgent):
    """阶段 1：Agent 发现。"""
    print_banner("阶段 1：Agent 发现 (Discovery)")
    print_role("系统", "A2A 协议的第一步是发现远程 Agent")
    print_role("客户端", f"请求地址: {client_agent.server_url}/.well-known/agent-card.json")
    print()

    agent_card = await client_agent.discover()
    print_role("客户端", "成功获取 Agent Card！远程 Agent 信息如下：")
    print("-" * 50)
    client_agent.display_agent_info()
    print("-" * 50)
    return agent_card


async def stage_non_streaming(client_agent: TranslatorClientAgent):
    """阶段 2：非流式翻译。"""
    print_banner("阶段 2：非流式翻译请求 (Non-Streaming)")
    print_role("系统", "用户发起翻译请求，客户端转发给远程 Agent，等待完整结果返回")
    print()

    for text in ["你好", "人工智能", "今天天气怎么样"]:
        print_role("用户", f'请翻译: "{text}"')
        print_role("客户端", "正在将请求转发给远程 Agent...")
        try:
            r = await client_agent.translate(text)
            print_role(
                "服务器",
                f'翻译结果: "{r.text}"（state={_state_name(r.final_state)}）',
            )
        except Exception as e:
            print_role("服务器", f"翻译出错: {e}")
        print()


async def stage_streaming(client_agent: TranslatorClientAgent):
    """阶段 3：流式翻译（基础版，保留原有体验）。"""
    print_banner("阶段 3：流式翻译请求 (Streaming)")
    print_role("系统", "用户发起流式翻译请求，结果逐步返回（类似 LLM 流式输出）")
    print()

    stream_text = "我是一个AI助手"
    print_role("用户", f'请翻译（流式）: "{stream_text}"')
    print_role("客户端", "正在以流式方式接收翻译结果...")
    print()
    print("  收到的流式响应 chunks:")

    chunk_count = 0
    async for chunk in client_agent.translate_stream(stream_text, mode="normal"):
        chunk_count += 1
        payload_type = chunk.WhichOneof("payload")
        if payload_type == "task":
            print(f"    chunk #{chunk_count} [Task 创建]     → SUBMITTED")
        elif payload_type == "status_update":
            state = chunk.status_update.status.state
            print(f"    chunk #{chunk_count} [状态更新]     → {_state_name(state)}")
        elif payload_type == "artifact_update":
            artifact_text = ""
            for part in chunk.artifact_update.artifact.parts:
                if part.HasField("text"):
                    artifact_text = part.text
            print(f"    chunk #{chunk_count} [产出物到达]   → \"{artifact_text}\"")
        else:
            print(f"    chunk #{chunk_count} [{payload_type}]")

    print()
    print_role("客户端", f"流式传输完成，共收到 {chunk_count} 个 chunk")


async def stage_input_required(client_agent: TranslatorClientAgent):
    """阶段 4：input-required 多轮续轮。

    演示：首轮发送模糊指令 "翻译" → Agent 返回 INPUT_REQUIRED
    → 用户用同一 task_id 发送真实中文 → Agent 完成翻译。
    """
    print_banner("阶段 4：input-required 多轮续轮")
    print_role("系统", "演示 Task 生命周期进阶：输入缺失 → requires_input → 用户续轮 → COMPLETED")
    print()

    # 首轮：模糊指令
    print_role("用户", '第一轮: "翻译"（模糊指令，缺少内容）')
    first = await client_agent.translate("翻译")
    print_role(
        "服务器",
        f"final_state={_state_name(first.final_state)}，提示: \"{first.text}\"",
    )
    if first.final_state != TaskState.TASK_STATE_INPUT_REQUIRED:
        print_role("系统", "⚠️ 未进入 INPUT_REQUIRED，终止本阶段演示")
        return
    print_role("系统", f"🎯 Task 停留在 INPUT_REQUIRED（task_id={first.task_id[:12]}...）")
    print()

    # 续轮：补全内容
    follow_text = "机器学习"
    print_role("用户", f'第二轮（续轮）: "{follow_text}" → 使用同一 task_id')
    second = await client_agent.translate(
        follow_text, task_id=first.task_id, context_id=first.context_id
    )
    print_role(
        "服务器",
        f'final_state={_state_name(second.final_state)}，翻译结果: "{second.text}"',
    )
    print()
    print_role("系统", "✅ 续轮完成：同一 Task 从 INPUT_REQUIRED → WORKING → COMPLETED")


async def stage_cancel(client_agent: TranslatorClientAgent):
    """阶段 5：Cancel 流程。

    演示：启动慢速流式翻译 → 客户端在第 2 段后发 cancel_task
    → 服务端写 CANCELED 终态，客户端验证。
    """
    print_banner("阶段 5：Cancel（流式慢速翻译中途取消）")
    print_role("系统", "演示 tasks/cancel：慢速翻译中途客户端主动取消")
    print()

    slow_text = "科技与艺术的完美结合"
    print_role("用户", f'发起慢速流式翻译: "{slow_text}"（mode=slow，服务端分段输出）')
    print()

    seen_task_id: str | None = None
    received = 0
    cancelled_in_flight = False
    print("  收到的流式响应 chunks:")
    try:
        async for chunk in client_agent.translate_stream(slow_text, mode="slow"):
            received += 1
            payload_type = chunk.WhichOneof("payload")
            if payload_type == "task":
                seen_task_id = chunk.task.id
                print(f"    chunk #{received} [Task 创建]     → task_id={seen_task_id[:12]}... SUBMITTED")
            elif payload_type == "status_update":
                state = chunk.status_update.status.state
                print(f"    chunk #{received} [状态更新]     → {_state_name(state)}")
            elif payload_type == "artifact_update":
                seg = chunk.artifact_update
                partial = ""
                for part in seg.artifact.parts:
                    if part.HasField("text"):
                        partial = part.text
                # 显示段号/总段
                seg_info = ""
                if seg.artifact.metadata:
                    fields = seg.artifact.metadata.fields
                    if "segment" in fields and "total" in fields:
                        seg_info = f" [{int(fields['segment'].number_value)}/{int(fields['total'].number_value)}]"
                print(f"    chunk #{received} [产出物到达]{seg_info} → \"{partial}\"")

                # 在第 2 段后发起 cancel
                if not cancelled_in_flight and seen_task_id and received >= 3:
                    print()
                    print_role("客户端", f"🛑 已收到 2 段，发起 cancel_task(task_id={seen_task_id[:12]}...)")
                    try:
                        cancelled_task = await client_agent.cancel_task(seen_task_id)
                        print_role(
                            "服务器",
                            f"cancel_task 响应 final_state={_state_name(cancelled_task.status.state)}",
                        )
                    except Exception as e:
                        print_role("服务器", f"cancel_task 出错: {e}")
                    cancelled_in_flight = True
                    print()
            else:
                print(f"    chunk #{received} [{payload_type}]")
    except Exception as e:
        print(f"    流式请求中断: {e}")

    print()
    if seen_task_id:
        # 再查一次任务的最终状态
        final_task = await client_agent.get_task(seen_task_id)
        print_role(
            "系统",
            f"✅ 最终 task state={_state_name(final_task.status.state)}（期望 TASK_STATE_CANCELED）",
        )


async def stage_reject(client_agent: TranslatorClientAgent):
    """阶段 6：Reject 流程。

    演示：发送非中文输入 → Agent 直接 reject。
    """
    print_banner("阶段 6：Reject（非法输入直接拒绝）")
    print_role("系统", "演示越权/不合法输入：Agent 直接 reject Task")
    print()

    bad_text = "Hello world, translate me!"
    print_role("用户", f'发送英文输入: "{bad_text}"（本 Agent 仅支持中→英）')
    r = await client_agent.translate(bad_text)
    print_role(
        "服务器",
        f"final_state={_state_name(r.final_state)}，拒绝理由: \"{r.text}\"",
    )
    print()
    if r.final_state == TaskState.TASK_STATE_REJECTED:
        print_role("系统", "✅ Task 已被 reject（终态 REJECTED）")
    else:
        print_role("系统", f"⚠️ 期望 REJECTED，实际 {_state_name(r.final_state)}")


async def stage_task_query(client_agent: TranslatorClientAgent):
    """阶段 7：tasks/get + tasks/list 查询。"""
    print_banner("阶段 7：Task 查询（tasks/get + tasks/list）")
    print_role("系统", "演示客户端通过 tasks/get 和 tasks/list 查询任务快照")
    print()

    # 先新建一个 Task 以便查询
    r = await client_agent.translate("早上好")
    print_role(
        "客户端",
        f"新创建 Task task_id={r.task_id[:12]}... state={_state_name(r.final_state)}",
    )
    print()

    # get_task
    print_role("客户端", f"发起 tasks/get(task_id={r.task_id[:12]}...)")
    t = await client_agent.get_task(r.task_id, history_length=5)
    print_role(
        "服务器",
        f"返回 task state={_state_name(t.status.state)}，artifacts={len(t.artifacts)}，history={len(t.history)}",
    )
    print()

    # list_tasks
    print_role("客户端", "发起 tasks/list（列出所有任务）")
    resp = await client_agent.list_tasks(page_size=20)
    print_role("服务器", f"共 {len(resp.tasks)} 个 Task（total_size={resp.total_size}）：")
    for idx, task in enumerate(resp.tasks, start=1):
        print(f"    {idx}. id={task.id[:12]}... state={_state_name(task.status.state)}")


async def stage_multi_part(client_agent: TranslatorClientAgent):
    """阶段 8：多样性 Part — 批量翻译（DataPart）+ 翻译报告（FilePart）。"""
    print_banner("阶段 8：多样性 Part（DataPart / FilePart）")
    print_role("系统", "演示 A2A 所支持的结构化 Part：DataPart与FilePart，不再只是 text")
    print()

    # ---- 8a：批量翻译（DataPart in → DataPart out） ----
    items = ["你好", "早上好", "人工智能", "机器学习"]
    print_role("用户", f"批量翻译请求（DataPart）：items={items}")
    print_role("客户端", "呼叫 skill=translate_batch_zh_to_en，Message.parts 携带 DataPart")
    r = await client_agent.translate(
        "",
        skill_id="translate_batch_zh_to_en",
        data={"items": items},
    )
    print_role("服务器", f"final_state={_state_name(r.final_state)}")
    if r.data and isinstance(r.data.get("results"), list):
        print_role("服务器", f"返回 DataPart：count={int(r.data.get('count', 0))}，明细：")
        for row in r.data["results"]:
            print(f"    - \"{row.get('source')}\" → \"{row.get('target')}\" (hit={row.get('hit')})")
    else:
        print_role("服务器", "未返回预期的 DataPart 结果。")
    print()

    # ---- 8b：翻译报告（text in → FilePart out） ----
    report_src = "人工智能"
    print_role("用户", f'翻译报告请求："{report_src}"')
    print_role("客户端", "呼叫 skill=translate_report，预期返回 FilePart")
    r2 = await client_agent.translate(report_src, skill_id="translate_report")
    print_role("服务器", f"final_state={_state_name(r2.final_state)}")
    if r2.file_bytes:
        print_role(
            "服务器",
            f"返回 FilePart：filename={r2.file_name}，media_type={r2.file_media_type}，size={len(r2.file_bytes)} bytes",
        )
        preview = r2.file_bytes.decode("utf-8", errors="replace")
        print("  ── 文件内容预览 ──")
        for line in preview.splitlines():
            print(f"    {line}")
    else:
        print_role("服务器", "未返回预期的 FilePart。")


async def stage_auth(client_agent: TranslatorClientAgent):
    """阶段 9：Bearer 鉴权 — 对比正确 token 与包含错误 token 两种场景。"""
    print_banner("阶段 9：Bearer 鉴权（security_schemes）")
    print_role(
        "系统",
        "演示 A2A Agent Card 中的 security_schemes，以及服务器端 BearerAuthMiddleware",
    )
    print()

    # 9a：从 Agent Card 中读取 security_schemes
    card = client_agent.agent_card
    if card and getattr(card, "security_schemes", None):
        print_role("客户端", "Agent Card 声明的 security_schemes：")
        # security_schemes 是 proto map，可迭代
        for scheme_id, scheme in card.security_schemes.items():
            http_auth = scheme.http_auth_security_scheme
            print(
                f"    - {scheme_id}: scheme={http_auth.scheme!r} "
                f"bearer_format={http_auth.bearer_format!r} desc={http_auth.description!r}"
            )
    else:
        print_role("客户端", "⚠️ Agent Card 未声明 security_schemes")
    print()

    # 9b：错误 token
    print_role("用户", "使用错误 token 发送翻译请求，期望被服务端拒绝")
    bad_agent = TranslatorClientAgent(
        server_url=client_agent.server_url, auth_token="invalid-token"
    )
    # 复用已发现的 card，跳过重复发现
    bad_agent.agent_card = card
    try:
        await bad_agent.translate("你好")
    except Exception as e:
        print_role("服务器", f"⚠️ 请求被拒绝：{type(e).__name__}: {e}")
    print()

    # 9c：正确 token
    print_role("用户", "使用正确 token 再次发送，期望正常翻译")
    try:
        r = await client_agent.translate("你好")
        print_role(
            "服务器",
            f'✅ 正常返回：final_state={_state_name(r.final_state)} "{r.text}"',
        )
    except Exception as e:
        print_role("服务器", f"❌ 意外失败：{type(e).__name__}: {e}")


async def main():
    """运行 A2A 教程 Demo 的完整闭环流程。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    print_banner("A2A (Agent2Agent) 协议教程 Demo")
    print("  本 Demo 演示 A2A 协议中三个核心角色的交互流程，涵盖 9 个阶段：")
    print("  发现 → 非流式/流式翻译 → 多轮续轮 → 取消 → 拒绝 →")
    print("  任务查询 → DataPart/FilePart 多样性翻译 → Bearer 鉴权")
    print()

    client_agent = TranslatorClientAgent(
        server_url="http://127.0.0.1:9999",
        auth_token=DEFAULT_AUTH_TOKEN,
    )

    try:
        await stage_discovery(client_agent)
    except Exception as e:
        print_role("系统", f"连接失败: {e}")
        print()
        print("  请确保 A2A 服务器已启动：python -m server")
        return

    await stage_non_streaming(client_agent)
    await stage_streaming(client_agent)
    await stage_input_required(client_agent)
    await stage_cancel(client_agent)
    await stage_reject(client_agent)
    await stage_task_query(client_agent)
    await stage_multi_part(client_agent)
    await stage_auth(client_agent)

    # ========================================
    # 总结
    # ========================================
    print_banner("Demo 完成")
    print("  A2A 协议完整闭环演示结束！")
    print()
    print("  回顾本 Demo 展示的 A2A 核心概念：")
    print("  1. Agent Card         — Agent 身份名片")
    print("  2. AgentSkill         — Agent 支持的具体技能")
    print("  3. Task 生命周期       — SUBMITTED / WORKING / INPUT_REQUIRED / CANCELED / REJECTED / COMPLETED")
    print("  4. TaskUpdater        — SDK 原生生命周期助手")
    print("  5. Message / Part     — Agent 间通信的消息格式")
    print("  6. Artifact           — Agent 执行任务后的产出物")
    print("  7. Streaming / SSE    — 流式实时传输")
    print("  8. 多轮续轮 / Cancel / Reject / tasks 查询")
    print("  9. DataPart / FilePart 多样性 Part（批量翻译 + 报告文件）")
    print(" 10. security_schemes + BearerAuthMiddleware 鉴权机制")
    print()
    print("  如需了解更多，请阅读 README.md")
    print()


if __name__ == "__main__":
    asyncio.run(main())
