"""
A2A 教程 Demo — 用户交互入口

本脚本模拟完整的 A2A 协议闭环交互流程，包含三个角色：
  1. 用户（User）        — 发起翻译请求
  2. 客户端智能体（Client Agent） — 发现远程 Agent、转发请求
  3. 远程智能体（Remote Agent）   — 执行翻译并返回结果

运行前请确保 A2A 服务器已启动：
    python -m server

然后运行本脚本：
    python main.py
"""

import asyncio
import logging

from a2a.types.a2a_pb2 import TaskState
from client.client_agent import TranslatorClientAgent


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


async def main():
    """运行 A2A 教程 Demo 的完整闭环流程。"""

    # 配置 logging，让客户端的底层请求日志也能输出
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    # 降低第三方库的日志级别，避免干扰
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    print_banner("A2A (Agent2Agent) 协议教程 Demo")
    print("  本 Demo 演示 A2A 协议中三个核心角色的交互流程：")
    print("  用户 → 客户端智能体 → 远程智能体 → 客户端智能体 → 用户")
    print()

    # 创建客户端智能体
    client_agent = TranslatorClientAgent(server_url="http://127.0.0.1:9999")

    # ========================================
    # 阶段 1：Agent 发现（Discovery）
    # ========================================
    print_banner("阶段 1：Agent 发现 (Discovery)")
    print_role("系统", "A2A 协议的第一步是发现远程 Agent")
    print_role("客户端", "正在连接远程 Agent，获取 Agent Card...")
    print_role("客户端", f"请求地址: {client_agent.server_url}/.well-known/agent-card.json")
    print()

    try:
        agent_card = await client_agent.discover()
    except Exception as e:
        print_role("系统", f"连接失败: {e}")
        print()
        print("  请确保 A2A 服务器已启动：python -m server")
        return

    # 打印原始 agent_card 对象，便于学习理解返回结构
    print_role("客户端", "原始 agent_card 对象:")
    print(f"  {agent_card!r}")
    print()
    print_role("客户端", "成功获取 Agent Card！远程 Agent 信息如下：")
    print("-" * 50)
    client_agent.display_agent_info()
    print("-" * 50)

    # ========================================
    # 阶段 2：非流式翻译请求
    # ========================================
    print_banner("阶段 2：非流式翻译请求 (Non-Streaming)")
    print_role("系统", "用户发起翻译请求，客户端转发给远程 Agent，等待完整结果返回")
    print()

    test_texts = ["你好", "人工智能", "今天天气怎么样"]

    for text in test_texts:
        print_role("用户", f'请翻译: "{text}"')
        print_role("客户端", f"正在将请求转发给远程 Agent...")

        try:
            result = await client_agent.translate(text)
            print_role("服务器", f'翻译结果: "{result}"')
        except Exception as e:
            print_role("服务器", f"翻译出错: {e}")

        print()

    # ========================================
    # 阶段 3：流式翻译请求
    # ========================================
    print_banner("阶段 3：流式翻译请求 (Streaming)")
    print_role("系统", "用户发起流式翻译请求，结果逐步返回（类似 LLM 流式输出）")
    print()

    stream_text = "我是一个AI助手"
    print_role("用户", f'请翻译（流式）: "{stream_text}"')
    print_role("客户端", "正在以流式方式接收翻译结果...")
    print()
    print("  收到的流式响应 chunks:")

    chunk_count = 0
    try:
        async for chunk in client_agent.translate_stream(stream_text):
            chunk_count += 1
            # 解析流式 chunk 类型，展示 Task 生命周期
            payload_type = chunk.WhichOneof("payload")
            if payload_type == "task":
                state = chunk.task.status.state
                print(f"    chunk #{chunk_count} [Task 创建]     → 任务已提交 (SUBMITTED)")
            elif payload_type == "status_update":
                state = chunk.status_update.status.state
                if state == TaskState.TASK_STATE_WORKING:
                    print(f"    chunk #{chunk_count} [状态更新]     → 正在处理中 (WORKING)")
                elif state == TaskState.TASK_STATE_COMPLETED:
                    msg_text = ""
                    if chunk.status_update.status.message:
                        for part in chunk.status_update.status.message.parts:
                            if part.HasField("text"):
                                msg_text = part.text
                    print(f"    chunk #{chunk_count} [状态更新]     → 任务完成 (COMPLETED): {msg_text}")
                elif state == TaskState.TASK_STATE_FAILED:
                    print(f"    chunk #{chunk_count} [状态更新]     → 任务失败 (FAILED)")
                else:
                    print(f"    chunk #{chunk_count} [状态更新]     → 状态码: {state}")
            elif payload_type == "artifact_update":
                artifact_text = ""
                for part in chunk.artifact_update.artifact.parts:
                    if part.HasField("text"):
                        artifact_text = part.text
                print(f"    chunk #{chunk_count} [产出物到达]   → 翻译结果: \"{artifact_text}\"")
            else:
                print(f"    chunk #{chunk_count} [{payload_type}]")
    except Exception as e:
        print(f"    流式请求出错: {e}")

    print()
    print_role("客户端", f"流式传输完成，共收到 {chunk_count} 个 chunk")
    print()
    print("  Task 生命周期回顾:")
    print("    SUBMITTED → WORKING → Artifact 产出 → COMPLETED")

    # ========================================
    # 总结
    # ========================================
    print_banner("Demo 完成")
    print("  A2A 协议完整闭环演示结束！")
    print()
    print("  回顾本 Demo 展示的 A2A 核心概念：")
    print("  1. Agent Card   — Agent 的身份名片，声明能力和接口")
    print("  2. AgentSkill   — Agent 支持的具体技能")
    print("  3. Task         — A2A 交互的核心单元（含生命周期）")
    print("  4. Message/Part — Agent 间通信的消息格式")
    print("  5. Artifact     — Agent 执行任务后的产出物")
    print("  6. Streaming    — 支持流式实时传输")
    print()
    print("  如需了解更多，请阅读 README.md")
    print()


if __name__ == "__main__":
    asyncio.run(main())
