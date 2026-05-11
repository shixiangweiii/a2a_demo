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
