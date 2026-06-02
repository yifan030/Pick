# AI 智能导购 Agent — 开发步骤

> 13个垂直切片，每个都可作为独立的 vibe coding 提示词使用。
> 已完成的 #1–#8, #10 不再列出，从剩余工作开始。
>
> **2026-06-02 更新**：已用 LangChain `create_agent` + LangGraph v2 streaming + Middleware 模式
> 重构了 agent-service 的骨架代码。WS-04, WS-05, WS-06, WS-08, WS-09 的原方案已被大幅简化，
> WS-07, WS-13 引入了 HumanInTheLoopMiddleware 和内置 Retry 中间件。
> 详见下方各 WS 的「更新方案」。

---

## 当前状态

**已完成（共9项 + Agent骨架重构）：**
- ✅ #1–#2 DB迁移：tb_shop（description/tags/recommended_scenes）、tb_shop_type（parent_id）
- ✅ #3–#4 Java同步端点：GET /api/sync/shops、GET /api/sync/blogs + InternalTokenInterceptor
- ✅ #5 Milvus Docker Compose + Python FastAPI骨架
- ✅ #6 Milvus 2个 HNSW Collection（collection_shop_desc + collection_user_note）
- ✅ #7–#8 全量Embedding同步（shop_desc含多模态 + user_note）
- ✅ #10 Python POST /chat 端点（已重构为 Agent + SSE v2 streaming）
- ✅ **Agent骨架重构**（2026-06-02）：
  - `agent/config.py` — 引入 `init_chat_model`（LangChain 模型工厂）
  - `agent/agent.py` — `create_agent` + InMemorySaver + 3个tool + 内置middleware
  - `agent/chat.py` — `agent.astream()` v2 协议（messages + custom 模式）
  - `agent/middleware.py` — 自定义中间件（日志 + 内容安全）
  - `agent/redis_history.py` — Redis 对话历史持久化（含连接缓存 + 降级）
  - `agent/tools/retrieval.py` — `search_shops` @tool（双路检索 + shop_card 推送 + 标量过滤）
  - `agent/tools/voucher.py` — `query_vouchers` @tool（HTTP 查券）
  - `agent/tools/purchase.py` — `place_order` @tool（下单 + HumanInTheLoopMiddleware）
  - `main.py` — lifespan + `/chat` + `/chat/resume` 端点

**Java SyncController路径：** `core-service/src/main/java/org/xu/sync/SyncController.java`
**Python /chat路径：** `agent-service/src/main.py` → `agent-service/src/agent/chat.py`
**Agent核心路径：** `agent-service/src/agent/agent.py`（`create_agent` 入口）
**Tools路径：** `agent-service/src/agent/tools/`（retrieval.py + voucher.py + purchase.py）
**Milvus模块路径：** `agent-service/src/milvus/__init__.py`
**Vue路由路径：** `vue3/src/router/index.js`（尚无 /ai-assistant）

## 架构变更说明

原方案使用手动 `StateGraph` + `intent_router` 节点 + 条件边 → 已被 `create_agent` + tool calling 替代：
- **不再需要** `graph.py`, `intent.py`, `nodes.py`
- **意图路由**：由 LLM 原生 function calling 决定（search_shops / query_vouchers / place_order / 直接回复）
- **检索**：合并 WS-05 + WS-08 + WS-09 为单一 `search_shops` @tool
- **多轮对话**：由 InMemorySaver checkpointer 自动管理，不再需要手动约束提取
- **降级**：ModelRetryMiddleware + ToolRetryMiddleware 替代分散的 try/except
- **下单确认**：HumanInTheLoopMiddleware(interrupt_on={"place_order": True}) 替代手动状态机
- **流式**：`agent.astream(version="v2", stream_mode=["messages", "custom"])` 替代手写 SSE 解析

---

## 依赖关系速览

```
Wave 1（可4线并行）：
  WS-01  增量同步定时任务        ─ 独立
  WS-02  Redis对话历史存储       ─ 独立
  WS-03  Java ChatController透传 ─ 独立
  WS-04  LangGraph意图识别路由   ─ 独立

Wave 2（依赖Wave 1）：
  WS-05  shop_desc语义检索       ← WS-04
  WS-06  多轮对话+约束继承       ← WS-02 + WS-05
  WS-07  自动下单流程            ← WS-04

Wave 3（依赖Wave 2）：
  WS-08  user_note检索+双路合并  ← WS-05
  WS-09  标量过滤（商圈/价格/类型）← WS-05
  WS-10  前端聊天页面            ← WS-03

Wave 4（依赖Wave 3）：
  WS-11  查券+LLM推荐语+shop_card ← WS-08 + WS-09
  WS-12  前端店铺卡片+详情Modal   ← WS-11 + WS-10

Wave 5（收尾）：
  WS-13  降级兜底+断点恢复       ← WS-11 + WS-10
```

---

## Wave 1：并行基建（4个独立任务）

### WS-01 增量同步定时任务

**类型：** AFK | **阻塞：** 无 | **预计改动文件：** 3–4个（Python）

## 要构建什么

在 Python AI 服务中实现一个定时轮询的增量同步器，每5分钟从 Java 后端拉取变更数据并更新 Milvus。

## 完整流程

```
每5分钟触发：
  1. 从本地文件（如 sync_state.json）读取 last_sync_time 和 last_blog_sync_time
  2. GET /api/sync/shops?since={last_sync_time}
     - 返回新增/更新的店铺列表
  3. GET /api/sync/blogs?since={last_blog_sync_time}
     - 返回新增/更新的探店笔记列表
  4. 对每条 shop：
     a. 按 "shop_desc_{shop_id}" 删除旧向量（如果存在）
     b. 构造向量化文本（name + description + tags + recommended_scenes + images）
     c. 调 embedding API 生成向量
     d. upsert 到 collection_shop_desc
  5. 对每条 blog：
     a. 按 "note_{blog_id}" 删除旧向量
     b. 构造文本（title + content）
     c. 调 embedding API 生成向量
     d. upsert 到 collection_user_note
  6. 更新 last_sync_time / last_blog_sync_time = now()
  7. 写入 sync_state.json
```

## 技术要点

- **同步状态存储：** JSON 文件 `sync_state.json`，格式 `{"last_shop_sync_ms": 1234567890000, "last_blog_sync_ms": 1234567890000}`
- **定时器：** 使用 `asyncio` + `apscheduler` 或简单的 `while True` + `asyncio.sleep(300)`
- **启动方式：** FastAPI `lifespan` 事件中启动后台任务
- **复用现有代码：**
  - `ingestion/shop_sync.py` 的 `fetch_shops()`, `embed_shop_multimodal()`, `to_milvus_record()`
  - `ingestion/user_note_sync.py` 的 `fetch_blogs_from_java()`, `build_embedding_text()`, `to_milvus_row()`
  - `ingestion/embedding.py` 的 `embed_texts()`
- **幂等性：** 用 upsert + 先删后插保证重复执行安全
- **软删除处理：** 如果 Java 侧实现了软删除字段，按 delete_flag 过滤删除对应向量
- **错误处理：** 单条失败不阻断整批；记录失败ID到日志；下次轮询自动重试

## 需要创建的文件

- `agent-service/src/ingestion/incremental_sync.py` — 增量同步主逻辑
- 修改 `agent-service/src/main.py` — 在 lifespan 中启动后台定时任务

## 验收标准

- [ ] 在 Java 侧新增一条 shop → 等一轮同步周期 → Milvus 中可见对应向量
- [ ] 更新一条 shop → 等一轮 → 向量已刷新
- [ ] 删除一条 shop → 等一轮 → 向量已删除
- [ ] 同步异常（如 embedding API 挂了）→ 记录错误日志 → 下一轮自动重试
- [ ] 重启 Python 服务后 last_sync_time 从文件恢复，不丢失进度

---

### WS-02 Redis 对话历史存储

**类型：** AFK | **阻塞：** 无 | **预计改动文件：** 2–3个（Python）

## 要构建什么

用 Redis 存储用户对话历史，session_id 为 key，30分钟 TTL，每次消息自动续期。让 AI 能记住同一会话中的前文。

## 完整流程

```
POST /chat 请求到达：
  1. 如果 session_id 为空，生成新的 UUID 作为 session_id
  2. 从 Redis 读取 chat:session:{session_id}
     - 命中：解析 JSON 数组，得到历史消息列表
     - 未命中：历史为空列表（新会话）
  3. 将历史消息注入 LLM messages（system prompt 之后、当前 query 之前）
  4. LLM 生成回复后：
     a. 追加用户消息 {role:"user", content: query}
     b. 追加助手消息 {role:"assistant", content: reply_text, shops: [...]}
     c. SET chat:session:{session_id} = 序列化后的 JSON 数组
     d. EXPIRE chat:session:{session_id} 1800（重置TTL为30分钟）
  5. SSE 流返回时，在 done 事件中附带 session_id 给前端
```

## 技术要点

- **Redis 客户端：** 使用 `redis` 库（已在 pyproject.toml 中声明），创建异步连接 `redis.asyncio.Redis`
- **Key 格式：** `chat:session:{session_id}`（session_id 为 UUID v4）
- **Value 格式：** JSON 数组，每条消息 `{"role": "user"|"assistant", "content": "...", "shops": [...]}`
- **TTL：** 30分钟（1800秒），每次新消息重置
- **连接参数：** 环境变量 `REDIS_HOST`（默认 localhost）、`REDIS_PORT`（默认 6379）、`REDIS_DB`（默认 0）
- **依赖注入：** 通过 FastAPI `Depends` 注入 Redis 连接
- **敏感数据：** 不在 Redis 中存储 user_id 的明文密码/token

## 需要创建/修改的文件

- `agent-service/src/agent/redis_history.py` — `load_history(session_id)`, `save_history(session_id, messages)`, `generate_session_id()`
- 修改 `agent-service/src/main.py` — 注入 Redis 连接，在 /chat 端点中集成历史加载/保存
- 修改 `agent-service/src/agent/chat.py` — `stream_chat` 接受历史消息参数

## 验收标准

- [ ] 发一条消息 → Redis 中存在 `chat:session:{session_id}` key
- [ ] 历史数据包含 role 和 content 字段，消息顺序正确
- [ ] 30分钟无操作 → key 自动过期（或用 ttl 命令验证剩余时间 ≤ 1800）
- [ ] 发第二条消息 → TTL 重置为 30 分钟
- [ ] 新会话（不传 session_id）→ 自动生成 session_id
- [ ] Redis 不可用时 → 不崩溃，仅当前轮对话可用（无历史）

---

### WS-03 Java ChatController + WebClient SSE 透传

**类型：** AFK | **阻塞：** 无 | **预计改动文件：** 2–3个（Java）

## 要构建什么

在 Java Spring Boot 中新增 ChatController，作为 SSE 透传代理：接收前端 sa-token 认证请求，通过 WebClient 转发到 Python /chat，将响应流逐条透传给前端。

## 完整流程

```
前端 fetch('/api/chat/stream') 携带 sa-token Cookie/Header
  │
  ▼
Java ChatController
  1. sa-token 鉴权（验证登录态）
  2. 从请求体解析 {session_id, query, longitude, latitude}
  3. 从 sa-token 会话中取出 user_id
  4. 构造发往 Python 的请求体：
     {"session_id": "...", "user_id": 123, "query": "...", "longitude": ..., "latitude": ...}
  5. WebClient POST → http://localhost:8000/chat
     Header: X-Internal-Token: {配置值}
     Content-Type: application/json
     Accept: text/event-stream
  6. Flux<ServerSentEvent> 逐条读取 Python 的 SSE 响应
  7. 每条数据原样写入 HttpServletResponse 的 OutputStream
  8. 不做任何解析、过滤、转换——完全透传
```

## 技术要点

- **WebClient 配置：** 用 `WebClient.builder()` 创建，baseUrl 通过配置项 `agent-service.base-url`（环境变量 `AGENT_SERVICE_URL`）
- **流式读取：** `webClient.post().bodyValue(...).accept(MediaType.TEXT_EVENT_STREAM).retrieve().bodyToFlux(ServerSentEvent.class)`
- **透传写入：** `response.contentType("text/event-stream")`，逐条 `response.writer.write(sse.data() + "\n\n")` + `flush()`
- **超时：** 连接超时 10s，读取超时 120s（长连接）
- **错误处理：** Python 不可用时返回 502 + JSON error
- **sa-token集成：** 复用现有的 sa-token 配置，Controller 上加 `@SaCheckLogin`
- **不阻塞：** Controller 方法返回 `void` 或 `Flux`，用 `SseEmitter` 或直接写 response

## 需要创建/修改的文件

- `core-service/src/main/java/org/xu/controller/ChatController.java` — 新建
- `core-service/src/main/java/org/xu/config/WebClientConfig.java` — WebClient Bean 配置
- `core-service/src/main/resources/application.yml` — 新增 `agent-service.base-url` 配置项

## ChatController 参考代码结构

```java
@RestController
@RequestMapping("/api/chat")
public class ChatController {

    private final WebClient webClient;
    private final String internalToken;

    @PostMapping("/stream")
    @SaCheckLogin
    public void streamChat(@RequestBody ChatStreamRequest body,
                           HttpServletResponse response) throws IOException {
        // 1. 从 sa-token 获取 user_id
        long userId = StpUtil.getLoginIdAsLong();

        // 2. 构造请求
        PythonChatRequest pythonReq = new PythonChatRequest(
            body.getSessionId(), userId,
            body.getQuery(), body.getLongitude(), body.getLatitude()
        );

        // 3. 设置响应头
        response.setContentType("text/event-stream");
        response.setCharacterEncoding("UTF-8");

        // 4. WebClient SSE 流式调用 + 透传
        webClient.post()
            .uri("/chat")
            .header("X-Internal-Token", internalToken)
            .bodyValue(pythonReq)
            .accept(MediaType.TEXT_EVENT_STREAM)
            .retrieve()
            .bodyToFlux(String.class)
            .doOnNext(chunk -> {
                response.getWriter().write(chunk);
                response.getWriter().flush();
            })
            .doOnError(e -> {
                response.setStatus(502);
                response.getWriter().write("data: {\"type\":\"error\",\"content\":\"AI服务不可用\"}\n\n");
            })
            .blockLast(); // 阻塞直到流结束
    }
}
```

## 验收标准

- [ ] curl Java `/api/chat/stream` 返回与直接 curl Python `/chat` 完全一致的 SSE 内容
- [ ] 不携带 sa-token 时返回 401
- [ ] Python 服务未启动时返回 502 + error 事件
- [ ] 前端 `fetch` + `ReadableStream` 可正常消费 Java 端 SSE

---

### WS-04 LangGraph 意图识别路由

> **⚡ 更新方案（2026-06-02）**：原方案的手动 StateGraph + intent_router 节点已被
> `create_agent` + tool calling 替代。不再需要单独的意图分类 LLM 调用。
> 意图由 LLM 原生 function calling 决定：
> - `search_shops` → recommend_shop 路径
> - `place_order` → purchase 路径
> - 无 tool call → chat 路径
>
> **状态**：Agent 骨架已实现（`agent/agent.py`），tools 已定义，
> 可直接使用。无需再创建 `graph.py` / `intent.py` / `nodes.py`。

**类型：** AFK | **阻塞：** 无 | **预计改动文件：** 3–4个（Python）

## 要构建什么（原始方案，已被新方案替代）

将现有的直通 LLM 的 `/chat` 端点升级为 LangGraph Agent：入口节点用 LLM 识别用户意图，根据意图路由到不同分支。MVP 阶段 chat 分支走现有直聊逻辑，recommend_shop 和 purchase 先返回占位提示。

## LangGraph 状态图

```
                    ┌──────────────────┐
                    │   START (入口)     │
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │  intent_router    │  ← LLM 识别意图
                    │  返回: chat       │
                    │  recommend_shop   │
                    │  purchase         │
                    └────────┬─────────┘
                             │
          ┌──────────────────┼──────────────────┐
          │                  │                  │
    ┌─────▼──────┐   ┌──────▼──────┐   ┌──────▼──────┐
    │ chat_node   │   │ rec_node    │   │ buy_node    │
    │ (直聊,已实现)│   │ (占位)       │   │ (占位)       │
    └─────┬──────┘   └──────┬──────┘   └──────┬──────┘
          │                  │                  │
          └──────────────────┼──────────────────┘
                             │
                    ┌────────▼─────────┐
                    │   END (汇总输出)   │
                    └──────────────────┘
```

## 技术要点

- **LangGraph：** `StateGraph`，定义 AgentState（query, session_id, user_id, messages, intent, result）
- **意图识别 prompt（中文）：**
  ```
  你是一个意图分类器。分析用户的输入，返回以下三种意图之一：
  - recommend_shop：用户想寻找/推荐店铺、餐厅、KTV等本地服务
  - purchase：用户想购买某个具体店铺的优惠券
  - chat：闲聊、打招呼、感谢、或其他不属于以上两类的对话

  只回复意图名称，不要回复其他内容。

  用户输入：{query}
  ```
- **LLM调用：** 复用 `agent/config.py` 的 `get_llm_client()`，用非流式 `chat.completions.create` 做分类
- **路由函数：** `def route_by_intent(state: AgentState) -> Literal["chat", "recommend_shop", "purchase"]`
- **状态定义：**
  ```python
  class AgentState(TypedDict):
      session_id: str
      user_id: int | None
      query: str
      longitude: float | None
      latitude: float | None
      messages: list[dict]  # 对话历史（来自Redis，WS-02实现）
      intent: str           # chat / recommend_shop / purchase
      result: str           # 最终回复文本
      shops: list[dict]     # 关联店铺（recommend_shop 时填充）
  ```
- **SSE 输出：** 保持现有 `_sse()` 函数格式，final state 统一输出

## 需要创建/修改的文件

- `agent-service/src/agent/graph.py` — LangGraph StateGraph 定义
- `agent-service/src/agent/intent.py` — 意图识别 prompt + LLM 调用
- `agent-service/src/agent/nodes.py` — chat_node / rec_node / buy_node 占位实现
- 修改 `agent-service/src/main.py` — /chat 端点改用 graph 执行
- 修改 `agent-service/src/agent/chat.py` — stream_chat 适配 graph state

## 验收标准

- [ ] curl -d '{"query":"推荐火锅"}' → 日志显示 intent=recommend_shop → 返回占位提示"推荐功能开发中"
- [ ] curl -d '{"query":"你好"}' → 日志显示 intent=chat → 返回 LLM 流式回复
- [ ] curl -d '{"query":"帮我买两张券"}' → 日志显示 intent=purchase → 返回占位提示"下单功能开发中"
- [ ] 意图识别失败（LLM返回非预期值）→ 降级为 chat 意图
- [ ] 意图识别耗时 < 1s

---

## Wave 2：依赖 Wave 1（3个任务）

### WS-05 shop_desc 语义检索

> **⚡ 更新方案（2026-06-02）**：已实现为 `agent/tools/retrieval.py` 的 `search_shops` @tool。
> 使用了 `response_format="content_and_artifact"`（同时返回 LLM 文本和结构化数据）、
> `get_stream_writer()` 在检索阶段直接推送 shop_card SSE 事件。
> 不再需要手动 embedding 调用 + prompt 拼接。
>
> **状态**：✅ 已实现。检索逻辑完整（embedding → Milvus search → shop_card 推送）。

## 完整流程

```
recommend_shop 意图（在 WS-04 的 rec_node 中实现）：
  1. 用户 query → Doubao embedding API 生成向量
  2. Milvus.search(
       collection_name="collection_shop_desc",
       data=[query_embedding],
       limit=5,
       output_fields=["shop_id", "area", "longitude", "latitude",
                      "avg_price", "type", "sub_type", "score",
                      "open_hours", "tags", "content_type"]
     )
  3. 拿到5条 Milvus 搜索结果
  4. 将店铺信息格式化为文本，注入 LLM context
  5. LLM 根据检索结果生成推荐语（带店铺名称 + 简要推荐理由）
  6. SSE 流式输出 text 事件
```

## 技术要点

- **Milvus 搜索：** 使用 `pymilvus.MilvusClient.search()`，metric_type=COSINE
- **Embedding 复用：** 使用 `ingestion/embedding.py` 的 `embed_texts()` 对 query 向量化
- **Milvus 连接复用：** 从 `milvus/__init__.py` 导入 init 函数
- **LLM 推荐 prompt：**
  ```
  你是一个本地生活推荐助手。基于以下检索到的店铺信息，为用户推荐最合适的店铺。
  请给出2-3个店铺的简要推荐，说明每家店的特点和推荐理由。
  不要编造任何不在检索结果中的店铺信息。如果检索结果为空，如实告知用户没有找到匹配的店铺。

  用户需求：{query}
  检索结果：{shops_json}
  ```
- **context 截断：** 每条店铺取 name + type + area + avg_price + score + tags + description 前200字
- **元数据传递：** 搜索结果中的 shop_id 保留在 state 中，供后续 WS-11 查券使用

## 需要创建/修改的文件

- `agent-service/src/agent/retrieval.py` — Milvus 搜索函数封装
- 修改 `agent-service/src/agent/nodes.py` — rec_node 实现真正检索+推荐
- 修改 `agent-service/src/agent/graph.py` — 如有必要调整 graph 结构

## 验收标准

- [ ] curl "推荐火锅" → 日志确认 Milvus 返回 ≤5 条搜索结果
- [ ] 返回结果的 content_type 均为 "shop_description"
- [ ] SSE 流输出包含具体的店铺名称和推荐理由
- [ ] 检索结果为空 → LLM 回复"没有找到匹配的店铺"，不编造内容
- [ ] 检索 + LLM 生成总耗时 P95 < 10s

---

### WS-06 多轮对话：Redis 历史注入 + 约束继承

> **⚡ 更新方案（2026-06-02）**：InMemorySaver checkpointer 通过 thread_id 自动累积消息历史，
> LLM 看到完整上下文自然理解约束叠加。不再需要单独的约束提取 LLM 调用。
> System prompt 一句话搞定："多轮追问时合并所有约束；说'重新推荐'时清空"。
> Redis 作为 checkpointer 的持久化补充（`agent/redis_history.py`）。
>
> **状态**：骨架已实现（checkpointer + Redis 持久化）。

**类型：** AFK | **阻塞：** WS-02, WS-05 | **预计改动文件：** 2–3个（Python）

## 要构建什么

利用 Redis 中存储的对话历史，让 AI 理解多轮对话上下文：约束逐轮叠加（"火锅"→"人均100以内"→"有包厢"），支持否定语义（"不要春熙路的"），支持断线重连恢复。

## 完整流程

```
每个新 query 到达时：
  1. 从 Redis 加载 chat:session:{session_id} 的历史消息
  2. 将历史消息 + 当前 query 一起送入 LLM
     - 用 LangGraph 的 messages 状态累积
  3. LLM 理解上下文：
     - "推荐火锅" → intent=recommend_shop, constraints={type:"火锅"}
     - "人均100以内" → 追加约束 avg_price<=100，叠加在之前约束上
     - "有包厢的" → 追加约束 tags 包含"有包厢"
     - "不要春熙路的" → 追加否定约束 area!="春熙路"
  4. 新约束与历史约束合并后执行检索
  5. 生成回复后更新 Redis 历史

断线重连：
  前端断开 → 用户刷新/重连 → 传同一个 session_id
  → 从 Redis 恢复全部历史 → 上下文不丢失
```

## 技术要点

- **LLM 约束提取 prompt：** 在检索前增加一个约束提取步骤，让 LLM 从 query + 历史约束中提取所有当前有效约束
  ```
  基于对话历史和当前用户输入，提取所有店铺筛选条件。
  历史约束：{previous_constraints}
  用户输入：{query}

  返回 JSON：
  {"include": {"type": "...", "area": "...", "avg_price_max": ..., "tags": [...]},
   "exclude": {"area": "...", "tags": [...]}}
  ```
- **约束合并逻辑：** 新约束覆盖同类型旧约束（如 area），不冲突的追加上去
- **否定语义：** LLM 识别"不要XX"、"除了XX"等否定表达，放入 exclude 字段
- **历史截断：** 只保留最近 20 条消息，超出时裁剪最旧的（保留首条 system 消息）
- **约束 reset：** 用户说"重新推荐"、"从新找"时清空约束

## 需要修改的文件

- 修改 `agent-service/src/agent/nodes.py` — 在 rec_node 前增加约束提取逻辑
- 修改 `agent-service/src/agent/retrieval.py` — 接受 constraints dict
- 修改 `agent-service/src/agent/redis_history.py` — 如需要增加约束存储

## 验收标准

- [ ] 同一 session 连续3条消息"火锅"→"人均100以内"→"有包厢" → 第三次检索结果同时满足三个约束
- [ ] "推荐火锅，不要春熙路的" → 检索结果不包含春熙路商圈
- [ ] "重新推荐" → 清空之前的约束，只根据新的 query 检索
- [ ] 模拟断线：关闭浏览器 → 用相同 session_id 重新请求 → 上下文不丢失
- [ ] 对话超过 20 条消息 → 历史被截断但不报错

---

### WS-07 下单流程：券解析 → 查券 → LLM 确认 → 下单

> **⚡ 更新方案（2026-06-02）**：使用 `HumanInTheLoopMiddleware(interrupt_on={"place_order": True})`
> 替代手动 state machine + `pending_action` 字段。
> `place_order` @tool 调用时自动中断 → `/chat/resume` 端点处理确认/取消 → `Command(resume=...)` 继续执行。
> 30s 超时需在后续迭代中实现。
>
> **状态**：骨架已实现（`agent/tools/purchase.py` + `agent/tools/voucher.py` + `/chat/resume` 端点）。
> 需要 Java 侧提供按 shop_ids 批量查券接口和 X-Internal-Token 代下单支持。

**类型：** AFK | **阻塞：** WS-04 | **预计改动文件：** 3–4个（Python）

## 要构建什么

实现 `purchase` 意图的完整流程：LLM 解析用户下单意图 → HTTP 调 Java 查券 → 生成确认语 → 等待用户确认 → 调用 Java 下单接口。

## 完整流程

```
purchase 意图被识别后：
  1. LLM 解析 query，提取：店名、券名、数量
     例："帮我买两张蜀大侠的满100减20券"
     → {shop_name: "蜀大侠", voucher_desc: "满100减20", quantity: 2}

  2. HTTP 调 Java 查券接口（携带 X-Internal-Token）：
     GET /api/voucher/query?user_id={user_id}&shop_name={shop_name}
     或按 shop_ids 批量查可用券

  3. 匹配到目标券后，LLM 生成确认语：
     "为您找到 蜀大侠火锅 满100减20券 ×2张，共40元（每张20元）。确认下单吗？"

  4. 用户回复"确认" → 进入下单步骤
     用户回复"取消"/"不要" → 中止，返回"已取消下单"

  5. HTTP 调 Java 下单接口：
     POST /api/voucher-order/seckill/{voucher_id}
     Header: X-Internal-Token
     Body: {user_id, quantity}

  6. 返回订单结果：
     - 成功："下单成功！订单号 xxx，2张券已发放到您的账户"
     - 失败：告知失败原因

业务规则：
  - 秒杀券：拦截不自动下单，提示"秒杀券不支持自动下单，已为您设置提醒"
  - 库存不足：LLM 自动推荐同类可用的普通券
  - 券名模糊匹配：LLM 辅助消歧
```

## 技术要点

- **状态管理：** purchase 是两轮交互（确认/取消），需要在 LangGraph 中处理
  - 第一轮：purchase_intent → 解析券 → 查券 → 生成确认语 → 等待用户回复
  - 第二轮：用户在同一个 session 中回复 → 识别为 purchase_confirm 还是 purchase_cancel
- **LangGraph 实现方式：**
  - 在 `AgentState` 中增加 `pending_action: str | None` 字段（"purchase_confirm"）
  - 下一轮消息到达时检查 `pending_action`，如为 purchase_confirm 则走确认分支
- **HTTP 调 Java：** 使用 `httpx`（同步或异步），配置 baseURL + internal_token
  - baseURL: `JAVA_BASE_URL` 环境变量（默认 http://localhost:8085）
- **Java 下单接口：** 复用现有的 `VoucherOrderController`
  - 需要验证该接口是否支持从 body 传入 user_id（跨服务代下单）
  - 如果不支持，需要先做 Java 侧小改造：允许 `X-Internal-Token` 认证时代入 user_id
- **确认超时：** 30秒无回复则自动取消 pending_action

## 需要创建/修改的文件

- `agent-service/src/agent/purchase.py` — 购买流程：parse_intent()、query_voucher()、confirm_and_order()
- 修改 `agent-service/src/agent/nodes.py` — buy_node 实现完整购买状态机
- 修改 `agent-service/src/agent/graph.py` — 增加 purchase_confirm 分支
- 可能修改 Java `VoucherOrderController` — 支持 X-Internal-Token 代下单

## 验收标准

- [ ] curl "帮我买两张蜀大侠满100减20的券" → 返回确认语，含券名+数量+总价
- [ ] 回复"确认" → 返回订单号 + 下单成功
- [ ] 回复"取消" → 返回已取消，不产生订单
- [ ] 秒杀券 → 拦截 + 提示已设置提醒
- [ ] 普通券库存不足 → 推荐同类替代券
- [ ] 模糊券名（"那个火锅的券"）→ LLM 辅助匹配最近的检索结果

---

## Wave 3：依赖 Wave 2（3个任务）

### WS-08 user_note 检索 + 双路结果合并

> **⚡ 更新方案（2026-06-02）**：已合并到 `search_shops` @tool 内部（`agent/tools/retrieval.py`）。
> 双 Collection 并行搜索 → 按 shop_id merge → 同一 tool 完成。
> `get_stream_writer()` 在检索阶段直接推送 shop_card。
>
> **状态**：✅ 已实现（`_search_shop_desc` + `_search_user_note` + `_merge_results`）。

**类型：** AFK | **阻塞：** WS-05 | **预计改动文件：** 2–3个（Python）

## 要构建什么

在 shop_desc 检索的基础上增加 user_note（探店笔记）检索，将两路结果按 shop_id 合并去重，在推荐中附上真实用户评价。

## 完整流程

```
recommend_shop 检索步骤：
  1. query embedding → 并行检索两个 Collection：
     - collection_shop_desc：Top-K = 5
     - collection_user_note：Top-K = 3

  2. 合并策略：
     a. 取 shop_desc 的5条结果作为主结果
     b. 取 user_note 的3条结果
     c. 按 shop_id 分组：
        - 如果 note 的 shop_id 匹配某条 shop_desc → 附在该店铺后
        - 如果 note 的 shop_id 不在 shop_desc 结果中 → 单独成条
     d. 最终结构：
        [
          {shop: {...}, notes: [{title, content_preview, user_nickname}, ...]},
          {shop: {...}, notes: []},
          ...
        ]

  3. 合并后的 context 送入 LLM 生成推荐语
     - 有笔记的店铺优先推荐（有真实用户背书）
     - 引用笔记中的关键评价词
```

## 技术要点

- **并行检索：** 两个 Milvus search 调用可并发执行（asyncio.gather）
- **Milvus 搜索参数：** shop_desc limit=5, user_note limit=3（控制 token 消耗）
- **笔记内容截断：** 每条笔记只取 title + content 前 100 字，超出截断加"..."
- **去重逻辑：** 纯 Python 代码实现，不依赖 Milvus
- **排序：** shop_desc 按 COSINE score 降序；附在店铺后的 notes 按自己的 score 降序

## 需要修改的文件

- 修改 `agent-service/src/agent/retrieval.py` — 增加 `search_user_notes()`，实现 `merge_results()`
- 修改 `agent-service/src/agent/nodes.py` — rec_node 调用双路检索 + 合并

## 验收标准

- [ ] 一次 query 同时触发两个 Collection 搜索
- [ ] 同一 shop_id 的笔记正确合并到对应店铺下
- [ ] 合并后的数据结构可送入 LLM 生成推荐语
- [ ] 某店铺无笔记 → notes 为空数组，不影响推荐
- [ ] user_note 的 shop_id 不在 shop_desc 结果中 → 单独作为推荐项出现

---

### WS-09 标量过滤（商圈/价格/类型）

> **⚡ 更新方案（2026-06-02）**：LLM 通过 tool calling schema 自动提取结构化 filter 参数
> （area, type_filter, max_price, min_price, min_score），传入 `search_shops` tool。
> `_build_filter_expr()` 构建 Milvus filter 表达式。不再需要单独的 filter 提取 LLM 调用。
> 包含 `SUB_TYPE_TO_TYPE` 映射表（"火锅" → type="美食"）。
>
> **状态**：✅ 已实现（`_build_filter_expr` + `SUB_TYPE_TO_TYPE`）。

**类型：** AFK | **阻塞：** WS-05 | **预计改动文件：** 2–3个（Python）

## 要构建什么

让 LLM 从用户 query 中提取标量过滤条件（area、avg_price、type），在 Milvus 检索时附加 scalar filter，实现精确筛选。

## 完整流程

```
1. LLM 从 query 中提取过滤条件（结合 WS-06 的历史约束）：
   "春熙路人均100以内的火锅"
   → {"area": "春熙路", "avg_price_max": 100, "type": "火锅"}

   提取 prompt：
   "从用户输入中提取店铺筛选条件，返回 JSON：
    {area: 商圈名|null, type: 大类名|null, avg_price_min: int|null, avg_price_max: int|null}
    只返回 JSON，不要其他内容。"

2. 构建 Milvus filter 表达式：
   条件组合示例：area == "春熙路" and avg_price <= 100 and type == "美食"
   - 注意：type 存储的是大类名（如"美食"），不是子类名（如"火锅"）
   - 需要将"火锅"映射到 type="美食"（因为子类型没有标量索引）
   - 或者用 type LIKE "%火锅%"（如果 Milvus 支持）

3. Milvus search 附加 filter：
   client.search(
     collection_name="collection_shop_desc",
     data=[query_embedding],
     limit=5,
     filter=filter_expr,
     output_fields=[...]
   )

4. 如果过滤后结果为空：
   - 降级：去掉最严格的过滤条件重试
   - 或提示用户"春熙路没有找到火锅店，为您推荐附近其他商圈的火锅店"
```

## 技术要点

- **Milvus filter 语法：** 使用 Milvus 的 scalar filter 表达式，支持 ==, !=, >, <, >=, <=, and, or, like
- **type 映射问题：** Milvus 中 type 存的是大类名（"美食"），但用户说"火锅"（子类）。处理方式：
  - 方案A（简单）：让 LLM 在提取条件时自动映射，prompt 中列出所有大类名
  - 方案B（精确）：Python 侧维护一个 type→parent_type 映射表，查询 shop_type 表
  - 推荐方案A，MVP 用 prompt 处理
- **约束互斥处理：** 当用户说"不要春熙路的火锅"→ filter: `type == "美食" and area != "春熙路"`
- **范围过滤：** avg_price 用 `avg_price <= N` 和 `avg_price >= N`，支持区间
- **降级策略：** 过滤结果为 0 时，去掉 area 约束重试；仍为 0 时去掉全部标量过滤只做向量检索

## 需要修改的文件

- `agent-service/src/agent/retrieval.py` — 增加 `extract_filters()` 和 `build_filter_expr()`
- 修改 `agent-service/src/agent/nodes.py` — rec_node 调用 filter 提取 + 检索

## 验收标准

- [ ] "春熙路人均100以内的火锅" → 结果全部满足 area=春熙路, avg_price≤100, type=美食
- [ ] "不要春熙路的火锅" → 结果排除春熙路商圈
- [ ] "评分4分以上的川菜" → 结果 score≥40（注意 score 是 ×10 存储的）
- [ ] query 无过滤条件 → 纯向量检索，不报错
- [ ] 过滤后结果为 0 → 自动放宽条件重试 + 给用户提示

---

### WS-10 前端聊天页面（路由 + SSE 消费 + Chat UI）

**类型：** AFK | **阻塞：** WS-03 | **预计改动文件：** 5–6个（Vue）

## 要构建什么

创建独立的 AI 导购对话页面 `/ai-assistant`，含 ChatView、ChatMessage、ChatInput 三个核心组件，通过 fetch + ReadableStream 消费 Java 端的 SSE 流，支持 sa-token 鉴权和地理位置获取。

## 页面结构

```
┌─────────────────────────────┐
│         导航栏 (可复用)       │
│  ← 返回    AI 导购           │
├─────────────────────────────┤
│                             │
│    ┌──────────────────┐     │
│    │ AI: 你好！我是你的 │     │  ← ChatMessage (AI气泡，左对齐，灰底)
│    │ 智能导购助手...    │     │
│    └──────────────────┘     │
│                             │
│         ┌──────────────────┐│
│         │ 用户: 推荐火锅   ││  ← ChatMessage (用户气泡，右对齐，蓝底)
│         └──────────────────┘│
│                             │
│    ┌──────────────────┐     │
│    │ AI: 为您找到两家  │     │  ← 流式逐字渲染
│    │ 火锅店...         │     │
│    └──────────────────┘     │
│                             │
├─────────────────────────────┤
│  ┌──────────────────────┐   │
│  │ 输入你想找的店铺...    │ 📤│  ← ChatInput (输入框 + 发送按钮)
│  └──────────────────────┘   │
└─────────────────────────────┘
```

## 技术要点

### 路由配置
- 路径：`/ai-assistant`
- `vue3/src/router/index.js` 新增路由
- 懒加载：`() => import('@/views/ai/ChatView.vue')`

### TabBar 入口
- 修改 `vue3/src/components/FootBar.vue`
- 将现有的"消息" tab（ChatDotRound 图标，index 3）改为导航到 `/ai-assistant`
- 或新增独立的"AI 导购"tab

### SSE 消费
```javascript
// 核心 SSE fetch 模式
async function sendMessage(query, sessionId) {
  const response = await fetch('/api/chat/stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      session_id: sessionId,
      query: query,
      longitude: userLocation.value?.longitude,
      latitude: userLocation.value?.latitude,
    }),
    credentials: 'include', // 携带 sa-token cookie
  })

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    // 解析 SSE 事件（可能一次收到多个）
    const lines = buffer.split('\n')
    buffer = lines.pop() // 保留不完整的行
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const event = JSON.parse(line.slice(6))
        handleSSEEvent(event) // 分发到 text / shop_card / done / error
      }
    }
  }
}

function handleSSEEvent(event) {
  switch (event.type) {
    case 'text':
      // 追加/更新当前AI消息文本（流式渲染）
      currentAiMessage.value += event.content
      break
    case 'shop_card':
      // 在当前AI消息中插入店铺卡片
      currentAiMessage.value.shops.push(event.data)
      break
    case 'done':
      // 流结束，保存 session_id
      sessionId.value = event.session_id
      break
    case 'error':
      // 显示错误提示
      showError(event.content)
      break
  }
}
```

### 组件拆分
- **`ChatView.vue`** — 主容器：消息列表（v-for + scrollToBottom）、输入框、滚动自动到底
- **`ChatMessage.vue`** — 单条消息：props {role, content, shops, isStreaming}，根据 role 切换左右对齐和颜色
- **`ChatInput.vue`** — 输入框：v-model + @keyup.enter 发送 + 发送按钮 + 发送中禁用

### 地理位置
- `navigator.geolocation.getCurrentPosition()` 获取坐标
- 失败时传空坐标，不阻塞发送
- 首次失败时提示"建议授权位置以获得更精准的附近推荐"

### 断线重连
- `fetch` 失败 → 显示"连接断开，点击重试"按钮
- 重试用相同 session_id 重新建立连接

## 需要创建/修改的文件

- `vue3/src/views/ai/ChatView.vue` — 主容器组件
- `vue3/src/views/ai/ChatMessage.vue` — 消息气泡组件
- `vue3/src/views/ai/ChatInput.vue` — 输入框组件
- `vue3/src/views/ai/composables/useChat.js` — SSE fetch + 状态管理 composable
- 修改 `vue3/src/router/index.js` — 新增 /ai-assistant 路由
- 修改 `vue3/src/components/FootBar.vue` — 修改"消息"tab 跳转到 /ai-assistant

## 验收标准

- [ ] 浏览器打开 `/ai-assistant` → 显示空白对话页，底部有输入框
- [ ] 输入"你好"回车 → 看到 AI 回复逐字流式渲染（不是一次性显示）
- [ ] 用户消息气泡右对齐蓝底，AI 消息气泡左对齐灰底
- [ ] 发送中 loading 状态：发送按钮禁用
- [ ] 授权位置 → 请求携带坐标；拒绝 → 仍可发送消息（坐标为空）
- [ ] 浏览器刷新页面 → 新 session，之前的对话清空（前端不持久化）
- [ ] 断网 → 显示"连接断开，点击重试"

---

## Wave 4：依赖 Wave 3（2个任务）

### WS-11 HTTP 查券 + LLM 推荐语生成 + shop_card SSE

> **⚡ 更新方案（2026-06-02）**：
> - `query_vouchers` @tool（`agent/tools/voucher.py`）：HTTP 调 Java 查券
> - shop_card 在 `search_shops` tool 内通过 `get_stream_writer()` 直接推送，不再需要 `[SHOP_CARD:id]` 标记解析
> - LLM 基于检索结果 + 券信息自然生成推荐语
>
> **状态**：Tools 已定义，需要 Java 侧批量查券接口就绪后联调。

**类型：** AFK | **阻塞：** WS-08, WS-09 | **预计改动文件：** 3–4个（Python）

## 要构建什么

在检索结果合并后，HTTP 调 Java 查券接口获取可用券信息，将店铺+券+笔记组合成 context，LLM 流式生成推荐语，SSE 交替输出 text 和 shop_card 事件。

## 完整流程

```
recommend_shop 检索合并完成后：
  1. 提取合并结果中的所有 shop_id 列表
     shop_ids = [r['shop']['shop_id'] for r in merged_results]

  2. HTTP 调 Java 查券：
     POST /api/voucher/available-by-shop-ids
     Header: X-Internal-Token
     Body: {shop_ids: [...], user_id: ...}
     返回：{shop_id: [voucher1, voucher2, ...], ...}

  3. 构建 LLM context（店铺 + 券 + 笔记）：
     """
     检索到的店铺列表：
     1. 蜀大侠火锅 | 评分4.6 | 人均120 | 春熙路 | 标签：有包厢,停车方便
        可用券：满100减20（剩余50张）| 8折代金券
        用户评价："服务很好，毛肚很新鲜..." — 用户A
     2. ...
     """

  4. LLM 流式生成推荐语 → SSE text 事件
     在适当位置插入 shop_card 事件（每推荐一家店就插一个 card）

  5. SSE 输出示例：
     data: {"type":"text","content":"为您找到两家火锅店：\n\n"}
     data: {"type":"text","content":"🔥 **蜀大侠火锅** 评分4.6 ..."}
     data: {"type":"shop_card","data":{"shop_id":1,"name":"蜀大侠火锅","score":4.6,"avg_price":120,"image":"/imgs/...","tags":["有包厢","停车方便"],"voucher":{"title":"满100减20","price":20,"stock":50}}}
     data: {"type":"text","content":"\n🔥 **海底捞火锅** 评分4.9 ..."}
     data: {"type":"shop_card","data":{...}}
     data: {"type":"done"}
```

## 技术要点

- **查券接口：** 如果 Java 没有现成的按 shop_ids 批量查券接口，需要新增或在 Python 侧循环调用单个接口
  - 优先新增 Java 批量接口（性能好）
  - MVP 可接受循环调单个接口（最多5次）
- **shop_card 格式（严格按 PRD §6.3）：**
  ```json
  {
    "type": "shop_card",
    "data": {
      "shop_id": 123456,
      "name": "蜀大侠火锅",
      "score": 4.6,
      "avg_price": 120,
      "image": "/imgs/shops/shop1.jpg",
      "tags": ["有包厢", "停车方便"],
      "voucher": {
        "title": "满100减20",
        "price": 20,
        "stock": 50
      }
    }
  }
  ```
- **查券失败降级：** 仍返回带店铺卡片的推荐，但 voucher 字段为 null
- **LLM 生成控制：**
  - 系统 prompt 要求 LLM 在提及每家店时输出一个 `[SHOP_CARD:{shop_id}]` 标记
  - Python 侧解析标记 → 替换为实际的 shop_card SSE 事件
  - 或者：LLM 直接输出文本，Python 侧根据 shop_id 出现顺序插入 card
- **image 字段：** 取店铺 images 的第一张图（按逗号分隔）

## 需要创建/修改的文件

- `agent-service/src/agent/voucher.py` — 查券 HTTP 调用 + 数据封装
- `agent-service/src/agent/recommend.py` — LLM 推荐语生成 + shop_card 插入逻辑
- 修改 `agent-service/src/agent/nodes.py` — rec_node 集成查券+推荐
- 可能需要修改 Java 侧新增按 shop_ids 批量查券接口

## 验收标准

- [ ] SSE 流中包含 `{"type": "shop_card"}` 事件，格式符合 PRD §6.3
- [ ] shop_card 含券信息（如果该店铺有可用券）
- [ ] 查券 HTTP 失败 → 仍返回 shop_card，voucher 字段为 null
- [ ] 流结束收到 `{"type": "done"}`
- [ ] 推荐语中提到的店铺名称与 shop_card 一一对应

---

### WS-12 前端店铺卡片 + 详情 Modal

**类型：** AFK | **阻塞：** WS-11, WS-10 | **预计改动文件：** 2–3个（Vue）

## 要构建什么

在对话流中渲染可点击的店铺卡片（ShopCard），点击弹出 Modal 展示完整店铺详情，不离开对话页面。复用现有的 ShopDetail 数据接口。

## 视觉结构

```
对话流中的店铺卡片：
┌─────────────────────────────────────┐
│ ┌─────────┐                         │
│ │ 店铺图片 │  蜀大侠火锅  ⭐4.6      │
│ │         │  人均 ¥120  春熙路       │
│ │  (150px)│  标签：有包厢 停车方便    │
│ │         │  🎫 满100减20  ¥20      │
│ └─────────┘                         │
└─────────────────────────────────────┘
       │ 点击
       ▼
┌─────────────────────────────────────┐
│ 店铺详情 Modal                    ✕  │
│ ┌─────────────────────────────────┐ │
│ │         店铺大图轮播             │ │
│ ├─────────────────────────────────┤ │
│ │ 蜀大侠火锅          ⭐4.6       │ │
│ │ 春熙路 · 人均¥120               │ │
│ │ 营业时间：10:00-22:00            │ │
│ │ 地址：春熙路xxx号               │ │
│ │ 标签：有包厢 停车方便 排队热门    │ │
│ │ ───────────────────             │ │
│ │ 店铺描述：地道川渝火锅...        │ │
│ │ ───────────────────             │ │
│ │ 可用优惠券：                     │ │
│ │ ┌ 满100减20  ¥20  剩余50张 ┐    │ │
│ │ └ 8折代金券  ¥30  剩余20张 ┘    │ │
│ │ ───────────────────             │ │
│ │ 用户评价（探店笔记）：           │ │
│ │ "服务很好，毛肚很新鲜..."        │ │
│ └─────────────────────────────────┘ │
└─────────────────────────────────────┘
```

## 技术要点

### ShopCard.vue
- Props: `shop` (object: shop_id, name, score, avg_price, image, tags, voucher)
- 布局：左图右文，图片 150×100px 圆角
- 评分显示：⭐ + score/10（后端存的是 ×10 的整数）
- 券标签：绿色底色 + 券标题 + 价格
- 点击 emit：`@click → emit('click', shop.shop_id)`

### ShopDetail Modal
- 使用 Element Plus `el-dialog` 或 `el-drawer`
- 内容：复用现有 `ShopDetail.vue` 或直接调用 `/api/shop/{id}` 获取详情
- 在 `ChatView.vue` 中管理 Modal 的 visible 状态
- 关闭 Modal → 回到对话页，聊天状态和消息列表不丢失

### 集成到 ChatMessage
- ChatMessage 检测消息中的 shops 数组
- 每条 AI 消息底部渲染 ShopCard 列表
- ShopCard 和 text 内容交替排列（保持后端 SSE 输出顺序）

## 需要创建/修改的文件

- `vue3/src/views/ai/ShopCard.vue` — 店铺卡片组件
- 修改 `vue3/src/views/ai/ChatMessage.vue` — 集成 ShopCard 渲染
- 修改 `vue3/src/views/ai/ChatView.vue` — 管理 Modal 状态

## 验收标准

- [ ] 对话中收到推荐回复 → 店铺卡片在消息气泡中渲染
- [ ] 卡片显示：图片、名称、评分、人均、标签、券信息（如有）
- [ ] 点击卡片 → Modal 弹出，展示完整店铺详情
- [ ] Modal 关闭 → 对话页状态不丢失，消息列表仍在
- [ ] 多个店铺 → 多个 ShopCard 依次排列，间距合理

---

## Wave 5：收尾（1个任务）

### WS-13 降级兜底 + 断点恢复

> **⚡ 更新方案（2026-06-02）**：降级逻辑由 Middleware 集中管理：
> - `ModelRetryMiddleware(max_retries=3)` — LLM 调用自动重试
> - `ToolRetryMiddleware(max_retries=2)` — Milvus/HTTP 工具自动重试
> - `content_safety_filter`（`after_model` 钩子）— 内容安全兜底
> - Tool 内部优雅降级（Milvus 挂了返回"搜索暂不可用"，券查不到返回空）
> - Redis 连接失败缓存（一次失败后续跳过，不阻塞对话）
>
> **状态**：Middleware 层已实现。具体的超时控制和全链路集成测试待后续完善。

**类型：** AFK | **阻塞：** WS-11, WS-10 | **预计改动文件：** 3–5个（Python + Vue）

## 要构建什么

覆盖所有关键故障点的降级处理，确保系统在任何单点故障下用户体验可接受。体现"先保证不崩，再尽量可用"的原则。

## 故障场景 × 处理策略

| 故障点 | 处理策略 | 用户感知 |
|--------|---------|---------|
| Milvus 不可用（连接超时/500） | 跳过检索，聊天意图正常；推荐意图返回降级提示 | "搜索服务暂时不可用，请稍后再试。您还可以问我其他问题。" |
| LLM 调用超时（>30s） | 返回已生成的 partial text + 截断提示 | "（已生成的推荐语）...\n\n回答被截断，请刷新重试。" |
| LLM 内容安全审核触发 | SSE 返回 error 事件，不暴露审核细节 | "抱歉，我无法回答这个问题。" |
| 检索结果为空（Milvus 正常但无结果） | LLM 告知用户扩大搜索范围 | "没有找到匹配的店铺，建议扩大搜索范围或换个关键词试试~" |
| HTTP 查券失败（Java 500/超时） | 仍返回店铺推荐，但省略券信息 | 店铺卡片显示但无券标签 |
| Redis 不可用 | 仅当前轮对话可用，历史丢失 | 连续对话可能丢失上下文，但本轮正常 |
| embedding API 超时 | 重试 1 次，仍失败 → 降级为纯文本匹配或直接报错 | "搜索服务暂时不可用"（与 Milvus 不可用统一） |
| 前端网络断开 | 显示重试按钮，重连携带 session_id | "连接断开，点击重试" |

## 技术要点

### Python 侧降级实现

**1. Milvus 健康检查 + 降级**
```python
# 在 retrieval.py 中
async def search_shops_with_fallback(query_embedding, filters=None):
    try:
        results = await milvus_client.search(...)
        return results, None
    except (ConnectionError, TimeoutError, MilvusException) as e:
        logger.warning(f"Milvus unavailable: {e}")
        return [], "milvus_unavailable"
```
- 在 graph 的 rec_node 中检测 fallback reason → 生成对应降级提示
- Milvus 恢复后自动恢复推荐功能

**2. LLM 超时控制**
```python
try:
    stream = await asyncio.wait_for(
        client.chat.completions.create(...),
        timeout=30.0
    )
except asyncio.TimeoutError:
    # 返回已生成的部分 + 截断提示
    yield _sse({"type": "text", "content": "\n\n[回答被截断，请刷新重试]"})
    yield _sse({"type": "done"})
```

**3. 内容安全兜底**
- 在 LLM 调用时捕获 content_filter 相关异常（OpenAI SDK 会抛）
- 统一返回 {"type": "error", "content": "抱歉，我无法回答这个问题"}

**4. 检索为空**
- 在 prompt 中明确指令："如果检索结果为空，告诉用户没有找到匹配的店铺，建议扩大搜索范围。严禁编造店铺。"
- 硬约束：检索结果作为唯一事实来源注入 prompt

**5. HTTP 查券失败**
```python
try:
    vouchers = await query_vouchers(shop_ids, user_id)
except Exception as e:
    logger.error(f"Voucher query failed: {e}")
    vouchers = {}  # 空 dict，店铺推荐照常但无券
```

**6. Redis 降级**
```python
try:
    history = await load_history(session_id)
except RedisError:
    history = []  # 空历史，本轮对话仍可用
```

### 前端降级实现

**7. 网络断开 + 重连**
```javascript
// useChat.js composable 中
let retrySessionId = null

async function sendMessage(query) {
  try {
    // ... normal fetch flow
    retrySessionId = null  // 成功后清除
  } catch (error) {
    retrySessionId = sessionId.value  // 保存 session_id 用于重试
    connectionError.value = true
  }
}

async function retry() {
  connectionError.value = false
  // 用同一个 session_id 重新请求
  await sendLastMessage()
}
```

**8. 加载状态**
- 发送中：输入框禁用 + 发送按钮显示 loading spinner
- AI 回复中（流式）：显示闪烁光标或"..."动画

### 全链路日志
- 所有异常日志携带 `session_id` + `user_id` + `error_type`
- 使用 Python `logging` 模块，JSON 格式输出
- 关键事件（PRD §13）：chat_session_start, chat_intent, chat_search, chat_error

## 需要修改的文件

- 修改 `agent-service/src/agent/retrieval.py` — Milvus 异常捕获 + 降级标记
- 修改 `agent-service/src/agent/nodes.py` — 各节点 try/except + 降级逻辑
- 修改 `agent-service/src/agent/chat.py` — LLM 超时 + 安全审核异常处理
- 修改 `agent-service/src/agent/voucher.py` — 查券异常降级
- 修改 `agent-service/src/agent/redis_history.py` — Redis 异常降级
- 修改 `vue3/src/views/ai/composables/useChat.js` — 断线重连 + 错误状态
- 修改 `vue3/src/views/ai/ChatView.vue` — 重试按钮 UI + loading 状态

## 验收标准

- [ ] Milvus 容器 stop → 发送"推荐火锅"→ 收到降级提示"搜索服务暂时不可用"，闲聊"你好"正常
- [ ] LLM API 设 5s 超时 → 收到 partial text + 截断提示
- [ ] 检索结果为空 → LLM 回复引导扩大搜索，不编造店铺名
- [ ] Java 查券接口返回 500 → 仍返回 shop_card，voucher 字段为 null
- [ ] Redis 容器 stop → 对话不崩溃，本轮消息正常，历史丢失
- [ ] 前端断网（浏览器 Network throttle Offline）→ 显示"连接断开，点击重试"按钮
- [ ] 重试按钮点击 → 网络恢复后正常续接对话
- [ ] 全链路异常日志包含 session_id + error_type

---

## 附录 A：配置项速查

### Python 环境变量（agent-service）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_BASE_URL` | — | LLM API 地址 |
| `LLM_API_KEY` | `sk-placeholder` | LLM API Key |
| `LLM_MODEL` | `gpt-4o-mini` | LLM 模型名 |
| `EMBEDDING_BASE_URL` | 同 LLM_BASE_URL | Embedding API 地址 |
| `EMBEDDING_API_KEY` | 同 LLM_API_KEY | Embedding API Key |
| `EMBEDDING_MODEL` | `doubao-embedding-text` | Embedding 模型名 |
| `EMBEDDING_DIM` | `1024` | 向量维度 |
| `MILVUS_HOST` | `localhost` | Milvus 地址 |
| `MILVUS_PORT` | `19530` | Milvus 端口 |
| `REDIS_HOST` | `localhost` | Redis 地址 |
| `REDIS_PORT` | `6379` | Redis 端口 |
| `REDIS_DB` | `0` | Redis DB |
| `JAVA_BASE_URL` | `http://localhost:8085` | Java 后端地址 |
| `SYNC_INTERNAL_TOKEN` | `internal-dev-token` | 服务间认证 Token |
| `IMAGE_BASE_PATH` | — | 店铺图片本地路径 |

### Java 配置项（application.yml）

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `sync.internal-token` | `${SYNC_INTERNAL_TOKEN:internal-dev-token}` | 服务间认证 Token |
| `agent-service.base-url` | `http://localhost:8000` | Python AI 服务地址 |

---

## 附录 B：与 PRD 的覆盖映射

| PRD 章节 | 对应步骤 |
|----------|---------|
| §4.1 单轮模糊推荐 | WS-05, WS-11 |
| §4.1 条件筛选 | WS-09 |
| §4.1 多轮追问+反选 | WS-06 |
| §4.1 闲聊兜底 | WS-04 |
| §4.1 自动下单+秒杀提醒 | WS-07 |
| §4.1 位置未授权 | WS-10 |
| §5.2 Milvus Collection | ✅ #6 已完成 |
| §5.3 Redis 对话历史 | WS-02 |
| §6.1 请求格式 | ✅ #10 已完成 |
| §6.2 对话处理流程 | WS-04 |
| §6.3 SSE 消息格式 | WS-11, WS-12 |
| §7.1 对话流式 | WS-03 |
| §7.2 数据同步 | ✅ #3, #4 已完成; WS-01 |
| §7.3 查券与下单 | WS-07, WS-11 |
| §8 前端对话页面 | WS-10, WS-12 |
| §9 降级与兜底 | WS-13 |
| §13 埋点 | WS-13（全链路日志）|

---

> **使用方式：** 每个 WS-XX 章节都是一个完整的 vibe coding 提示词。
> 复制该章节的全部内容（从"要构建什么"到"验收标准"），
> 粘贴给 AI coding agent 即可开始实现。
