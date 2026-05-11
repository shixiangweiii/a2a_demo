"""
A2A 服务器启动入口

本文件是 A2A 远程智能体的启动脚本，负责：
1. 定义 Agent 的技能（AgentSkill）
2. 创建 Agent 名片（AgentCard）
3. 配置请求处理器和路由
4. 启动 HTTP 服务器（含请求/响应日志中间件）

运行方式：
    python -m server

启动后，Agent Card 可通过以下地址访问：
    http://127.0.0.1:9999/.well-known/agent-card.json
"""

import logging
import time

import uvicorn

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import (
    create_agent_card_routes,
    create_jsonrpc_routes,
)
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
)
from server.agent_executor import TranslatorAgentExecutor
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """HTTP 请求/响应日志中间件。

    记录每个进入服务器的 HTTP 请求的 method、path、body，
    以及响应的 status code 和耗时，方便教程学习理解底层通信。
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        method = request.method
        path = request.url.path
        client_host = request.client.host if request.client else "unknown"
        client_port = request.client.port if request.client else 0

        logger.info("🌐 [服务端] ========== 收到 HTTP 请求 ==========")
        logger.info("🌐 [服务端] %s %s", method, path)
        logger.info("🌐 [服务端] 来源: %s:%s", client_host, client_port)
        logger.info("🌐 [服务端] Content-Type: %s", request.headers.get("content-type", "N/A"))

        # 读取并记录请求体（仅对 POST 请求记录 body）
        if method == "POST":
            body_bytes = await request.body()
            body_text = body_bytes.decode("utf-8", errors="replace")
            # 截断过长的 body，保留前 1000 个字符
            display_body = body_text[:1000] + ("..." if len(body_text) > 1000 else "")
            logger.info("🌐 [服务端] 请求体 (JSON-RPC):\n%s", display_body)

        start_time = time.monotonic()
        response = await call_next(request)
        elapsed_ms = (time.monotonic() - start_time) * 1000

        logger.info("🌐 [服务端] ✅ 响应状态码: %d | 耗时: %.1fms", response.status_code, elapsed_ms)
        logger.info("🌐 [服务端] Content-Type: %s", response.headers.get("content-type", "N/A"))
        logger.info("🌐 [服务端] =====================================")

        return response


def main():
    """启动 A2A 翻译服务器。"""

    # ========================================
    # Step 1: 定义 Agent 技能（AgentSkill）
    # ========================================
    # AgentSkill 描述了 Agent 能做什么，
    # 客户端可以通过 Agent Card 发现这些技能。
    skill = AgentSkill(
        id="translate_zh_to_en",
        name="中文翻译为英文",
        description="将中文文本翻译为英文。支持常用短语和句子的翻译。",
        tags=["翻译", "中文", "英文", "translation"],
        examples=["你好", "今天天气怎么样", "人工智能"],
    )

    # ========================================
    # Step 2: 创建 Agent 名片（AgentCard）
    # ========================================
    # AgentCard 是 A2A 协议中 Agent 的"身份证"，
    # 它声明了 Agent 的基本信息、能力和支持的接口。
    # 客户端通过 /.well-known/agent-card.json 获取此信息。
    agent_card = AgentCard(
        name="Translator Agent (翻译智能体)",
        description="一个基于 A2A 协议的智能翻译 Agent，能够将中文翻译为英文。这是一个教学演示 Agent。",
        version="1.0.0",
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        capabilities=AgentCapabilities(streaming=True),
        supported_interfaces=[
            AgentInterface(
                protocol_binding="JSONRPC",
                url="http://127.0.0.1:9999",
            )
        ],
        skills=[skill],
    )

    # ========================================
    # Step 3: 配置请求处理器
    # ========================================
    # DefaultRequestHandler 是 A2A SDK 提供的默认请求处理器，
    # 它将 JSON-RPC 请求路由到 AgentExecutor。
    # InMemoryTaskStore 用于在内存中存储任务状态。
    request_handler = DefaultRequestHandler(
        agent_executor=TranslatorAgentExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=agent_card,
    )

    # ========================================
    # Step 4: 配置路由并启动服务器
    # ========================================
    # 注册两类路由：
    # 1. Agent Card 路由: GET /.well-known/agent-card.json
    # 2. JSON-RPC 路由:   POST / (处理 sendMessage 等 RPC 调用)
    routes = []
    routes.extend(create_agent_card_routes(agent_card))
    routes.extend(create_jsonrpc_routes(request_handler, "/"))

    # 将日志中间件加入 Starlette 应用
    app = Starlette(
        routes=routes,
        middleware=[Middleware(RequestLoggingMiddleware)],
    )

    # ========================================
    # Step 5: 配置 logging 格式
    # ========================================
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    # 降低 uvicorn access log 的干扰，避免和我们的日志重复
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    print("=" * 60)
    print("  A2A 翻译智能体服务器 (Remote Agent)")
    print("=" * 60)
    print(f"  Agent 名称:  {agent_card.name}")
    print(f"  Agent 版本:  {agent_card.version}")
    print(f"  技能:        {skill.name}")
    print(f"  服务地址:    http://127.0.0.1:9999")
    print(f"  Agent Card:  http://127.0.0.1:9999/.well-known/agent-card.json")
    print(f"  日志级别:    INFO（含底层请求/响应详情）")
    print("=" * 60)

    uvicorn.run(app, host="127.0.0.1", port=9999)


if __name__ == "__main__":
    main()
