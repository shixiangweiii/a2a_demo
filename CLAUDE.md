# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A2A (Agent2Agent) protocol tutorial demo built with `a2a-sdk`. It demonstrates a closed-loop interaction between three roles: User, Client Agent, and Remote Agent (A2A Server). The Remote Agent is a mock Chinese-to-English translator using a preset dictionary — no LLM integration.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Start the A2A server (Remote Agent) on port 9999
python -m server

# Run the client demo (requires server to be running first, in a separate terminal)
python main.py
```

## Architecture

**Server side** (`server/`):
- `__main__.py` — Entry point. Defines `AgentSkill`, `AgentCard`, wires `DefaultRequestHandler` with `InMemoryTaskStore`, registers Starlette routes (agent card + JSON-RPC), starts Uvicorn on `127.0.0.1:9999`. Includes `RequestLoggingMiddleware` for verbose HTTP logging.
- `agent.py` — `TranslatorAgent`: pure business logic. Uses a hardcoded dictionary (`MOCK_TRANSLATIONS`) with simulated async delay. Has both `invoke()` (full result) and `stream()` (word-by-word generator) methods.
- `agent_executor.py` — `TranslatorAgentExecutor` implements the SDK's `AgentExecutor` interface. Bridges the A2A protocol layer and `TranslatorAgent`. Manages full Task lifecycle: create task → WORKING → extract user text → call agent → emit Artifact → COMPLETED (or FAILED on error).

**Client side** (`client/`):
- `client_agent.py` — `TranslatorClientAgent` wraps `A2ACardResolver` (discovery) and `create_client` (communication). Supports both streaming and non-streaming modes via `ClientConfig(streaming=...)`. Parses `StreamResponse` oneof payloads (task, message, status_update, artifact_update).

**User entry** (`main.py`):
- Runs a 3-phase demo: Agent Discovery → Non-streaming translate → Streaming translate. Prints formatted output showing the role-based message flow.

## Key A2A Concepts Used

- **Agent Card** (`/.well-known/agent-card.json`) — Agent metadata including skills, capabilities, and interface URLs
- **AgentSkill** — Declares what the agent can do (id, name, description, tags, examples)
- **Task lifecycle** — SUBMITTED → WORKING → Artifact produced → COMPLETED (or FAILED)
- **AgentExecutor** — SDK interface connecting protocol layer to business logic via `execute()` / `cancel()`
- **EventQueue** — Used in executor to emit `TaskStatusUpdateEvent` and `TaskArtifactUpdateEvent`
- **StreamResponse** — Oneof payload: `task`, `message`, `status_update`, `artifact_update`

## Tech Stack

Python 3.12, `a2a-sdk[http-server]`, Starlette, Uvicorn, httpx, Pydantic, protobuf, sse-starlette
