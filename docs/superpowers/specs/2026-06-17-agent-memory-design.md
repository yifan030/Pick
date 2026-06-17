# Agent 三层记忆架构设计

> 2026-06-17 | brainstorming

## 背景

当前 agent 记忆方案：

| 组件 | 作用 | 问题 |
|------|------|------|
| `InMemorySaver` | LangGraph checkpoint | 进程重启即丢 |
| `redis_history.py` | 消息持久化到 Redis，TTL 30min | 手动序列化，非框架原生，超时蒸发 |
| 无 | 用户画像/偏好 | 完全缺失 |

## 目标

建立三层记忆架构，覆盖行业主流的 L1/L2/L3 模型：

```
L1 工作记忆: Context Window — 当前对话窗口内的消息
L2 短期记忆: PostgresSaver — 跨会话 checkpoint 持久化
L3 长期记忆: Milvus user_memory — 用户偏好/行为语义检索
```

## 架构总览

```
用户消息 → [L3: Milvus 检索(仅新会话)] → [@dynamic_prompt 注入] → [L1: Agent 执行]
                                                                          │
                                                                          ▼
                                                                 [L2: PostgresSaver 自动 checkpoint]
                                                                          │
                                                                          ▼
                                                                 [异步: Kafka → 小模型提取 → Milvus upsert]
```

### 各层职责

| 层 | 存储 | 生命周期 | 触发方式 |
|----|------|---------|---------|
| L1 工作记忆 | Context window + LangChain messages state | 单次请求 | LLM 自动管理 |
| L2 短期记忆 | Postgres (PostgresSaver) | 永久 | 框架每个节点自动 |
| L3 长期记忆 | Milvus `user_memory` collection | 永久 | 异步提取 + 新会话检索 |

## L2: PostgresSaver 替代 InMemorySaver + Redis

### 变更

- **删除** `agent-service/src/agent/memory/redis_history.py`
- **删除** `main.py` 中的 `load_history()`、`save_history()`、`_save_history_safe()` 调用
- **修改** `agent.py`: `InMemorySaver()` → `AsyncPostgresSaver.from_conn_string(DB_URI)`
- **修改** `main.py` `/chat` 端点：移除手动 history 管理，checkpoint 自动恢复
- **修改** `main.py` `/chat/resume` 端点：同上

### 效果

- 对话结束后无需手动保存，框架自动持久化 checkpoint
- 同一 `thread_id` 的会话跨进程重启自动恢复
- 序列化由框架 msgpack 处理，不再手写 `_serialize_messages` / `_deserialize_messages`

### 环境变量

```
PG_URI=postgres://user:pass@localhost:5432/pick_agent
```

## L3: 长期记忆（用户偏好/行为）

### Collection 设计

```
Milvus collection: user_memory
├── id (VARCHAR, primary)
├── user_id (VARCHAR, partition key)
├── content (VARCHAR, 记忆事实文本)
├── type (VARCHAR, "preference" | "behavior" | "fact")
├── content_embedding (FLOAT_VECTOR, dim=同现有)
├── created_at (INT64, unix timestamp)
└── updated_at (INT64, unix timestamp)
```

索引：HNSW on `content_embedding`，cosine 相似度。

### 记忆提取（异步）

```
对话结束 → agent.get_state(config) → 完整 messages
  → 序列化为 Kafka 消息
  → Kafka Consumer (Python agent 侧)
  → 小模型 (gpt-4o-mini 或更便宜) 提取 memory facts
  → embed_texts(fact.content)
  → Milvus upsert (user_memory collection)
```

Kafka topic: `agent.memory.extract`

消息格式：
```json
{
  "user_id": "u123",
  "session_id": "abc",
  "messages": [
    {"role": "user", "content": "我不吃辣..."},
    {"role": "assistant", "content": "推荐..."}
  ]
}
```

提取 prompt（用于小模型）：
```
从以下对话中提取用户偏好和行为事实，每条单独列出：
- type: preference / behavior / fact
- content: 简洁的事实描述

对话：
{messages}
```

提取结果示例：
```json
[
  {"type": "preference", "content": "用户不吃辣"},
  {"type": "preference", "content": "用户预算人均100以内"},
  {"type": "behavior", "content": "用户在春熙路附近搜索粤菜馆"}
]
```

### 记忆检索（新会话时触发一次）

```python
# /chat 端点
existing_state = agent.get_state(config)
has_existing = existing_state and existing_state.values.get("messages")

if not has_existing:
    # 仅新会话检索
    query_embedding = embed_texts([query])[0]
    memories = milvus.search(
        collection="user_memory",
        data=[query_embedding],
        filter=f'user_id == "{user_id}"',
        limit=5,
    )
    memory_context = "\n".join(f"- {m['entity']['content']}" for m in memories)
    system_prompt = SYSTEM_PROMPT + f"\n\n关于该用户:\n{memory_context}"
else:
    system_prompt = SYSTEM_PROMPT
```

检索后记忆注入 system prompt，后续 checkpoint 自动延续上下文，不重复检索。

### 记忆更新策略

- 当前阶段：append-only，不处理冲突
- 后续扩展：LLM 判断 update/delete + 相似度去重

## Kafka 集成

Python agent 侧新增 `aiokafka` 依赖：

```
# producer: main.py 流结束后发送记忆提取任务
# consumer: 独立进程或 asyncio task，消费提取任务
```

consumer 流程：
```
Kafka message → 小模型提取事实 → embed → Milvus upsert
```

错误处理：consumer 失败重试，不阻塞主对话流。

## Redis 去留

| 用途 | 决策 |
|------|------|
| 消息历史持久化 (`redis_history.py`) | **删除** |
| 限流（滑动窗口/令牌桶 Lua） | 保留 |
| Sa-Token 会话 | 保留 |
| 秒杀库存扣减 | 保留 |

Redis 从"记忆层"退回到"缓存/业务层"。

## 数据流总结

```
POST /chat
  ├── L3: 新会话? → Milvus search(user_id, query_embedding) → 注入 system prompt
  ├── L1: Agent 执行 (create_agent)
  ├── L2: PostgresSaver 自动 checkpoint (每个节点)
  └── L3 async: Kafka produce(记忆提取任务) → Consumer → 小模型 → Milvus upsert
```

## 实施阶段

| 阶段 | 内容 | 依赖 |
|------|------|------|
| Phase 0 | 搭建 Postgres 环境 | 运维 |
| Phase 1 | PostgresSaver 接入，删除 redis_history.py | PG 就绪 |
| Phase 2 | Milvus `user_memory` collection 创建 | — |
| Phase 3 | Kafka 记忆提取 producer/consumer | Kafka |
| Phase 4 | 新会话记忆检索 + system prompt 注入 | Phase 2 |

## 未解决问题

- **记忆冲突解决**：后续迭代，当前 append-only
- **Postgres 实例**：新建还是复用 Java 侧的 MySQL？建议新建 PG（LangGraph checkpoint 需要 PG，不兼容 MySQL）
- **Consumer 部署形态**：独立进程 vs asyncio background task？
