# Agent Team 多 Agent 协作重设计

> 2026-07-05 | brainstorming | 基于 LangGraph Send API 的 Supervisor + Worker 模式

## 背景

`2026-06-30-agent-team-design.md` 描述了 Supervisor + Worker 的概念模型，但未指定 LangGraph 实现原语。当前代码已实现单 Agent StateGraph（classify_intent → 3-route），记忆系统（Neo4j + Milvus）完整落地。本文档在现有基础上重新设计多 Agent 架构：

- **同一进程内**，使用 LangGraph 原语（StateGraph、Send、interrupt、checkpoint）
- **不依赖** `langchain.agents.create_agent()` 和 langchain middleware
- **核心 ReAct 循环手写**，框架只负责 State + Checkpoint + Send + interrupt
- 与现有代码风格一致：纯 Python 函数节点 + OpenAI SDK 直调

## 设计决策汇总

| 决策 | 选择 | 原因 |
|------|------|------|
| 编排模式 | Supervisor + Send API 动态 Fan-out | LangGraph 原生多 Agent 模式，Worker 并行执行，state 隔离 |
| 协作粒度 | 完全动态路由（Supervisor 唯一入口） | 去掉意图分类节点，LLM 决策何时拆、拆几个、谁来执行 |
| Agent 通信 | Shared State + Reducer 隐式聚合 | Worker 写 state → reducer 合并；不直接通信 |
| ReAct 循环 | 手写 agent_node + tools_node + check_continue | 减少框架依赖，每一步透明可控 |
| HITL | `interrupt()` + `Command(resume=...)` | LangGraph 原生中断恢复语义 |
| 记忆传递 | Supervisor 检索全量，按 Worker 类型裁剪注入 | 硬约束始终全量，裁剪纯 Python 逻辑不调 LLM |
| 记忆回写 | Worker 轻量提取 → Synthesizer 消重 → 统一写入 | Supervisor 单点写入避免并发冲突 |
| 框架依赖 | 仅 LangGraph StateGraph + Send + checkpoint + interrupt | 移除 langchain 的 create_agent 和 middleware |

## 图拓扑

```
                            START
                              │
                     ┌────────────────┐
                     │  supervisor_node │
                     │                  │
                     │ 1. 检索记忆(全量)  │
                     │ 2. LLM 决策拆解   │
                     │ 3. 按需裁剪记忆   │
                     │ 4. 写入 sub_tasks │
                     └────────┬─────────┘
                              │
                    route_to_workers
                  (conditional edge → Send[])
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
    ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
    │worker_rest   │ │worker_vou    │ │worker_chat   │
    │(编译子图)     │ │(编译子图)     │ │(编译子图)     │
    │              │ │              │ │              │
    │ tools:       │ │ tools:       │ │ tools:       │
    │ search_shops │ │ query_voucher│ │ memory_tools │
    │ bookmark_*   │ │ place_order  │ │              │
    │ reservation  │ │ check_orders │ │              │
    │              │ │ refund/alert │ │              │
    └──────┬───────┘ └──────┬───────┘ └──────┬───────┘
           │                │                │
           │ 返回:           │ 返回:           │ 返回:
           │ messages        │ messages        │ messages
           │ worker_result   │ worker_result   │ worker_result
           │ candidate_deltas│ candidate_deltas│ candidate_deltas
           │                │                │
           └────────────────┼────────────────┘
                            ▼
                   ┌────────────────┐
                   │synthesizer_node │
                   │                  │
                   │ 1. 汇总结果       │
                   │ 2. 消重 deltas    │
                   │ 3. LLM 合成回复   │
                   │ 4. 触发记忆回写   │
                   └────────┬─────────┘
                           END
```

### 执行时序

- **并行 (parallel)**：`route_to_workers` 返回 N 个 `Send()` → N 个 Worker 同时启动 → 全部完成后进入 synthesizer
- **串行 (sequential)**：返回 1 个 `Send()` → Worker 完成后回到 supervisor → supervisor 根据最新 state 决定是否继续 → 循环
- 默认 parallel。sequential 仅用于请求包含多个 HITL 操作（如预约+下单）的场景

## State Schema

```python
from typing import Annotated, TypedDict
from langgraph.graph import add_messages


class SubTask(TypedDict):
    worker_id: str           # "worker_restaurant" | "worker_voucher" | "worker_chat"
    task: str                # 自然语言任务描述
    priority: int            # 1=高, 2=中, 3=低
    memory_ctx: str          # Supervisor 裁剪的记忆上下文
    context: dict            # 额外结构化参数


class WorkerResult(TypedDict):
    worker_id: str
    status: str              # "success" | "failed" | "cancelled"
    summary: str             # 简短摘要
    artifacts: list[dict]    # 结构化产物 (shop_card, voucher 等)
    error: dict | None       # 失败时的错误信息 {type, message}


class CandidateDelta(TypedDict):
    op: str                  # ADD | REVISE | DELETE | REINFORCE
    target_type: str         # CuisinePreference | BudgetPreference | ...
    new_value: dict
    evidence: str            # 对话中的原始证据
    confidence: float
    source_worker: str


def merge_lists(left: list, right: list) -> list:
    """通用列表合并 reducer。"""
    return (left or []) + (right or [])


class PickAgentState(TypedDict):
    # ── 对话层 ──
    messages: Annotated[list, add_messages]

    # ── 编排层 ──
    sub_tasks: list[SubTask]                                # Supervisor 写入
    strategy: str                                           # "parallel" | "sequential"，Supervisor 写入
    current_step: int                                       # sequential 模式的当前执行步数
    worker_results: Annotated[list[WorkerResult], merge_lists]  # Worker 回写
    candidate_deltas: Annotated[list[CandidateDelta], merge_lists]  # Worker 回写

    # ── 输出层 ──
    final_response: str                                     # Synthesizer 写入
```

## Worker 子图：手写 ReAct 循环

每个 Worker 是独立编译的 StateGraph。三个 Worker 共享相同的循环结构，差异仅在 tools、system prompt、HITL 触发条件。

### Worker State

```python
class WorkerState(TypedDict):
    worker_task: dict          # Send 传入的子任务
    memory_context: str        # Supervisor 裁剪的记忆文本
    messages: Annotated[list, add_messages]
    tool_rounds: int
    worker_result: dict
    candidate_deltas: list[dict]
```

### ReAct 循环拓扑

```
START → agent_node → check_continue ──→ "tools" → tools_node → agent_node (循环)
                          │
                          └──→ "extract_deltas" → extract_deltas_node → END
```

### 节点函数

**agent_node** — 调 LLM，返回 AI message（可能含 tool_calls）：

```python
def _agent_node(state: WorkerState) -> dict:
    messages = [
        {"role": "system", "content": _build_worker_system_prompt(
            state["worker_task"], state.get("memory_context", "")
        )}
    ] + state.get("messages", [])

    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=messages,
        tools=WORKER_TOOLS,
        tool_choice="auto",
    )

    msg = response.choices[0].message
    ai_dict = {"role": "assistant", "content": msg.content or ""}
    if msg.tool_calls:
        ai_dict["tool_calls"] = [
            {"id": tc.id, "type": "function",
             "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in msg.tool_calls
        ]

    return {"messages": [ai_dict], "tool_rounds": state.get("tool_rounds", 0) + 1}
```

**check_continue** — 判断是否继续工具循环（纯逻辑，不调 LLM）：

```python
def _check_continue(state: WorkerState) -> str:
    if state.get("tool_rounds", 0) >= MAX_TOOL_ROUNDS:
        return "extract_deltas"
    last_msg = state["messages"][-1] if state.get("messages") else {}
    return "tools" if last_msg.get("tool_calls") else "extract_deltas"
```

**tools_node** — 执行工具调用，支持 HITL 中断：

```python
HITL_TOOLS = {"place_order", "request_refund", "make_reservation"}

def _tools_node(state: WorkerState) -> dict:
    last_msg = state["messages"][-1]
    tool_calls = last_msg.get("tool_calls", [])
    tool_messages = []

    for tc in tool_calls:
        fn_name = tc["function"]["name"]
        fn_args = json.loads(tc["function"]["arguments"])

        if fn_name in HITL_TOOLS:
            approved = interrupt({
                "type": "confirm",
                "tool": fn_name,
                "params": fn_args,
                "message": HITL_MESSAGES[fn_name].format(**fn_args),
            })
            if not approved:
                tool_messages.append({
                    "role": "tool", "tool_call_id": tc["id"],
                    "content": json.dumps({"status": "cancelled", "message": "用户取消"})
                })
                continue

        result = TOOL_EXECUTORS[fn_name](**fn_args)
        tool_messages.append({
            "role": "tool", "tool_call_id": tc["id"],
            "content": json.dumps(result) if isinstance(result, dict) else str(result),
        })

    return {"messages": tool_messages}
```

**extract_deltas_node** — 小模型从对话中提取候选记忆变更：

```python
def _extract_deltas_node(state: WorkerState) -> dict:
    user_msgs = [m for m in state["messages"] if m.get("role") == "user"]
    if not user_msgs:
        return _build_empty_output(state)

    conversation = format_conversation(state["messages"])
    try:
        response = get_extractor_client().chat.completions.create(
            model=EXTRACTOR_MODEL,
            messages=[
                {"role": "system", "content": MEMORY_EXTRACTION_PROMPT},
                {"role": "user", "content": f"分析对话提取用户偏好：\n\n{conversation}"},
            ],
            response_format={"type": "json_object"},
        )
        deltas = parse_deltas(response.choices[0].message.content)
    except Exception:
        logger.exception("Delta extraction failed")
        deltas = []

    return _build_empty_output(state, deltas)
```

### Worker 构建工厂

```python
def create_worker(
    name: str,
    system_prompt: str,
    tool_schemas: list[dict],
    tool_executors: dict[str, Callable],
    *,
    hitl_tools: set[str] | None = None,
    max_rounds: int = 8,
    extract_deltas: bool = True,
) -> "CompiledStateGraph":
    """通用 Worker 子图工厂。"""
    builder = StateGraph(WorkerState)

    # 当 extract_deltas=False 时，extract_deltas 节点仍存在但只输出空结果
    extract_node = _extract_deltas_node if extract_deltas else _build_empty_output

    builder.add_node("agent", _agent_node)
    builder.add_node("tools", _tools_node)
    builder.add_node("extract_deltas", extract_node)

    builder.add_edge(START, "agent")
    builder.add_conditional_edges(
        "agent", _check_continue,
        {"tools": "tools", "extract_deltas": "extract_deltas"},
    )
    builder.add_edge("tools", "agent")
    builder.add_edge("extract_deltas", END)  # ← 提取完成后结束子图

    return builder.compile()


def _build_empty_output(state: WorkerState, deltas: list | None = None) -> dict:
    """Worker 无提取需求时直接构建空输出（如 worker_chat）。"""
    last_assistant = ""
    for m in reversed(state.get("messages", [])):
        if m.get("role") == "assistant" and m.get("content"):
            last_assistant = m["content"][:200]
            break
    return {
        "worker_result": {
            "worker_id": state["worker_task"].get("worker_id", "unknown"),
            "status": "success",
            "summary": last_assistant,
            "artifacts": [],
            "error": None,
        },
        "candidate_deltas": [],
    }
```

### 三个 Worker 差异

| | worker_restaurant | worker_voucher | worker_chat |
|---|---|---|---|
| Tools | search_shops, bookmark_*, reservation | query_vouchers, place_order, check_orders, refund, alert | memory_tools |
| HITL | make_reservation | place_order, request_refund | 无 |
| extract_deltas | ✅ | ✅ | ❌ |
| max_rounds | 8 | 6 | 3 |

## 通信协议：Worker 输入/输出

Worker 之间不直接通信。通信通过 state 的读写实现。

### 输入：SubTask

```json
{
    "worker_id": "worker_restaurant",
    "task": "推荐春熙路人气火锅，人均100以内",
    "priority": 1,
    "memory_ctx": "### 相关偏好\n- [菜系] 川渝火锅 (置信度:0.85)\n- [预算] 人均50-100 (置信度:0.9)\n### 硬约束\n- [饮食] 不吃辣 (置信度:1.0)\n- [饮食] 清真 (置信度:1.0)",
    "context": {}
}
```

### 输出：WorkerResult + CandidateDelta

```json
{
    "worker_result": {
        "worker_id": "worker_restaurant",
        "status": "success",
        "summary": "推荐蜀大侠火锅，评分4.8，人均80，春熙路",
        "artifacts": [{"shop_id": 1, "name": "蜀大侠火锅", ...}],
        "error": null
    },
    "candidate_deltas": [
        {
            "op": "ADD",
            "target_type": "CuisinePreference",
            "new_value": {"cuisine": "川渝火锅"},
            "evidence": "用户说'我就喜欢吃重庆火锅'",
            "confidence": 0.7,
            "source_worker": "worker_restaurant"
        }
    ]
}
```

### 合并规则

- `messages`：`add_messages` reducer 自动追加
- `worker_results`：`merge_lists` reducer 拼接所有 Worker 结果
- `candidate_deltas`：`merge_lists` reducer 拼接，再由 Synthesizer 消重

## Supervisor 节点

Supervisor 只做一次 LLM 调用，其余为纯 Python。

### 处理流程

```
Step 1: 判断是否复合请求 (纯逻辑)
  └─ 简单请求 → 规则路由生成单个 sub_task，跳过 LLM

Step 2: LLM 决策 (仅复合请求)
  └─ 输入: 用户请求 + 可用 Worker 列表 + 检索到的记忆
  └─ 输出: {decomposition: [...], strategy: "parallel"|"sequential", reasoning: "..."}

Step 3: 记忆裁剪 (纯逻辑)
  └─ 根据 Worker 类型过滤 profiles → 格式化为 memory_ctx → 写入每个 sub_task
```

### 记忆裁剪映射

```python
WORKER_MEMORY_FIELDS = {
    "worker_restaurant": [
        "CuisinePreference", "TastePreference", "BudgetPreference",
        "DietaryPreference", "AreaPreference", "ScenePreference"
    ],
    "worker_voucher": [
        "BudgetPreference", "ConstraintPreference"
    ],
    "worker_chat": ["__ALL__"],
}

HARD_CONSTRAINT_TYPES = {"DietaryPreference", "ConstraintPreference"}

def trim_memory_for_worker(profiles: list, worker_id: str) -> str:
    """裁剪原则：硬约束始终全量注入所有 Worker，软偏好按 Worker 类型过滤。"""
    hards = [p for p in profiles if p.type_name in HARD_CONSTRAINT_TYPES]
    allowed = WORKER_MEMORY_FIELDS.get(worker_id, [])
    if "__ALL__" in allowed:
        softs = [p for p in profiles if p.type_name not in HARD_CONSTRAINT_TYPES]
    else:
        softs = [p for p in profiles if p.type_name in allowed]
    return format_profiles_as_prompt(hards + softs)
```

### 降级

LLM 决策失败（JSON 解析失败、超时）→ 降级为规则路由：

```python
def _rule_based_routing(query: str) -> list[SubTask]:
    """纯关键词匹配，回退到当前意图分类模式。"""
    if any(kw in query for kw in ["买", "下单", "券", "订单"]):
        worker = "worker_voucher"
    elif any(kw in query for kw in ["推荐", "找", "搜索", "附近"]):
        worker = "worker_restaurant"
    else:
        worker = "worker_chat"
    return [{"worker_id": worker, "task": query, "priority": 1, "memory_ctx": "", "context": {}}]
```

## route_to_workers：编排执行层

纯 Python 函数，将 `sub_tasks` 映射为 `Send()`。

```python
WORKER_NODE_MAP = {
    "worker_restaurant": "worker_restaurant",
    "worker_voucher":   "worker_voucher",
    "worker_chat":      "worker_chat",
}

def route_to_workers(state: PickAgentState) -> list[Send]:
    sub_tasks = state.get("sub_tasks", [])
    if not sub_tasks:
        return [Send("worker_chat", {"worker_task": {...}, "memory_context": ""})]

    strategy = state.get("strategy", "parallel")

    if strategy == "sequential":
        current_step = state.get("current_step", 0)
        if current_step >= len(sub_tasks):
            return []
        task = sub_tasks[current_step]
        return [Send(WORKER_NODE_MAP[task["worker_id"]], {
            "worker_task": task,
            "memory_context": task.get("memory_ctx", ""),
        })]

    # parallel: 所有子任务一次性 Send
    return [Send(WORKER_NODE_MAP[t["worker_id"]], {
        "worker_task": t,
        "memory_context": t.get("memory_ctx", ""),
    }) for t in sub_tasks]
```

**LangGraph 语义**：返回 N 个 Send → N 个 Worker 同时启动 → 全部完成后进入 synthesizer。

### 主图组装

```python
def create_pick_agent(checkpointer=None, ...) -> "CompiledStateGraph":
    """构建 Supervisor + Worker 协作图。"""
    builder = StateGraph(PickAgentState)

    # Worker 子图（编译一次，运行时复用）
    worker_restaurant = create_worker_restaurant()
    worker_voucher   = create_worker_voucher()
    worker_chat      = create_worker_chat()

    # 主图节点
    builder.add_node("supervisor", supervisor_node)
    builder.add_node("synthesizer", synthesizer_node)
    builder.add_node("worker_restaurant", worker_restaurant)
    builder.add_node("worker_voucher",   worker_voucher)
    builder.add_node("worker_chat",      worker_chat)

    # 边
    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges(
        "supervisor",
        route_to_workers,
        ["worker_restaurant", "worker_voucher", "worker_chat"],
    )
    for name in ("worker_restaurant", "worker_voucher", "worker_chat"):
        builder.add_edge(name, "synthesizer")
    builder.add_edge("synthesizer", END)

    return builder.compile(checkpointer=checkpointer)
```

## Synthesizer：汇总 + 消重 + 合成

### 处理流程

```
Step 1: 消重 & 冲突解决 (纯逻辑)
  └─ 同值去重 → 矛盾冲突判定 → 与已有 Profile 对比
  └─ 输出: resolved_deltas

Step 2: 合成最终回复 (调 LLM)
  └─ 输入: 用户请求 + 所有 worker_results
  └─ 输出: 自然语言回复

Step 3: 写入 state + 触发记忆回写
```

### 消重逻辑

```python
def dedup_and_resolve(
    deltas: list[dict],
    existing_profiles: dict,
) -> list[dict]:
    """纯逻辑消重。"""
    seen = {}
    for d in deltas:
        key = (d["target_type"], canonicalize(d["new_value"]))
        if key in seen:
            if d["confidence"] > seen[key]["confidence"]:
                seen[key] = d
        else:
            seen[key] = d

    resolved = []
    for d in seen.values():
        existing = existing_profiles.get(d["target_type"])
        if existing and is_contradict(d, existing):
            if d["confidence"] > existing.confidence + 0.2:
                d["op"] = "REVISE"
                d["target_id"] = existing.id
            else:
                continue  # 新证据不够强，丢弃
        resolved.append(d)

    return resolved
```

### 降级

LLM 合成失败 → 简单字符串拼接：

```python
def _concat_results(worker_results: list) -> str:
    parts = []
    for r in worker_results:
        if r["status"] == "success":
            parts.append(r["summary"])
        else:
            parts.append(f"{r['worker_id']} 查询失败")
    return "\n".join(parts) if parts else "抱歉，所有查询均失败，请稍后再试"
```

## HITL：多 Worker 中断处理

### 边界场景

| 场景 | 处理 |
|------|------|
| Worker A 完成，Worker B 中断，用户取消 | Synthesizer 读到两个结果：success + cancelled → 只合成已完成的，告知用户哪部分取消。取消的 Worker 的 deltas 丢弃 |
| 两个 Worker 同时触发 interrupt | 禁止此场景。Supervisor 检测到多个 HITL 操作时，拆为 sequential |
| interrupt 丢失（checkpoint 损坏） | `/chat/resume` 检测到无 interrupt → 返回错误："会话已过期，请重新发送请求" |
| 取消后的 Worker 状态 | `status: "cancelled"`，Synthesizer 区分"失败"和"取消" |

### 前端中断事件

```json
{
    "type": "confirm",
    "tool": "place_order",
    "params": {"voucher_id": 88, "quantity": 1, "shop_name": "蜀大侠火锅"},
    "message": "确认下单？蜀大侠火锅 88抵100券 x1，金额 ¥88"
}
```

### 恢复端点

```python
@app.post("/chat/resume")
async def chat_resume(request: ChatRequest, agent=Depends(get_agent)):
    config = {"configurable": {"thread_id": request.session_id}}
    state = agent.get_state(config)

    if not state or not state.tasks:
        return error("会话已过期")

    interrupts = state.tasks[0].interrupts
    if not interrupts:
        # 无中断 → 普通对话恢复
        return stream_normal(request, agent, config)

    confirmed = _parse_confirmation(request.query)
    command = Command(resume=confirmed)
    return StreamingResponse(
        stream_agent_response(query=request.query, history=[], agent=agent,
                              config=config, command=command),
        media_type="text/event-stream",
    )
```

## 错误处理 & 降级

### 三级降级

```
L1 (Supervisor LLM 挂了):
  RuleRouter → N×Worker(ReAct) → Synthesizer(LLM) → Delta写入

L2 (Synthesizer LLM 也挂了):
  RuleRouter → N×Worker(ReAct) → SimpleConcat → Delta写入

L3 (Worker LLM 也挂了):
  Worker 返回 status="failed" + 错误描述 → Synthesizer 告知用户

L4 (全挂):
  "服务暂时不可用，请稍后再试"
```

### 关键原则

| 原则 | 说明 |
|------|------|
| 局部失败不扩散 | 一个 Worker 失败不影响其他 Worker |
| 降级时协议一致 | 失败的 Worker 仍返回标准格式（status="failed"） |
| 记忆提取保守 | 任何失败都不提取记忆，宁可漏写也不错写 |
| 日志完整 | 每种降级路径有明确 warn/error 日志 |

### 重试策略

| 失败类型 | 重试 | 策略 |
|---------|------|------|
| LLM RateLimitError | 3 次 | 指数退避 1s/2s/4s |
| LLM APITimeoutError | 3 次 | 指数退避 |
| 工具 MilvusTimeoutError | 0 次 | 直接返回错误给 LLM，让 LLM 决定降级 |
| 工具 JavaBackendError | 1 次 | 2s 后退 |
| JSON 解析失败 | 0 次 | 直接降级，不重试 |
| 其他异常 | 0 次 | 标记失败，不重试 |

## 文件结构

```
agent-service/src/agent/
├── agent.py              ← 主图 (create_pick_agent)
├── supervisor.py         ← supervisor_node + route_to_workers + 记忆裁剪
├── synthesizer.py        ← synthesizer_node + 消重逻辑
├── state.py              ← PickAgentState + SubTask + WorkerResult + CandidateDelta
├── workers/
│   ├── __init__.py
│   ├── base.py           ← create_worker() 工厂 + WorkerState
│   ├── restaurant.py     ← create_worker_restaurant() → 注入 restaurant tools
│   ├── voucher.py        ← create_worker_voucher() → 注入 voucher tools
│   └── chat.py           ← create_worker_chat() → 注入 memory tools
├── tools/                ← 现有工具目录，逐步改为纯函数 + JSON Schema
│   ├── schemas.py         ← 工具的 OpenAI function-calling JSON Schema（新增）
│   └── ...
├── config.py
├── prompts/
├── middleware/            ← 最终移除（不再依赖 langchain middleware）
├── stream/
└── services/
```

## 迁移路径

### 阶段 1：提取 Worker 子图

- 目标：三个 `create_agent()` 替换为手写 ReAct 子图
- 范围：新增 `workers/` 包，修改 `agent.py` 的 handler 创建逻辑
- 图结构不变：保持 classify_intent → 3-route
- 验证：现有 API 测试全部通过，SSE 流格式不变

### 阶段 2：引入 Supervisor 编排

- 目标：主图改为 Supervisor → Send → Synthesizer
- 范围：新增 `supervisor.py`、`synthesizer.py`、`state.py`
- 单 Worker 场景等价于阶段 1
- 复合请求激活并行 Fan-out
- 验证：单 Worker 场景行为一致 + 复合请求端到端测试

### 阶段 3：记忆裁剪 + Delta 汇入

- 目标：Supervisor 检索全量记忆并按需裁剪；Worker 轻量提取 delta → Synthesizer 消重写入
- 范围：`supervisor_node` 增加记忆检索/裁剪；`synthesizer_node` 增加消重/写入
- 与现有 MemoryPipeline 共存：重提取走 extract_deltas_node，完整提取仍走异步 MemoryPipeline

### 阶段 4：清理旧代码

- 移除：`classify_intent` 节点、`route_by_intent`、旧 system prompt 常量、`SHARED_MIDDLEWARE`/`PURCHASE_MIDDLEWARE`、langchain 的 `create_agent`/middleware 引用
- 保留：所有工具函数、`stream/sse.py`、`main.py` 端点、整个记忆系统、Java 客户端

## 与现有代码的兼容

| 组件 | 兼容策略 |
|------|---------|
| PostgresSaver checkpoint | messages 结构不变，state 新增字段有默认值，向前兼容 |
| SSE 流格式 | `astream_events` v3 不变，event type 不变 |
| `/chat` + `/chat/resume` 端点 | 签名不变，内部逻辑适配 |
| 记忆系统 (Neo4j/Milvus) | 读写接口不变，新增 Worker 级提取作为补充路径 |
| 工具函数 | 接口不变，补充 JSON Schema 定义 |
| Java 客户端 | 不变 |

## 关键约束

- Python 3.11+，LangGraph >= 1.2.2
- 所有节点函数返回 dict（LangGraph StateGraph 约定）
- checkpoint 中存储的所有数据必须 JSON 可序列化
- OpenAI SDK 直调（`client.chat.completions.create`），不经过 langchain 的 BaseChatModel
- `interrupt()` 只在 `tools_node` 中调用（不在 `agent_node` 中）
