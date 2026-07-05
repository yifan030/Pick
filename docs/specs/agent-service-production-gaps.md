# Agent-Service 生产化缺口规格

> 基于 2026-07-05 全量代码审查，对照已有实现与健壮 Agent 服务所需能力的差距分析。
> 每项缺口含优先级、现状、目标、建议方案和验收标准。

---

## 目录

1. [P0 — Guardrails / 安全护栏](#p0--guardrails-安全护栏)
2. [P0 — Observability / 可观测性](#p0--observability-可观测性)
3. [P0 — 模型降级 + 熔断 + 超时](#p0--模型降级--熔断--超时)
4. [P1 — Memory Tools 接入 Worker](#p1--memory-tools-接入-worker)
5. [P1 — 会话内记忆可见性](#p1--会话内记忆可见性)
6. [P1 — 网关层速率限制 / 滥用防护](#p1--网关层速率限制--滥用防护)
7. [P1 — 会话生命周期管理](#p1--会话生命周期管理)
8. [P2 — 多轮对话状态追踪](#p2--多轮对话状态追踪)
9. [P2 — Prompt 版本管理](#p2--prompt-版本管理)
10. [P2 — 检索结果缓存](#p2--检索结果缓存)
11. [P2 — 结构化输出验证](#p2--结构化输出验证)
12. [P2 — Health Check 细粒度化](#p2--health-check-细粒度化)
13. [P3 — 地理空间搜索](#p3--地理空间搜索)
14. [P3 — 多模态支持](#p3--多模态支持)
15. [P3 — 成本追踪](#p3--成本追踪)
16. [P3 — SessionSummarizer 缓存治理](#p3--sessionsummarizer-缓存治理)
17. [P3 — Graceful Shutdown](#p3--graceful-shutdown)
18. [P3 — 集成测试补齐](#p3--集成测试补齐)

---

## P0 — Guardrails / 安全护栏

### 现状

旧 `src/agent/middleware/safety.py` 已在 agent team 重设计时删除，未替换。
当前 agent 能调用 `place_order`、`request_refund` 等敏感工具，但没有任何安全边界：

- 无输入内容审核（越狱、提示注入）
- 无输出内容审核（有害内容、幻觉编造）
- 无 PII 检测与脱敏
- 无敏感操作二次确认的强制机制（`interrupt()` 存在但依赖 LLM 自觉调用工具）
- 工具调用无权限校验（user_id 伪造、跨用户 voucher_id）

### 目标

在每个请求的入口和出口建立安全护栏，确保：
1. 恶意/越狱输入被拦截在 Supervisor 之前
2. 敏感输出（PII、有害内容）在 Synthesizer 之后被过滤
3. 敏感工具调用有不可绕过的确认路径
4. 工具参数经过权限校验

### 建议方案

#### 1. 输入护栏节点 (`GuardrailsNode`)

在 `supervisor` 之前插入一个轻量检查节点：

```
START → guardrails → supervisor → ...
```

```python
# 新文件: src/agent/guardrails.py
class GuardrailsNode:
    """Pre-supervisor safety check."""
    
    REJECT_PATTERNS = [...]  # 已知越狱模式
    MAX_QUERY_LENGTH = 4000
    
    def check(self, state: PickAgentState) -> dict:
        query = self._extract_query(state)
        
        # 1. 长度检查
        if len(query) > self.MAX_QUERY_LENGTH:
            return {"blocked": True, "block_reason": "query_too_long"}
        
        # 2. 模式匹配（已知越狱/注入）
        if self._matches_reject_pattern(query):
            return {"blocked": True, "block_reason": "blocked_pattern"}
        
        # 3. 轻量 LLM 分类器（可选，高流量时用规则优先）
        # verdict = await self._llm_check(query)
        
        return {"blocked": False}
```

#### 2. 输出护栏

在 `synthesizer` 之后或 SSE 流中检查：

- PII 正则脱敏（手机号/身份证/银行卡号）
- 有害内容关键词过滤
- 工具调用结果中的敏感字段裁剪

#### 3. 工具权限校验

在 `tools_node` 中，HITL 工具执行前增加权限检查：

```python
def _check_tool_permission(fn_name: str, fn_args: dict, user_id: str) -> bool:
    """验证当前用户是否有权执行此工具调用。"""
    if fn_name == "place_order":
        # 确保 order 的 user_id 匹配请求 user_id
        ...
    if fn_name == "request_refund":
        # 确保 order 属于当前用户
        ...
```

### 文件变更

| Action | Path | Purpose |
|--------|------|---------|
| CREATE | `src/agent/guardrails.py` | 输入/输出护栏节点 |
| CREATE | `src/agent/guardrails/pii_patterns.py` | PII 检测正则库 |
| MODIFY | `src/agent/agent.py` | 在 graph 中插入 guardrails 节点 |
| MODIFY | `src/agent/workers/base.py` | 工具调用前增加权限校验 |

### 验收标准

- [ ] 已知越狱 prompt 被拦截，返回通用错误消息
- [ ] 手机号/身份证号在输出中被 `***` 替换
- [ ] `place_order` 无法用其他用户的 user_id 下单
- [ ] 输入护栏延迟 < 5ms（纯规则模式）
- [ ] 添加 `tests/agent/test_guardrails.py`

---

## P0 — Observability / 可观测性

### 现状

旧 `src/agent/middleware/logging.py` 已删除。当前只有裸 `logging.getLogger()`：

- 无分布式追踪，trace 不贯穿 supervisor → workers → tools
- 无 request-level trace_id
- 无 LLM 调用指标（token、延迟、模型）
- 无工具调用指标（成功率、延迟分布）
- 无记忆流水线指标
- 无 Dashboard 或告警集成

### 目标

建立端到端的可观测性，使每个请求的生命周期可追踪、每个组件的性能可度量。

### 建议方案

#### 1. Trace ID 贯穿

从 `session_id` 派生 trace_id，注入到所有日志和 span：

```python
# 新文件: src/observability/tracing.py
import contextvars

_trace_id: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id")

def set_trace_id(session_id: str) -> str:
    tid = f"trace_{session_id}"
    _trace_id.set(tid)
    return tid

def get_trace_id() -> str:
    return _trace_id.get("-")
```

#### 2. OpenTelemetry 集成

在每个关键节点创建 span：

```
POST /chat (root span)
├── guardrails.check               [span: ~1ms]
├── retrieval.retrieve              [span: ~200ms]
│   ├── semantic_search.search      [span]
│   ├── bm25_search.search          [span]
│   └── entity_boost.search         [span]
├── supervisor.classify             [span: ~500ms]
├── worker_restaurant.react         [span: ~2s]
│   ├── llm.call (round 1)          [span: token, model, latency]
│   ├── tool.search_shops           [span: latency, status]
│   ├── llm.call (round 2)          [span]
│   └── extract_deltas              [span]
├── worker_voucher.react            [span]
├── synthesizer.synthesize          [span: ~1s]
└── memory_pipeline.extract          [span: ~2s, background]
```

#### 3. 关键指标 (Metrics)

```python
# LLM 调用
llm_call_total{model, node}              # Counter
llm_call_duration_seconds{model, node}   # Histogram
llm_token_usage_total{model, type}       # Counter (prompt/completion)

# 工具调用
tool_call_total{tool, status}            # Counter (success/error)
tool_call_duration_seconds{tool}         # Histogram

# 记忆流水线
memory_events_extracted_total            # Counter
memory_deltas_applied_total{op}          # Counter

# 请求
request_duration_seconds                 # Histogram
request_total{status}                    # Counter (success/error/blocked)
```

### 文件变更

| Action | Path | Purpose |
|--------|------|---------|
| CREATE | `src/observability/__init__.py` | Package init |
| CREATE | `src/observability/tracing.py` | Trace ID + OpenTelemetry 初始化 |
| CREATE | `src/observability/metrics.py` | Metrics 定义和导出 |
| CREATE | `src/observability/middleware.py` | FastAPI middleware：trace_id 注入 + 请求计时 |
| MODIFY | `src/agent/workers/base.py` | LLM 调用处添加 span |
| MODIFY | `src/agent/agent.py` | 各节点添加 span |
| MODIFY | `src/retrieval/gateway.py` | 检索各通道添加 span |
| MODIFY | `src/memory/pipeline.py` | 各提取步骤添加 span |
| MODIFY | `src/main.py` | 注册 middleware |

### 验收标准

- [ ] 每条日志自动携带 trace_id
- [ ] OpenTelemetry exporter 可配置（console / OTLP / none）
- [ ] Grafana Dashboard JSON 模板（至少含 LLM 延迟 + 工具成功率 + 请求 QPS）
- [ ] 请求级别 P50/P95/P99 延迟可查询
- [ ] 添加 `tests/observability/` 验证 trace_id 传播

---

## P0 — 模型降级 + 熔断 + 超时

### 现状

- 所有 LLM 调用使用同一模型（`LLM_MODEL`），无降级路径
- 外部依赖（Milvus、Neo4j）无熔断，失败即抛异常
- 工具调用无超时，一个 hung 工具永久阻塞 worker

### 目标

任何单一组件故障不应导致整个请求失败。系统应自动降级并继续提供降级服务。

### 建议方案

#### 1. LLM 调用：重试 + 模型降级链

```python
# 新文件: src/agent/llm/resilience.py
from tenacity import retry, stop_after_attempt, wait_exponential

LLM_FALLBACK_CHAIN = [
    {"model": "gpt-4o", "base_url": "...", "api_key": "..."},       # 主模型
    {"model": "gpt-4o-mini", "base_url": "...", "api_key": "..."},   # 降级 1
    {"model": "qwen-turbo", "base_url": "...", "api_key": "..."},    # 降级 2
]

async def call_llm_with_fallback(messages, tools=None, max_retries=2):
    for tier, config in enumerate(LLM_FALLBACK_CHAIN):
        try:
            client = OpenAI(base_url=config["base_url"], api_key=config["api_key"])
            return await client.chat.completions.create(
                model=config["model"],
                messages=messages,
                tools=tools,
                timeout=30.0,  # 单次调用超时
            )
        except Exception:
            logger.warning("LLM tier %d (%s) failed", tier, config["model"])
            if tier == len(LLM_FALLBACK_CHAIN) - 1:
                raise
    # unreachable
```

#### 2. 外部依赖熔断

```python
# 新文件: src/agent/circuit_breaker.py
# 或复用现有 Java client 的 CircuitBreaker 模式
class CircuitBreaker:
    def __init__(self, name: str, failure_threshold: int = 5, cooldown_seconds: float = 30.0):
        ...
    
    async def call(self, fn, fallback=None):
        """执行 fn，熔断时返回 fallback() 结果"""
        ...
```

应用到：
- Milvus 连接（熔断 → 跳过语义搜索，仅用 BM25）
- Neo4j 连接（熔断 → 跳过实体增强，profile 为空）
- Java 后端（已实现，保持不变）

#### 3. 工具调用超时

在 `tools_node` 中对每个工具调用添加超时：

```python
import asyncio

async def _execute_with_timeout(fn, kwargs, timeout=15.0):
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(fn, **kwargs),  # 同步工具在线程中执行
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        return f"Error: tool execution timed out after {timeout}s"
```

### 文件变更

| Action | Path | Purpose |
|--------|------|---------|
| CREATE | `src/agent/llm/resilience.py` | LLM 重试 + 降级链 |
| CREATE | `src/agent/circuit_breaker.py` | 通用熔断器 |
| MODIFY | `src/agent/workers/base.py` | 工具调用超时 + LLM 降级 |
| MODIFY | `src/retrieval/gateway.py` | 各检索通道熔断包裹 |
| MODIFY | `src/memory/pipeline.py` | Neo4j/Milvus 操作熔断包裹 |

### 验收标准

- [ ] 主 LLM 不可用时自动降级到 fallback 模型
- [ ] Milvus 不可用时检索返回仅 BM25 结果
- [ ] 工具执行超时 > 15s 时返回 timeout 错误，worker 继续
- [ ] 熔断器在 5 次失败后打开，30s 后半开探活
- [ ] 降级事件记录到 metrics + logs

---

## P1 — Memory Tools 接入 Worker

### 现状

`create_memory_tools()` 定义了 5 个记忆管理工具，但：
- `CHAT_TOOL_NAMES = frozenset()` — chat worker 不暴露任何工具
- 系统提示中明确写了"用户可以通过对话自然管理自己的偏好记忆"
- **用户实际无法管理记忆**：没有任何 worker 注册这些工具

### 目标

用户可以通过自然语言管理自己的偏好记忆（查看/删除/修改/清除）。

### 建议方案

#### 方案 A：将 memory tools 加入 chat worker（推荐）

```python
# src/agent/tools/schemas.py
CHAT_TOOL_NAMES: frozenset[str] = frozenset({
    "view_my_preferences",
    "delete_preference",
    "update_preference",
    "clear_all_preferences",
    "temporary_ignore_preferences",
})
```

同时将 memory tools 注册到 `TOOL_SCHEMAS` 和 `TOOL_EXECUTORS`。

#### 方案 B：创建独立的 memory_tools worker

```python
# src/agent/workers/memory.py
def create_worker_memory():
    return create_worker(
        name="worker_memory",
        system_prompt=MEMORY_SYSTEM_PROMPT,
        tool_schemas=get_tool_schemas_for_worker(MEMORY_TOOL_NAMES),
        tool_executors=get_tool_executors_for_worker(MEMORY_TOOL_NAMES),
        hitl_tools=frozenset({"clear_all_preferences"}),
        max_rounds=3,
        extract_deltas=False,
    )
```

然后在 supervisor 中增加路由：记忆管理意图 → `worker_memory`。

### 推荐

方案 A（接入 chat worker），因为记忆管理通常是轻量操作，不需要独立 worker。

### 文件变更

| Action | Path | Purpose |
|--------|------|---------|
| MODIFY | `src/agent/tools/schemas.py` | 将 memory tools 注册到 schemas/executors；更新 CHAT_TOOL_NAMES |
| MODIFY | `src/agent/tools/memory_tools.py` | 确保工具签名兼容 OpenAI function-calling 格式 |

### 验收标准

- [ ] 用户说"你知道我什么偏好"时，agent 调用 `view_my_preferences` 并返回结果
- [ ] 用户说"忘掉我喜欢辣的"时，agent 调用 `delete_preference`
- [ ] 用户说"清除所有记忆"时，agent 确认后调用 `clear_all_preferences`
- [ ] `tests/agent/tools/test_memory_tools.py` 通过

---

## P1 — 会话内记忆可见性

### 现状

记忆更新发生在 SSE 流结束后（MemoryPipeline 后台任务）或 Worker 结束时（delta 提取），但：

- `memory_context` 仅在 `is_new_session=True` 时注入（`main.py:279`）
- **同一 session 的后续 turn 不会触发 retrieval**
- 用户在当前对话中表达的偏好（如"我喜欢辣的"）在当前 session 不会被用来调整推荐

```
Turn 1 (new session): retrieval → memory_context 注入 ✓
Turn 2 (same session): 无 retrieval → 上一轮提取的偏好不可见 ✗
Turn 3 (same session): 无 retrieval → 仍然不可见 ✗
```

### 目标

用户在**同一 session** 内表达的偏好应立即在后续 turn 中生效。

### 建议方案

#### 1. 每 turn 轻量 retrieval

在 supervisor 中为非首次 turn 也做检索（使用更轻量的策略）：

```python
# src/agent/supervisor.py
def supervisor_node(state, *, profiles=None, retrieval_gateway=None, ...):
    if retrieval_gateway and user_id:
        if is_new_session:
            result = await retrieval_gateway.retrieve(
                user_id=user_id, query=query, is_new_session=True
            )
        else:
            # 仅查 profiles（跳过语义/BM25 全量搜索）
            result = await retrieval_gateway.get_profiles_only(user_id)
```

#### 2. Worker Delta → State 实时注入

将 Worker 提取的 `candidate_deltas` 在 synthesizer 写 Neo4j 后**同时注入到当前 state 的 memory_context**：

```python
# src/agent/synthesizer.py
def synthesizer_node(state, ...):
    # 写入 Neo4j 后
    if resolved_deltas:
        # 将新提取的偏好转为 memory_context 追加到 state
        fresh_memory = _deltas_to_memory_context(resolved_deltas)
        state["memory_context"] = (state.get("memory_context") or "") + fresh_memory
```

### 文件变更

| Action | Path | Purpose |
|--------|------|---------|
| MODIFY | `src/agent/supervisor.py` | 非新 session 时做轻量 profile 查询 |
| MODIFY | `src/agent/synthesizer.py` | 新写的 delta 追加到 memory_context |
| MODIFY | `src/retrieval/gateway.py` | 添加 `get_profiles_only()` 轻量方法 |

### 验收标准

- [ ] Turn 1: 用户说"我喜欢川菜" → 记忆提取
- [ ] Turn 2: 用户说"推荐个餐厅" → 推荐结果偏好川菜
- [ ] 验证：检查 supervisor 拿到的 profiles 在 turn 2 包含新提取的 CuisinePreference

---

## P1 — 网关层速率限制 / 滥用防护

### 现状

Java 后端有 `redis-tool-framework` 做限流，但 agent-service 自身无任何速率限制。

### 目标

保护 agent-service 免于滥用（单个用户高频调用、恶意脚本）。

### 建议方案

FastAPI middleware，基于 Redis 的滑动窗口限流：

```python
# 新文件: src/api/rate_limiter.py
from fastapi import Request, HTTPException
import redis.asyncio as redis

class RateLimiter:
    def __init__(self, redis_client, max_requests=30, window_seconds=60):
        self._redis = redis_client
        self._max = max_requests
        self._window = window_seconds
    
    async def check(self, user_id: str) -> bool:
        key = f"ratelimit:chat:{user_id}"
        current = await self._redis.incr(key)
        if current == 1:
            await self._redis.expire(key, self._window)
        return current <= self._max

# 注册到 main.py
app.add_middleware(RateLimitMiddleware, redis=..., max_rpm=30)
```

### 文件变更

| Action | Path | Purpose |
|--------|------|---------|
| CREATE | `src/api/__init__.py` | Package init |
| CREATE | `src/api/rate_limiter.py` | Redis 滑动窗口限流 |
| CREATE | `src/api/middleware.py` | FastAPI middleware 注册 |
| MODIFY | `src/main.py` | 注册 middleware |

### 验收标准

- [ ] 同一 user_id 在 1 分钟内超过 30 次请求返回 429
- [ ] 不同 user_id 独立计数
- [ ] 限流器不可用时（Redis down）默认放行（fail-open）
- [ ] 添加 `tests/api/test_rate_limiter.py`

---

## P1 — 会话生命周期管理

### 现状

- `MemoryPipeline.finalize_session()` 定义了但**从未被调用**
- `SessionSummarizer._round_cache` 是进程内 `dict`，无 TTL，无上限，重启丢失
- 无 session 超时机制
- 无 session 清理策略

### 目标

会话有明确的生命周期：创建 → 活跃 → 超时/结束 → 归档 → 清理。

### 建议方案

#### 1. Session TTL

```python
# Postgres 中记录 session 最后活跃时间
# 定时任务扫描超时 session
SESSION_TTL_SECONDS = 30 * 60  # 30 分钟无活动 = 超时

async def expire_stale_sessions():
    """定时任务：超时 session → finalize → 标记过期"""
    ...
```

#### 2. 显式 session 结束

添加 `POST /chat/end` 端点：

```python
@app.post("/chat/end")
async def end_session(session_id: str, user_id: str):
    await _pipeline.finalize_session(user_id, session_id)
    _round_tracker.pop(session_id, None)
    return {"status": "ok"}
```

#### 3. SessionSummarizer 缓存上限

```python
# 添加 LRU 缓存 + TTL
from cachetools import TTLCache

class SessionSummarizer:
    def __init__(self, ...):
        self._round_cache = TTLCache(maxsize=10000, ttl=3600)  # 1h TTL
```

### 文件变更

| Action | Path | Purpose |
|--------|------|---------|
| CREATE | `src/session/__init__.py` | Package init |
| CREATE | `src/session/manager.py` | Session 生命周期管理 |
| CREATE | `src/session/cleanup_job.py` | 定时清理任务 |
| MODIFY | `src/main.py` | 添加 `/chat/end` 端点，注册清理任务 |
| MODIFY | `src/memory/session_summarizer.py` | 缓存改为 TTLCache |
| MODIFY | `src/memory/pipeline.py` | 确保 `finalize_session` 可被调用 |

### 验收标准

- [ ] 30 分钟无活动的 session 自动触发 `finalize_session`
- [ ] `POST /chat/end` 正确结束 session 并写 final summary
- [ ] SessionSummarizer 缓存不超过 10000 条
- [ ] 服务重启后旧 session 仍可通过 PostgresSaver 恢复

---

## P2 — 多轮对话状态追踪

### 现状

Supervisor 对每个 turn 独立分类。后续 turn 依赖 LLM 从 PostgresSaver 恢复的消息历史来理解上下文：
- "那第二家呢？" → LLM 从历史消息推断"第二家"指什么
- 无显式的对话状态机或 slot-filling
- 无跨 turn 的意图追踪

### 目标

对话状态被显式维护，支持指代消解、条件累积和多轮追问。

### 建议方案

在 `PickAgentState` 中增加 `active_context` 字段：

```python
class ActiveContext(TypedDict, total=False):
    """跨 turn 的活跃上下文，由 supervisor 提取和维护."""
    last_search_results: list[dict]     # 上一轮搜索结果（支持"第二家"指代）
    active_filters: dict                 # 当前累积的过滤条件
    pending_actions: list[str]           # 待完成的操作
    referred_entities: dict[str, str]    # 指代映射 {"第二家": shop_id_2}

class PickAgentState(TypedDict, total=False):
    ...
    active_context: dict  # ActiveContext
```

Supervisor 在每个 turn 更新 `active_context`：
- 提取搜索结果的 shop 列表 → `last_search_results`
- 累积过滤条件 → `active_filters`
- 解析指代 → `referred_entities`

### 文件变更

| Action | Path | Purpose |
|--------|------|---------|
| MODIFY | `src/agent/state.py` | 添加 ActiveContext 类型 |
| MODIFY | `src/agent/supervisor.py` | 每个 turn 更新 active_context |
| MODIFY | `src/agent/workers/base.py` | 将 active_context 注入 worker 的 system prompt |

### 验收标准

- [ ] "推荐春熙路附近的火锅" → "那第二家呢？" → 正确返回第 2 家店铺
- [ ] "人均 100 以内的" → "评分高一点的" → 两个条件叠加
- [ ] "帮我排个号" → 自动使用上一轮推荐的 shop_id

---

## P2 — Prompt 版本管理

### 现状

所有 system prompt 是硬编码的模块级常量：
- `RESTAURANT_SYSTEM_PROMPT`
- `VOUCHER_SYSTEM_PROMPT`
- `CHAT_SYSTEM_PROMPT`
- `DECOMPOSITION_PROMPT`
- `SYNTHESIS_PROMPT`
- `SYSTEM_PROMPT` / `SYSTEM_PROMPT_WITH_MEMORY`

无版本号，无回滚机制，无 A/B 测试支持。

### 目标

Prompt 可版本化、可回滚、可实验。

### 建议方案

#### 1. Prompt 注册表

```python
# 新文件: src/agent/prompts/registry.py
from dataclasses import dataclass
from typing import Optional

@dataclass
class PromptVersion:
    name: str
    version: str          # semver: "1.0.0"
    template: str
    variables: list[str]
    metadata: dict        # author, created_at, description

class PromptRegistry:
    _prompts: dict[str, dict[str, PromptVersion]]  # name → version → PromptVersion
    
    def get(self, name: str, version: Optional[str] = None) -> PromptVersion:
        ...
    
    def get_experiment(self, name: str, user_id: str) -> PromptVersion:
        """根据 user_id 哈希分配 A/B 变体"""
        ...
```

#### 2. YAML/JSON 配置文件

将 prompt 从 Python 模块移到配置文件：

```yaml
# prompts/restaurant_worker.yaml
name: restaurant_worker
versions:
  - version: "1.0.0"
    template: |
      You are a local lifestyle shopping guide...
    metadata:
      author: team
      created: "2026-07-01"
  - version: "1.1.0"
    template: |
      You are an expert Chengdu food guide...
    metadata:
      author: team
      created: "2026-07-10"
      changes: "Added more Chengdu-specific knowledge"
```

### 文件变更

| Action | Path | Purpose |
|--------|------|---------|
| CREATE | `src/agent/prompts/registry.py` | Prompt 注册表和版本管理 |
| CREATE | `prompts/` | YAML 配置文件目录 |
| CREATE | `prompts/restaurant_worker.yaml` | Restaurant worker prompts |
| CREATE | `prompts/voucher_worker.yaml` | Voucher worker prompts |
| CREATE | `prompts/chat_worker.yaml` | Chat worker prompts |
| CREATE | `prompts/supervisor.yaml` | Supervisor decomposition prompt |
| CREATE | `prompts/synthesizer.yaml` | Synthesizer prompt |
| MODIFY | `src/agent/prompts/system_prompt.py` | 改为从 registry 加载 |
| MODIFY | `src/agent/workers/restaurant.py` | 使用 registry |
| MODIFY | `src/agent/workers/voucher.py` | 使用 registry |
| MODIFY | `src/agent/workers/chat.py` | 使用 registry |

### 验收标准

- [ ] 修改 prompt 配置文件后无需重启即可生效（热加载）
- [ ] 可通过环境变量 `PROMPT_VERSION=1.1.0` 切换版本
- [ ] 可按 user_id 哈希做 A/B 分流
- [ ] Prompt 变更记录到 audit log

---

## P2 — 检索结果缓存

### 现状

`RetrievalGateway.retrieve()` 每个新 session 都完整执行：
- 1 次 embedding 调用（query embedding）
- 3 路 Milvus 搜索（语义 + BM25 + 跨 collection）
- 1 次 Neo4j 遍历

同一用户在短时间内多次创建 session（如刷新页面）会重复全部计算。

### 目标

对检索结果做短期缓存，减少重复计算和 LLM/embedding 成本。

### 建议方案

```python
# src/retrieval/cache.py
import hashlib
from cachetools import TTLCache

class RetrievalCache:
    def __init__(self, ttl=300):  # 5 分钟 TTL
        self._cache = TTLCache(maxsize=5000, ttl=ttl)
    
    def _key(self, user_id: str, query: str) -> str:
        # 归一化 query 后 hash
        normalized = query.strip().lower()
        return hashlib.sha256(f"{user_id}:{normalized}".encode()).hexdigest()
    
    def get(self, user_id: str, query: str) -> dict | None:
        return self._cache.get(self._key(user_id, query))
    
    def set(self, user_id: str, query: str, result: dict):
        self._cache[self._key(user_id, query)] = result
```

### 文件变更

| Action | Path | Purpose |
|--------|------|---------|
| CREATE | `src/retrieval/cache.py` | 检索结果缓存层 |
| MODIFY | `src/retrieval/gateway.py` | retrieve() 前检查缓存 |

### 验收标准

- [ ] 同一用户 5 分钟内相同 query 命中缓存，不触发 Milvus/Neo4j 调用
- [ ] 缓存命中记录到 metrics
- [ ] 缓存不跨用户泄露（key 包含 user_id）

---

## P2 — 结构化输出验证

### 现状

LLM 结构化输出（JSON）仅在基本层面验证：
- Supervisor 分解：验证 `strategy` 和 `worker_id`
- Delta 提取：基本 JSON 解析
- 无 Pydantic schema 验证
- 格式错误的数据可能进入 state 并级联失败

### 目标

所有 LLM 结构化输出经过 Pydantic 验证，格式错误被拦截并重试。

### 建议方案

```python
# src/agent/validation.py
from pydantic import BaseModel, ValidationError, Field
from typing import Literal

class DecompositionResult(BaseModel):
    strategy: Literal["parallel", "sequential"]
    decomposition: list[SubTaskSchema]
    reasoning: str = ""

class SubTaskSchema(BaseModel):
    worker_id: Literal["worker_restaurant", "worker_voucher", "worker_chat"]
    task: str = Field(min_length=1, max_length=1000)
    priority: int = Field(ge=1, le=3)

def validate_or_retry(llm_output: str, schema: type[BaseModel], max_retries=2):
    """解析 LLM 输出，验证失败时重试。"""
    for attempt in range(max_retries + 1):
        try:
            data = json.loads(llm_output)
            return schema(**data)
        except (json.JSONDecodeError, ValidationError) as e:
            if attempt == max_retries:
                raise
            llm_output = retry_with_error_feedback(llm_output, str(e))
```

### 文件变更

| Action | Path | Purpose |
|--------|------|---------|
| CREATE | `src/agent/validation.py` | Pydantic schemas + validate_or_retry |
| MODIFY | `src/agent/supervisor.py` | 分解结果使用 Pydantic 验证 |
| MODIFY | `src/agent/workers/base.py` | Delta 提取结果使用 Pydantic 验证 |
| MODIFY | `src/agent/synthesizer.py` | Delta 使用 Pydantic 验证 |

### 验收标准

- [ ] `{"strategy": "invalid"}` → 验证失败 → 重试 → 仍失败 → fallback
- [ ] 缺少必填字段的分解结果被拒绝
- [ ] 验证失败次数记录到 metrics

---

## P2 — Health Check 细粒度化

### 现状

`GET /health` 返回 `{"status": "ok"}`：
- 无依赖健康检查
- 无 readiness vs liveness 区分
- K8s 无法做正确的探活

### 目标

提供 k8s 兼容的 health check 端点。

### 建议方案

```python
@app.get("/health/live")
async def liveness():
    """K8s liveness probe — 仅检查进程是否存活."""
    return {"status": "ok"}

@app.get("/health/ready")
async def readiness():
    """K8s readiness probe — 检查所有依赖是否就绪."""
    checks = {}
    
    # Milvus
    try:
        milvus_store.client.get_collection_stats("user_event")
        checks["milvus"] = "ok"
    except Exception as e:
        checks["milvus"] = f"error: {e}"
    
    # Neo4j
    try:
        await neo4j_client.verify_connectivity()
        checks["neo4j"] = "ok"
    except Exception as e:
        checks["neo4j"] = f"error: {e}"
    
    # Postgres
    try:
        await pg_manager.check_connection()
        checks["postgres"] = "ok"
    except Exception as e:
        checks["postgres"] = f"error: {e}"
    
    # LLM API
    try:
        client = get_sync_llm_client()
        client.models.list()
        checks["llm_api"] = "ok"
    except Exception as e:
        checks["llm_api"] = f"error: {e}"
    
    all_ok = all(v == "ok" for v in checks.values())
    status_code = 200 if all_ok else 503
    return JSONResponse({"status": "ready" if all_ok else "not_ready", "checks": checks}, status_code=status_code)
```

### 文件变更

| Action | Path | Purpose |
|--------|------|---------|
| MODIFY | `src/main.py` | 替换 /health，添加 /health/live 和 /health/ready |

### 验收标准

- [ ] `GET /health/live` 始终返回 200（进程存活）
- [ ] `GET /health/ready` 在依赖全部可用时返回 200
- [ ] `GET /health/ready` 在任一依赖不可用时返回 503 + 具体错误信息

---

## P3 — 地理空间搜索

### 现状

用户传入 `longitude`/`latitude` 但 tools 未使用：
- `search_shops` 不支持 `order_by_distance`
- 无法实现"最近的火锅店"

### 建议方案

在 `search_shops` 中添加 `order_by_distance` 参数，利用 Milvus 的地理过滤或后处理按经纬度排序。

### 文件变更

| Action | Path |
|--------|------|
| MODIFY | `src/agent/tools/recommendation/search_shops.py` |

---

## P3 — 多模态支持

### 现状

仅支持文本输入。无法处理图片（用户拍照问"这家店怎么样"）。

### 建议方案

- 支持图片 URL 或 base64 输入
- 在 supervisor 中识别图片 → 路由到多模态处理
- 使用视觉模型做图片理解

### 文件变更

| Action | Path |
|--------|------|
| MODIFY | `src/main.py` (ChatRequest 增加 image_url 字段) |
| CREATE | `src/agent/multimodal.py` |

---

## P3 — 成本追踪

### 现状

无 per-user / per-request token 消费统计。

### 建议方案

在 LLM 调用处记录 token 使用量，按 `user_id` 聚合。

### 文件变更

| Action | Path |
|--------|------|
| MODIFY | `src/agent/workers/base.py` |
| MODIFY | `src/agent/supervisor.py` |
| MODIFY | `src/agent/synthesizer.py` |
| CREATE | `src/observability/cost_tracker.py` |

---

## P3 — SessionSummarizer 缓存治理

### 现状

`SessionSummarizer._round_cache` 是普通 `dict`，无 TTL，无上限，长期运行可能 OOM。

### 建议方案

改为 `cachetools.TTLCache(maxsize=10000, ttl=3600)`。

### 文件变更

| Action | Path |
|--------|------|
| MODIFY | `src/memory/session_summarizer.py` |

---

## P3 — Graceful Shutdown

### 现状

lifespan shutdown 关闭连接，但不等待正在执行的请求完成。正在进行的 SSE 流会被粗暴截断。

### 建议方案

```python
# main.py lifespan shutdown
import asyncio

# 等待正在执行的请求
await asyncio.wait_for(
    asyncio.gather(*active_tasks, return_exceptions=True),
    timeout=10.0,
)
```

### 文件变更

| Action | Path |
|--------|------|
| MODIFY | `src/main.py` |

---

## P3 — 集成测试补齐

### 现状

Plan 文档中定义了 `tests/agent/test_agent_graph.py`（单 worker + 多 worker + HITL 集成测试），但文件未实际创建。当前测试以单元测试为主。

### 建议方案

创建集成测试，mock 外部依赖，验证完整 graph 路径：

- 单 worker 路径（chat / restaurant / voucher）
- 多 worker 并行路径
- HITL interrupt + resume 路径
- supervisor 降级路径（LLM 失败 → 规则路由）
- synthesizer 降级路径（LLM 失败 → concat）
- 跨 turn 状态持久化

### 文件变更

| Action | Path |
|--------|------|
| CREATE | `tests/agent/test_agent_graph.py` |
| CREATE | `tests/integration/test_full_pipeline.py` |

---

## 总结

| 优先级 | 项数 | 核心主题 |
|--------|------|---------|
| P0 | 3 | 安全、可观测性、韧性 — 从"能跑"到"能上线" |
| P1 | 4 | 记忆工具、会话内可见性、限流、会话管理 — 核心功能闭环 |
| P2 | 5 | 多轮追踪、Prompt 版本、缓存、验证、Health — 生产质量 |
| P3 | 6 | 地理搜索、多模态、成本、缓存治理、Graceful Shutdown、测试 — 长期完善 |

**建议实施顺序**：P0 全部 → P1 全部 → P2 按需 → P3 按需
