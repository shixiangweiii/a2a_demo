# A2A (Agent2Agent) 协议教程 Demo

本项目是一个基于 **A2A 官方 SDK** (`a2a-sdk`) 的完整教程案例，演示 A2A 协议中三个核心角色的闭环交互流程。

## 什么是 A2A 协议？

A2A (Agent2Agent) 是 Google Cloud 发起的开放协议，旨在让不同 AI Agent 之间实现标准化通信与协作。

## 三个核心角色

```
用户 (User)                客户端智能体              远程智能体（A2A 服务器）
    │                     (Client Agent)            (Remote Agent)
    │                          │                          │
    │  1. 发起翻译请求          │                          │
    │ ──────────────────────>  │                          │
    │                          │  2. 发现 Agent Card       │
    │                          │ ──────────────────────>   │
    │                          │  <─────────────────────   │
    │                          │  3. 发送翻译任务(Task)     │
    │                          │ ──────────────────────>   │
    │                          │         4. 执行翻译        │
    │                          │  <─────────────────────   │
    │  5. 展示翻译结果          │     返回结果(Artifact)     │
    │ <──────────────────────  │                          │
```

## 项目结构

```
a2a_demo/
├── server/                    # A2A 服务器（远程智能体）
│   ├── __init__.py
│   ├── __main__.py            # 服务器启动入口
│   ├── agent.py               # 翻译 Agent 核心业务逻辑
│   └── agent_executor.py      # AgentExecutor 实现
├── client/                    # A2A 客户端（客户端智能体）
│   ├── __init__.py
│   └── client_agent.py        # 客户端智能体封装
├── main.py                    # 用户交互入口（演示完整闭环）
├── requirements.txt           # Python 依赖
└── README.md                  # 本文件
```

## 快速开始

### 1. 安装依赖

```bash
# 激活虚拟环境
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 2. 启动 A2A 服务器（远程智能体）

```bash
python -m server
```

启动后你会看到：
```
============================================================
  A2A 翻译智能体服务器 (Remote Agent)
============================================================
  Agent 名称:  Translator Agent (翻译智能体)
  服务地址:    http://127.0.0.1:9999
  Agent Card:  http://127.0.0.1:9999/.well-known/agent-card.json
============================================================
```

### 3. 运行客户端（新开一个终端）

```bash
source .venv/bin/activate
python main.py
```

> 客户端内置默认 Bearer Token 为 `demo-secret-token`（见 `main.py` 的 `DEFAULT_AUTH_TOKEN`），与服务端的白名单一致，无需额外配置即可运行所有阶段。

### 4. 验证运行结果

正常运行时所有阶段均会依次打印横条标题。每个阶段的核心预期输出如下（摘错用）：

| 阶段 | 期望看到的关键行 |
|------|-----------------|
| 1 发现 | `名称: Translator Agent (翻译智能体)` / `版本: 1.0.0` / `技能数: 3` |
| 2 非流式 | `翻译结果: "Hello"` / `Artificial Intelligence` / `How is the weather today` |
| 3 流式 | 逐条 `chunk #n [产出物到达]` ，最终 `TASK_STATE_COMPLETED` |
| 4 多轮 | 首轮 `INPUT_REQUIRED`；续轮 `"Machine Learning"` 且 `COMPLETED` |
| 5 Cancel | 收到3 个 chunk 后下发 cancel；最终 `TASK_STATE_CANCELED` |
| 6 Reject | 输入英文被拒 → `TASK_STATE_REJECTED` |
| 7 查询 | `tasks/get` / `tasks/list` 正常返回列表和快照 |
| 8 多 Part | DataPart 返 4 行翻译；FilePart `translation_report.txt` 约 150 bytes |
| 9 鉴权 | 错误 token 抛 `A2AClientError: HTTP Error 401`；正确 token `"Hello"` `COMPLETED` |

### 5. 仅运行某一阶段（可选）

各阶段均封装为独立的 `async def stage_xxx(...)` 函数。若想只运行某个阶段，直接修改 `main.py` 的 `main()` 函数，注释掉不想跑的 `await stage_xxx(client_agent)` 即可：

```python
await stage_discovery(client_agent)         # 阶段 1 必要跳过
# await stage_non_streaming(client_agent)   # 阶段 2
# await stage_streaming(client_agent)       # 阶段 3
await stage_multi_part(client_agent)        # 单跑阶段 8
await stage_auth(client_agent)              # 单跑阶段 9
```

> 阶段 1（发现）是所有后续阶段的前置，因为后续请求需要 `agent_card` 解析 RPC URL 和 security_schemes。

### 6. 用 curl 验证鉴权端到端（可选）

在服务端运行的情况下，可以通过 curl 独立验证 Bearer 鉴权逻辑（HTTP 层）：

```bash
# 1. Agent Card 公开端点（属于 /.well-known/ 白名单，免鉴权），应返 200
curl -s -o /dev/null -w "HTTP %{http_code}\n" \
  http://127.0.0.1:9999/.well-known/agent-card.json

# 2. 不携 token 访问 JSON-RPC 端点，应返 401 + WWW-Authenticate 头
curl -s -o /dev/null -w "HTTP %{http_code}\n" -X POST http://127.0.0.1:9999/ \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":"1","method":"SendMessage","params":{}}'

# 3. 携错误 token，应返 401
curl -s -o /dev/null -w "HTTP %{http_code}\n" -X POST http://127.0.0.1:9999/ \
  -H 'Authorization: Bearer wrong-token' \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":"1","method":"SendMessage","params":{}}'

# 4. 携正确 token，应返 200（响应体是 JSON-RPC 层错误是正常的，
#    因为这里 params 为空；目的只是验证鉴权中间件放行）
curl -s -o /dev/null -w "HTTP %{http_code}\n" -X POST http://127.0.0.1:9999/ \
  -H 'Authorization: Bearer demo-secret-token' \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":"1","method":"SendMessage","params":{}}'
```

期望输出：`HTTP 200` / `HTTP 401` / `HTTP 401` / `HTTP 200`。

> 完整的业务端到端验证（请求 → Task 生命周期 → Artifact）建议直接运行 `python main.py`，
> 里面的 `stage_auth` 已用错误/正确 token 各走一遍，比手工拼 JSON-RPC 请求体更直接。

### 7. 常见故障排查

| 现象 | 原因 | 处置 |
|------|------|------|
| `[errno 48] address already in use` | 9999 端口被旧进程占用 | `lsof -ti :9999 \| xargs kill -9` 后重启服务 |
| `A2AClientError: HTTP Error 401` | 客户端 token 缺失或错误 | 确认 `main.py` 的 `DEFAULT_AUTH_TOKEN` 与 `server/__main__.py` 的 `VALID_BEARER_TOKENS` 一致 |
| `ModuleNotFoundError: a2a` | 虚拟环境未激活或依赖未装 | `source .venv/bin/activate && pip install -r requirements.txt` |
| `InvalidParamsError: Validation failed` | 手写 Message 时缺 `message_id` | 构造空文本 Message 时补上 `message_id=str(uuid.uuid4())`（见 `_build_user_message`） |
| 阶段 4 续轮返回 `INPUT_REQUIRED` 而非 `COMPLETED` | `context.current_task` 已存在时错误地再 `enqueue_event(task)` | 确认 `agent_executor.py` 保有 `if not is_followup: enqueue_event(task)` |
| 阶段 8 `未返回预期的 DataPart 结果` | `skill_id` 没有通过 metadata 传到服务端 | 检查 `_build_user_message` 中是否写入了 `md_payload["skill_id"]` |

## 关键概念

| 概念 | 说明 |
|------|------|
| **Agent Card** | Agent 的身份名片，声明能力和接口，通过 `/.well-known/agent-card.json` 获取 |
| **AgentSkill** | Agent 支持的具体技能描述 |
| **Task** | A2A 交互的核心单元，有完整的生命周期（WORKING → COMPLETED） |
| **Message/Part** | Agent 间通信的消息格式，支持文本、文件等 |
| **Artifact** | Agent 执行任务后的产出物 |
| **AgentExecutor** | SDK 核心接口，连接协议层和业务逻辑层 |

## 代码解读

### 服务器端核心流程

1. **定义技能** — `AgentSkill` 描述 Agent 能做什么
2. **创建名片** — `AgentCard` 声明 Agent 信息和支持的接口
3. **实现执行器** — `AgentExecutor.execute()` 处理请求并返回结果
4. **启动服务** — 通过 Starlette + Uvicorn 提供 HTTP 服务

### 客户端核心流程

1. **发现 Agent** — 通过 `A2ACardResolver` 获取 Agent Card
2. **创建客户端** — 通过 `create_client()` 创建 A2A 客户端
3. **发送消息** — 通过 `client.send_message()` 发送请求
4. **处理响应** — 解析返回的 Message 或 Task 结果

## TaskUpdater —— 服务端生命周期事件助手

在 `server/agent_executor.py` 中，所有 Task 生命周期事件都通过 **`TaskUpdater`**（由 `a2a-sdk` 提供）发出，而不是手写 `TaskStatusUpdateEvent` / `TaskArtifactUpdateEvent`。

### 为什么用 TaskUpdater？

| 维度 | 手写事件（旧方式） | TaskUpdater（推荐） |
|------|-------------------|-------------------|
| 字段填充 | 需自己填 `task_id` / `context_id` / `timestamp` / `status.state` 等 | 自动填充 |
| 终态保护 | 无，可能多次下发 COMPLETED 等终态 | 内置 `_terminal_state_reached` 锁 |
| 可读性 | 事件结构冗长 | 语义化 API：`start_work` / `complete` / `cancel` / `requires_input` ... |
| 协议一致性 | 易漏字段 | 紧跟 SDK，向后兼容 |

### 方法对照表

| TaskUpdater 方法 | 对应 Task 状态 | 使用场景 |
|-----------------|---------------|---------|
| `submit()` | `TASK_STATE_SUBMITTED` | 任务已提交，等待处理 |
| `start_work()` | `TASK_STATE_WORKING` | 开始执行业务逻辑 |
| `requires_input()` | `TASK_STATE_INPUT_REQUIRED` | 需要用户补充信息后续轮 |
| `requires_auth()` | `TASK_STATE_AUTH_REQUIRED` | 需要用户完成鉴权后继续 |
| `add_artifact(parts, name=...)` | —（`TaskArtifactUpdateEvent`） | 下发产出物（可多次） |
| `complete()` | `TASK_STATE_COMPLETED` | 任务完成（终态） |
| `cancel()` | `TASK_STATE_CANCELED` | 任务被取消（终态） |
| `reject()` | `TASK_STATE_REJECTED` | 拒绝接受任务（终态） |
| `failed()` | `TASK_STATE_FAILED` | 任务失败（终态） |

> 注：初始 `Task` 对象（由 `new_task_from_user_message()` 创建）自带 `SUBMITTED` 状态，只需 `event_queue.enqueue_event(task)` 即可，通常**无须再调用 `submit()`**。
>
> ⚠️ **续轮不要再 enqueue**：当 `context.current_task` 非空（续轮场景）时，SDK 已从 `TaskStore` 恢复任务，此时再 `enqueue_event(task)` 会把旧的 `INPUT_REQUIRED` 快照塞回结果聚合器，导致客户端看不到新一轮的 `WORKING → COMPLETED` 流。本 Demo 在 `agent_executor.py` 中通过 `if not is_followup: enqueue_event(task)` 显式规避。

## Demo 覆盖的 9 个阶段

`main.py` 依次演示 A2A 协议的完整能力矩阵：

| 阶段 | 演示主题 | 关键 API / 概念 |
|------|---------|----------------|
| 1 | **发现 Agent Card** | `A2ACardResolver.get_agent_card()` |
| 2 | **非流式翻译** | `client.send_message()` 单次返回 |
| 3 | **流式翻译** | `streaming=True`，增量聚合 `WORKING → COMPLETED` |
| 4 | **input-required 多轮** | `requires_input()` + 客户端续轮 `task_id` |
| 5 | **Cancel 取消任务** | `client.cancel_task()` → `TASK_STATE_CANCELED` |
| 6 | **Reject 拒绝任务** | 业务规则命中后 `reject()` → `TASK_STATE_REJECTED` |
| 7 | **Task 查询** | `get_task(task_id)` / `list_tasks()` 回溯历史任务 |
| 8 | **DataPart / FilePart** | 结构化数据上下行、文件 Artifact 产出 |
| 9 | **Bearer 鉴权** | `security_schemes` + 中间件拦截未授权请求 |

## 多 AgentSkill 与多模态 Part

本 Demo 在服务端注册了 **3 个 AgentSkill**，客户端通过 `Message.metadata.skill_id` 路由到对应分支：

| Skill ID | 输入模态 | 输出模态 | 业务含义 |
|----------|---------|---------|---------|
| `translate_zh_to_en` | `text/plain` | `text/plain` | 默认文本翻译（流式/非流式/多轮） |
| `translate_batch_zh_to_en` | `application/json` | `application/json` | 批量翻译，上下行皆为 **DataPart** |
| `translate_report` | `text/plain` | `text/plain` | 生成翻译报告，通过 **FilePart** 回传 |

### DataPart（结构化数据）

协议中 `Part` 是 oneof 扁平结构，构造 DataPart 时使用 `google.protobuf.Value` + `ParseDict`：

```python
from google.protobuf.struct_pb2 import Value
from google.protobuf.json_format import ParseDict, MessageToDict
from a2a.grpc.a2a_pb2 import Part

# 发送侧：dict → Value → Part(data=...)
value = Value()
ParseDict({"items": ["你好", "再见"]}, value)
part = Part(data=value, media_type="application/json")

# 接收侧：Part.data → dict
payload = MessageToDict(part.data)
```

### FilePart（文件产出）

服务端通过 `TaskUpdater.add_artifact()` 下发文件 Part：

```python
content = build_translation_report(text)  # str
await updater.add_artifact(
    parts=[Part(
        raw=content.encode("utf-8"),
        filename="translation_report.txt",
        media_type="text/plain; charset=utf-8",
    )],
    name="translation_report_file",
)
```

客户端用 `part.HasField("raw")` 识别文件 Part，再读取 `filename` / `media_type` / `raw`（bytes）。

## Bearer 鉴权（security_schemes）

服务端声明安全方案并挂载鉴权中间件，客户端通过 `httpx.AsyncClient` 注入 `Authorization` 请求头：

### 服务端：AgentCard 声明 + 中间件拦截

```python
# server/__main__.py
agent_card = AgentCard(
    ...,
    security_schemes={
        "bearerAuth": SecurityScheme(
            http_auth_security_scheme=HTTPAuthSecurityScheme(
                scheme="bearer", bearer_format="demo-token",
            )
        )
    },
    security_requirements=[
        SecurityRequirement(schemes={"bearerAuth": StringList(list=[])})
    ],
)

class BearerAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if any(request.url.path.startswith(p) for p in PUBLIC_PATH_PREFIXES):
            return await call_next(request)      # /.well-known/ 公开
        auth = request.headers.get("authorization", "")
        if not auth.lower().startswith("bearer ") or \
           auth[7:].strip() not in VALID_BEARER_TOKENS:
            return JSONResponse({...}, status_code=401,
                                headers={"WWW-Authenticate": 'Bearer realm="a2a"'})
        return await call_next(request)
```

> **Agent Card 端点必须免鉴权**（白名单 `/.well-known/`），否则客户端连 Agent 的能力都发现不了。

### 客户端：注入 httpx.AsyncClient

```python
# client/client_agent.py
httpx_client = httpx.AsyncClient(
    headers={"Authorization": f"Bearer {self.auth_token}"},
    timeout=30.0,
)
config = ClientConfig(streaming=streaming, httpx_client=httpx_client)
```

阶段 9 演示了 **错误 token → HTTP 401 / 正确 token → COMPLETED** 的完整对照。

## Message 必填字段提醒

`Message.message_id` 是 A2A 协议的 **required 字段**。SDK 的 `new_text_message(text, ...)` 会自动生成；但若你手工构造（例如 text 为空、仅携带 DataPart 的场景），必须显式赋值：

```python
message = Message(role=Role.ROLE_USER, message_id=str(uuid.uuid4()))
message.parts.append(Part(data=data_value, media_type="application/json"))
```

否则会在请求时抛 `InvalidParamsError: Validation failed`。
