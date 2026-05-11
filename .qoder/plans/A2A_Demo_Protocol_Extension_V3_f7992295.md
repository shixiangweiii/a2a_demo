# A2A Demo 协议扩展计划 V3（端到端复核版）

## 端到端链路已核实要点
1. input-required 续轮原生支持：handler 从 `params.message.task_id` 取 ID → `TaskStore.get` → `context.current_task` 回灌，executor 即可感知续轮
2. SDK 客户端已暴露 send_message / get_task / cancel_task / list_tasks / subscribe 方法
3. SDK 已有 TaskUpdater 助手，应替换当前手写 `TaskStatusUpdateEvent` 写法
4. Part 扁平结构（text / raw / url / data / filename / media_type），FilePart 直接用 `Part(raw=..., filename=..., media_type=...)`
5. Request 字段名确认：GetTaskRequest 用 `id`，CancelTaskRequest 用 `id`
6. SecurityScheme 是 oneof 5 选 1，Bearer 用 `SecurityScheme(http_auth_security_scheme=HTTPAuthSecurityScheme(scheme="bearer"))`
7. SecurityRequirement.schemes 是 Map[str, StringList]

## 9 演示阶段（整合原 11 阶段）
| # | 阶段 | 涉及 A2A 能力 |
|---|------|------|
| 1 | Agent 发现 | AgentCard / security_schemes / 多 AgentSkill |
| 2 | 非流式翻译 | sendMessage（保留） |
| 3 | 流式翻译 | sendMessage streaming（保留） |
| 4 | input-required 多轮 | TaskState.INPUT_REQUIRED / 续轮 task_id |
| 5 | Cancel | cancel_task / TASK_STATE_CANCELED |
| 6 | Rejected | TASK_STATE_REJECTED |
| 7 | Task 查询 | get_task + list_tasks |
| 8 | 多样化 Part | DataPart（detect_language）+ FilePart（文件翻译） |
| 9 | Bearer 鉴权 | security_schemes 正确 token 与错误 token 对照（try/except 兜底） |

## 批次 A：TaskUpdater 重构（不新增功能，做回归基线）
### 文件改动
- [server/agent_executor.py](file:///Users/shixiangweii/PycharmProjects/2026_qoder_proj/a2a_demo/server/agent_executor.py)：改用 TaskUpdater
```
updater = TaskUpdater(event_queue, context.task_id, context.context_id)
await updater.submit()
await updater.start_work(new_text_message("正在翻译中..."))
await updater.add_artifact([Part(text=result)], name="translation_result")
await updater.complete(new_text_message(f"翻译完成: {user_text} -> {result}"))
```
保留原手写 TaskStatusUpdateEvent 写法作注释块作为对照教学。
- [README.md](file:///Users/shixiangweii/PycharmProjects/2026_qoder_proj/a2a_demo/README.md)：新增 "TaskUpdater 对照表"
### 验证
- `python -m server` + `python main.py`，观察阶段 1/2/3 行为与日志一致

## 批次 B：Task 生命周期进阶（阶段 4~7）
### [server/agent.py](file:///Users/shixiangweii/PycharmProjects/2026_qoder_proj/a2a_demo/server/agent.py)
新增：
- `slow_translate(text, cancel_event)`：5s 延时，每 0.5s 检查 cancel_event
- 扩展 `MOCK_TRANSLATIONS`
### [server/agent_executor.py](file:///Users/shixiangweii/PycharmProjects/2026_qoder_proj/a2a_demo/server/agent_executor.py)
- 在 `__init__` 维护 `self._cancel_events: dict[str, asyncio.Event]`
- `execute()` 入口注册 event，退出 finally 清理
- 新增分支判定（按 message.metadata.skill_id 与 text 内容）：
  - 无 text 且未指定 skill → `updater.requires_input(new_text_message("请提供待翻译文本"))`
  - text 纯 ASCII 英文 → `updater.reject(new_text_message("仅支持中译英"))`
  - metadata.skill_id == "slow_translate" → 调 slow_translate，检测 cancel → `updater.cancel(...)`
- `cancel()` 实现：查表 set event
### [client/client_agent.py](file:///Users/shixiangweii/PycharmProjects/2026_qoder_proj/a2a_demo/client/client_agent.py)
- `translate()` 改签名：`translate(text, *, task_id=None, context_id=None, metadata=None)`（向后兼容，默认参数不影响批次 A）
- 新增薄封装方法直接调 SDK 客户端：
  - `cancel_task(task_id)` → `client.cancel_task(CancelTaskRequest(id=task_id))`
  - `get_task(task_id, history_length=None)` → `client.get_task(GetTaskRequest(id=task_id, history_length=...))`
  - `list_tasks(context_id=None)` → `client.list_tasks(ListTasksRequest(context_id=...))`
- 保留单一 httpx_client，context_id 由客户端生成并全 demo 共享
### [main.py](file:///Users/shixiangweii/PycharmProjects/2026_qoder_proj/a2a_demo/main.py)
新增阶段 4/5/6/7 的展示逻辑，阶段 4 用同一 `context_id` 做续轮：
```
t1 = await client_agent.translate("", context_id=CTX)  # 收 INPUT_REQUIRED, 返回 task_id
t2 = await client_agent.translate("你好", task_id=t1, context_id=CTX)  # 同 task 续轮
```
阶段 5 异步并发：`asyncio.gather(translate_stream(metadata=slow_translate), cancel_after(1.5s))`

## 批次 C：多样化 Part + 多 Skill + 鉴权（阶段 8~9）
### [server/agent.py](file:///Users/shixiangweii/PycharmProjects/2026_qoder_proj/a2a_demo/server/agent.py)
新增：
- `detect_language(text) -> dict`
- `translate_lines(lines: list[str]) -> list[str]`
### [server/agent_executor.py](file:///Users/shixiangweii/PycharmProjects/2026_qoder_proj/a2a_demo/server/agent_executor.py)
新增分支：
- `skill_id == "detect_language"`：构造 `Part(data=Value(struct_value=Struct(...)))` 作为 Artifact
- `skill_id == "translate_file"`：读入参 Part 中 `raw + filename + media_type`，翻译后产出同 media_type 的 Part
### [server/__main__.py](file:///Users/shixiangweii/PycharmProjects/2026_qoder_proj/a2a_demo/server/__main__.py)
- 3 个 AgentSkill：translate_zh_to_en、detect_language、translate_file
- `security_schemes={"bearer": SecurityScheme(http_auth_security_scheme=HTTPAuthSecurityScheme(scheme="bearer", bearer_format="JWT"))}`
- `security_requirements=[SecurityRequirement(schemes={"bearer": StringList(list=[""])})]`
- `capabilities=AgentCapabilities(streaming=True, push_notifications=False, extensions=[])`
- `BearerAuthMiddleware`：从 `a2a.utils.constants import AGENT_CARD_WELL_KNOWN_PATH` 放行，其它 POST 校验 `Authorization: Bearer demo-token-123`
### [client/client_agent.py](file:///Users/shixiangweii/PycharmProjects/2026_qoder_proj/a2a_demo/client/client_agent.py)
- `send_with_data(skill_id, options: dict)` → 构造 DataPart
- `send_with_file(file_path)` → 读字节构造 `Part(raw=..., filename=..., media_type="text/plain")`
- 所有默认请求在 httpx_client headers 注入 `Authorization: Bearer demo-token-123`
- 新增参数化入口可用错误 token 新建一个 client 实例（仅阶段 9 用）
### [main.py](file:///Users/shixiangweii/PycharmProjects/2026_qoder_proj/a2a_demo/main.py)
- 阶段 8：调用 detect_language 展示 DataPart；上传 `assets/sample.txt` 展示 FilePart 并写回 `assets/sample.en.txt`
- 阶段 9：先正确 token 成功 → 再错误 token 用 try/except 打印 "预期收到 401"
### 素材
- 新增 `assets/sample.txt`（3~5 行中文）

## Task 通用：README 更新
每批次结束同步更新：
- 概念表补充：INPUT_REQUIRED / CANCELED / REJECTED / DataPart / FilePart / security_schemes / TaskUpdater
- 新增 "9 阶段演示索引"，每阶段标注 A2A 规范章节号
- 新增 "概念 ↔ 代码文件" 对照表

## 不做的事
- Push Notifications（需额外起客户端 Webhook）
- Agent-to-Agent 级联（本轮未选）
- 引入真实 LLM
- resubscribe / subscribe 流断线重连（复杂度高且现有流式已演示 SSE）

## 端到端风险与兜底
- R1: TaskUpdater 重构后阶段 2/3 输出格式如与原版存在差异：批次 A 回归时逐项对齐日志关键字
- R2: SecurityRequirement 字段名以实际 pyi 为准（已核对：schemes 是 MessageMap[str, StringList]）
- R3: Bearer 中间件误拦 SSE 或 JSON-RPC：中间件只 allowlist `AGENT_CARD_WELL_KNOWN_PATH`，其它全校验（含 GET 也要，以演示真实鉴权）
- R4: 阶段 5 cancel 比 complete 晚导致无法取消：slow_translate 首次 sleep 0.5s 后再返回结果，cancel 1s 后发，时序可靠
- R5: `main.py` 阶段 9 以 401 收尾影响整体成功态：try/except 包裹并打印预期信息，最终正常退出
