# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A2A (Agent2Agent) protocol tutorial demo built on `a2a-sdk`. It demonstrates a closed loop between three roles: User, Client Agent, and Remote Agent (A2A Server). The Remote Agent is a mock Chinese→English translator backed by a preset dictionary — no LLM. Code comments, logs, and README are in Chinese; the demo is teaching material, so verbose logging and step-by-step comments are intentional.

## Commands

`python` is not on PATH — the venv must be activated (or use `.venv/bin/python` directly).

```bash
source .venv/bin/activate
pip install -r requirements.txt

# Terminal 1 — start the Remote Agent on 127.0.0.1:9999
python -m server

# Terminal 2 — run the 9-stage client demo
python main.py
```

There is no test suite, linter, or build step. Verification is running the demo end to end and checking stage output (README has an expected-output table per stage).

**Running a single stage:** each stage is an independent `async def stage_xxx(client_agent)` in `main.py`. Comment out unwanted `await stage_xxx(...)` calls in `main()`. `stage_discovery` is a prerequisite for everything else — it populates `agent_card`, which is needed to resolve the RPC URL.

Port 9999 left occupied by a stale server: `lsof -ti :9999 | xargs kill -9`.

## Architecture

**Server** (`server/`):
- `__main__.py` — Builds 3 `AgentSkill`s + the `AgentCard` (including `security_schemes`), wires `DefaultRequestHandler` with `InMemoryTaskStore`, registers agent-card + JSON-RPC routes, mounts two Starlette middlewares (`RequestLoggingMiddleware` then `BearerAuthMiddleware`), runs Uvicorn.
- `agent.py` — `TranslatorAgent`, pure business logic, no protocol types. `MOCK_TRANSLATIONS` dict plus `classify_input()` (drives input-required/reject), `invoke()`, `stream()`, `translate_batch()`, `build_translation_report()`, `slow_translate()` (segmented output with a `cancel_event` probe).
- `agent_executor.py` — `TranslatorAgentExecutor` implements the SDK `AgentExecutor`. Routes by `skill_id`, then by `mode`, and emits every lifecycle event through `TaskUpdater`.

**Client** (`client/client_agent.py`) — `TranslatorClientAgent` wraps `A2ACardResolver` (discovery) and `create_client`. Each public method builds its own client via `_make_client(streaming=...)` and closes it in a `finally`, so streaming and non-streaming calls never share state. Non-streaming results are folded into a `TranslateResult` dataclass by `_absorb_chunk_into_result` / `_absorb_part`.

**Entry** (`main.py`) — 9 sequential stages: discovery → non-streaming → streaming → input-required follow-up → cancel → reject → task query → DataPart/FilePart → Bearer auth.

## Conventions and Gotchas

**Types are protobuf, not Pydantic.** Messages come from `a2a.types.a2a_pb2`. `Part` is a flat oneof (`text` / `data` / `raw`), so always probe with `part.HasField("text")`, never truthiness. `Message.metadata` is a `google.protobuf.Struct`, read as `msg.metadata.fields["key"].string_value`.

**`Message.message_id` is required.** `new_text_message()` fills it in; hand-built messages (e.g. empty text carrying only a DataPart) must set `message_id=str(uuid.uuid4())` or the request fails with `InvalidParamsError: Validation failed`.

**Use `TaskUpdater`, never hand-written `TaskStatusUpdateEvent` / `TaskArtifactUpdateEvent`.** It fills task/context ids and timestamps and enforces a terminal-state lock. Methods map to states: `start_work` → WORKING, `requires_input` → INPUT_REQUIRED, `complete` / `cancel` / `reject` / `failed` → terminal, `add_artifact` → artifact event.

**Do not re-enqueue the Task on a follow-up turn.** `new_task_from_user_message()` already produces a SUBMITTED task, so the first turn only needs `event_queue.enqueue_event(task)`. On a follow-up (`context.current_task` is non-empty) the SDK has already restored the task from `TaskStore`; enqueuing again pushes the stale INPUT_REQUIRED snapshot into the result aggregator and the client never sees the new WORKING → COMPLETED flow. Guarded by `if not is_followup:` in `agent_executor.py`.

**Cancel is split across two coroutines.** `DefaultRequestHandler` calls `cancel()` and then cancels the `execute()` coroutine. `cancel()` must itself emit the CANCELED terminal state (the aggregator errors out otherwise) and set the `asyncio.Event` in `self._cancel_events[task_id]` so the slow loop exits. `execute()` deliberately swallows nothing on `CancelledError` — it re-raises without writing a terminal state.

**Skill routing goes through message metadata, not the protocol.** The client puts `skill_id` (and `mode`) into `Message.metadata`; the executor reads it and branches. Skills: `translate_zh_to_en` (default text), `translate_batch_zh_to_en` (DataPart in/out), `translate_report` (FilePart out). Batch and report paths skip the Chinese-character validation.

**DataPart construction:** `dict` → `google.protobuf.struct_pb2.Value` via `ParseDict`, then `Part(data=value, media_type="application/json")`; decode with `MessageToDict(part.data)`. **FilePart:** `Part(raw=bytes, filename=..., media_type=...)`.

**Bearer auth.** `VALID_BEARER_TOKENS` in `server/__main__.py` must stay in sync with `DEFAULT_AUTH_TOKEN` in `main.py` (`demo-secret-token`), otherwise everything after discovery fails with `A2AClientError: HTTP Error 401`. `/.well-known/` is whitelisted in `PUBLIC_PATH_PREFIXES` and must stay public — discovery happens before the client has any token.
