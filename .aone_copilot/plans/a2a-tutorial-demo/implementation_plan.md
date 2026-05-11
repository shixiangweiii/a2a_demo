# 基于 A2A 官方 SDK 构建完整教程 Demo

本计划将在 `/Users/shixiangweii/PycharmProjects/2026_qoder_proj/a2a_demo` 项目中，使用 A2A 官方 SDK（`a2a-sdk`）创建一个包含三个核心角色的教程案例 Demo，实现 A2A 协议的完整闭环交互。

## Proposed Changes

### 项目配置与依赖

#### [NEW] [requirements.txt](file:///Users/shixiangweii/PycharmProjects/2026_qoder_proj/a2a_demo/requirements.txt)
项目依赖清单，包含：
- `a2a-sdk[http-server]` — A2A 官方 SDK（含 HTTP Server 支持）
- `httpx` — HTTP 客户端
- `uvicorn` — ASGI 服务器
- `starlette` — Web 框架
- `pydantic` — 数据模型

---

### A2A 服务器（远程智能体）

业务场景选择 **"智能翻译助手"**：接收用户输入的中文文本，返回一个模拟的英文翻译结果。逻辑简单但完整展示了 A2A 协议的 Task 生命周期。

#### [NEW] [server/agent.py](file:///Users/shixiangweii/PycharmProjects/2026_qoder_proj/a2a_demo/server/agent.py)
翻译 Agent 的核心业务逻辑类 `TranslatorAgent`：
- `invoke(text)` — 同步翻译：接收中文文本，返回模拟翻译结果
- `stream(text)` — 流式翻译：将翻译结果分多个 chunk 返回

```python
class TranslatorAgent:
    """模拟翻译 Agent - 将中文翻译为英文"""

    MOCK_TRANSLATIONS = {
        "你好": "Hello",
        "世界": "World",
        # ...更多预设
    }

    async def invoke(self, text: str) -> str:
        """同步翻译"""
        return self.MOCK_TRANSLATIONS.get(text, f"[Translated] {text}")

    async def stream(self, text: str) -> AsyncGenerator[str, None]:
        """流式翻译，逐词返回"""
        result = await self.invoke(text)
        for word in result.split():
            yield word + " "
```

#### [NEW] [server/agent_executor.py](file:///Users/shixiangweii/PycharmProjects/2026_qoder_proj/a2a_demo/server/agent_executor.py)
`TranslatorAgentExecutor` 类，继承 `AgentExecutor`，负责：
- 解析 `RequestContext` 中用户发送的消息
- 调用 `TranslatorAgent` 执行翻译
- 通过 `EventQueue` 发送 Task 状态更新事件（WORKING → COMPLETED）
- 通过 `TaskArtifactUpdateEvent` 返回翻译结果

```python
class TranslatorAgentExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue):
        # 1. 创建/获取任务
        # 2. 发送 WORKING 状态
        # 3. 提取用户消息文本，调用 agent.invoke()
        # 4. 发送翻译结果 Artifact
        # 5. 发送 COMPLETED 状态

    async def cancel(self, context, event_queue):
        raise Exception("cancel not supported")
```

#### [NEW] [server/\_\_main\_\_.py](file:///Users/shixiangweii/PycharmProjects/2026_qoder_proj/a2a_demo/server/__main__.py)
A2A 服务器启动入口，负责：
- 定义 `AgentSkill`（翻译技能）
- 创建 `AgentCard`（代理名片），声明 Agent 能力
- 配置 `DefaultRequestHandler`（含 `InMemoryTaskStore`）
- 使用 Starlette + Uvicorn 启动 HTTP 服务（`127.0.0.1:9999`）
- 注册 Agent Card 路由（`/.well-known/agent.json`）和 JSON-RPC 路由

---

### A2A 客户端（客户端智能体）

#### [NEW] [client/client_agent.py](file:///Users/shixiangweii/PycharmProjects/2026_qoder_proj/a2a_demo/client/client_agent.py)
`TranslatorClientAgent` 类，封装 A2A 客户端交互逻辑：
- `discover()` — 通过 `A2ACardResolver` 获取远程 Agent Card
- `translate(text)` — 非流式调用：发送翻译请求，等待完整结果
- `translate_stream(text)` — 流式调用：发送请求，逐步接收翻译结果
- `display_agent_info()` — 展示远程 Agent 的能力信息

```python
class TranslatorClientAgent:
    def __init__(self, server_url: str):
        self.server_url = server_url

    async def discover(self) -> AgentCard:
        """发现远程 Agent，获取 Agent Card"""

    async def translate(self, text: str) -> str:
        """非流式翻译请求"""

    async def translate_stream(self, text: str):
        """流式翻译请求"""
```

---

### 用户交互入口

#### [NEW] [main.py](file:///Users/shixiangweii/PycharmProjects/2026_qoder_proj/a2a_demo/main.py)
用户交互入口脚本，模拟完整的 A2A 闭环流程：
1. **发现阶段** — 客户端智能体连接 A2A 服务器，获取 Agent Card
2. **非流式调用** — 用户发送翻译请求，客户端转发给远程 Agent，获取完整结果
3. **流式调用** — 用户发送翻译请求，客户端以流式方式接收结果
4. **展示结果** — 打印完整的交互日志，体现三个角色的交互过程

每个步骤都有清晰的日志输出，标注当前是哪个角色在执行操作。

---

### 教程说明文档

#### [NEW] [README.md](file:///Users/shixiangweii/PycharmProjects/2026_qoder_proj/a2a_demo/README.md)
完整的教程说明文档，包含：
- A2A 协议简介与三个角色说明
- 项目结构说明
- 环境安装步骤
- 运行步骤（先启动 Server，再运行 Client）
- 代码解读与关键概念说明
- 扩展建议

---

### 辅助文件

#### [NEW] [server/\_\_init\_\_.py](file:///Users/shixiangweii/PycharmProjects/2026_qoder_proj/a2a_demo/server/__init__.py)
空的 Python 包初始化文件

#### [NEW] [client/\_\_init\_\_.py](file:///Users/shixiangweii/PycharmProjects/2026_qoder_proj/a2a_demo/client/__init__.py)
空的 Python 包初始化文件

## Verification Plan

### Automated Tests
1. 安装依赖：
```bash
source .venv/bin/activate
pip install -r requirements.txt
```

2. 启动 A2A 服务器：
```bash
python -m server
```

3. 在另一个终端运行客户端测试：
```bash
python main.py
```

4. 验证输出中包含：
   - Agent Card 成功获取
   - 非流式翻译结果正确返回
   - 流式翻译逐步输出
   - Task 状态从 WORKING 到 COMPLETED 完整流转

### Manual Verification
- 用户在浏览器中访问 `http://127.0.0.1:9999/.well-known/agent.json` 确认 Agent Card 正常返回
- 观察终端日志，确认三个角色（User → Client Agent → Remote Agent）交互链路完整


---
生成时间: 2026/5/11 17:38:02
planId: ea4b0765-fc8c-4846-a0e4-f4aba4c81ac9
plan_status: review