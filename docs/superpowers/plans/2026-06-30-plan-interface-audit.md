# Plan A–E 接口连通性审计

> 2026-06-30 | 代码审计 | 基于当前 `agent-service/src/` 实际代码

## 审计结论

**Plan A/B/C/D 代码层接口已全部打通，所有组件已在 `main.py` lifespan 中接入。存在 3 个阻断性问题需修复后整条链路才能跑通。Plan E 扩展点已回退需恢复。**

---

## 一、文件清单

### Plan A — 存储基础

| 文件 | 状态 | 说明 |
|------|------|------|
| `storage/models.py` | ✅ 存在 | ProfileBase + 7 种子类型, MemoryEvent, SessionSummary, AgentCase, DeltaOperation |
| `storage/neo4j_client.py` | ✅ 存在 | 完整 CRUD + subgraph_search + get_profiles_by_trace + delete_all_profiles |
| `storage/milvus_store.py` | ✅ 存在 | 3 个 collection + HNSW/SPARSE index + insert/search/delete |
| `storage/postgres_saver.py` | ✅ 存在 | PostgresSaverManager |
| `storage/embedding.py` | ✅ 存在 | embed_texts + embed_single，独立的 OpenAI-compatible 客户端 |

### Plan B — 记忆写入管道

| 文件 | 状态 | 说明 |
|------|------|------|
| `memory/pipeline.py` | ✅ 存在 | 6 步编排：extract → embed → pre-filter → profile update → summarize → case extract |
| `memory/extractor.py` | ✅ 存在 | EventExtractor：对话回合 → MemoryEvent |
| `memory/pre_filter.py` | ✅ 存在 | VectorPreFilter：语义相似度筛选已有 Profile |
| `memory/profile_updater.py` | ✅ 存在 | ProfileUpdater：LLM delta 计算 + Neo4j 写入 |
| `memory/session_summarizer.py` | ✅ 存在 | SessionSummarizer：每 3 轮增量摘要 |
| `memory/agent_case_extractor.py` | ✅ 存在 | AgentCaseExtractor：推荐结果 → AgentCase |
| `memory/audit.py` | ✅ 存在 | AuditLogger：memory_diff.jsonl |
| `memory/consolidation.py` | ✅ 存在 | ConsolidationJob：Profile 去重合并 |
| `memory/cleanup.py` | ✅ 存在 | CleanupJob：TTL 过期 + Event 压缩 + 防膨胀 |
| `memory/prompts.py` | ✅ 存在 | 全部 LLM prompt 模板 |

### Plan C — 记忆读取管道

| 文件 | 状态 | 说明 |
|------|------|------|
| `retrieval/gateway.py` | ✅ 存在 | RetrievalGateway：三路检索编排 + 冷启动检测 |
| `retrieval/semantic_search.py` | ✅ 存在 | SemanticSearch：Milvus dense HNSW/COSINE |
| `retrieval/bm25_search.py` | ✅ 存在 | BM25Search：Milvus sparse SPARSE_INVERTED_INDEX |
| `retrieval/entity_boost.py` | ✅ 存在 | EntityBoost：Neo4j 子图遍历 + 实体提取 |
| `retrieval/fusion.py` | ✅ 存在 | ScoreNormalizer + RankFusion (0.45/0.25/0.30) |
| `retrieval/prompt_builder.py` | ✅ 存在 | PromptBuilder：记忆注入 system prompt |
| `retrieval/feedback.py` | ✅ 存在 | FeedbackProcessor：5 种用户行为信号 |
| `retrieval/consistency.py` | ✅ 存在 | ConsistencyChecker：双写一致性 + dead-letter |

### Plan D — 补充能力

| 文件 | 状态 | 说明 |
|------|------|------|
| `memory/cold_start.py` | ✅ 存在 | ColdStartManager：冷启动检测 + 行为导入 + onboarding |
| `memory/user_control.py` | ✅ 存在 | MemoryControlHandler：查看/删除/修正/清除记忆 |
| `memory/feedback_fallback.py` | ✅ 存在 | detect_implicit_feedback()：对话上下文感知反馈 |
| `retrieval/feedback_consumer.py` | ✅ 存在 | FeedbackConsumer：Kafka 消费 → Neo4j Profile 更新 |
| `agent/tools/memory_tools.py` | ✅ 存在 | 5 个 LangChain 工具：查看/删除/修改/清除/临时忽略 |
| `eval/run_eval.py` | ✅ 存在 | 离线质量评估脚本 |
| `eval/data/scenarios.json` | ✅ 存在 | 标注评估数据（3 条场景） |

---

## 二、main.py 接入矩阵

```
lifespan() 启动顺序:
  ┌─────────────────────────────────────────────────────┐
  │ PostgresSaverManager.setup()                  ✅    │
  │ neo4j_client = None                           ❌    │  ← TODO 未实现
  │ ColdStartManager(neo4j=None)                  ⚠️    │
  │ MemoryControlHandler(neo4j=None)              ⚠️    │
  │ create_pick_agent(                            ✅    │
  │   checkpointer=saver,                               │
  │   memory_control_handler=memory_control,            │
  │   neo4j_client=neo4j_client)                        │
  │ RetrievalGateway(                             ⚠️    │  ← 条件跳过: if neo4j else None
  │   milvus=None, cold_start=cold_start_mgr)           │
  │ MemoryPipeline(neo4j=None, milvus=None)       ⚠️    │
  │ FeedbackConsumer.start()                      ⚠️    │  ← Kafka 不可用时 warn
  └─────────────────────────────────────────────────────┘
```

---

## 三、阻断性问题

### P0-1: `to_milvus_dict()` 方法缺失

**位置**: `storage/models.py` vs `storage/milvus_store.py`

`MemoryEvent`、`SessionSummary`、`AgentCase` 三个 dataclass 没有 `to_milvus_dict()` 方法，但 `milvus_store.py` 的 insert 方法直接调用：

```python
# milvus_store.py:192
data = event.to_milvus_dict()    # AttributeError!

# milvus_store.py:204
data = session.to_milvus_dict()  # AttributeError!

# milvus_store.py:216
data = case.to_milvus_dict()     # AttributeError!
```

**影响**: Plan B `MemoryPipeline` 步骤 2（embed + insert event）运行时 crash。

**修复方向**: 在 `models.py` 的三个类上添加 `to_milvus_dict()` 方法，将 dataclass 字段序列化为 Milvus insert 所需的 dict 格式（含 `json.dumps` 处理嵌套字段）。

---

### P0-2: Neo4jClient + MilvusMemoryStore 未初始化

**位置**: `main.py:99-100`, `main.py:122-123`

```python
# main.py:99
# TODO: Initialize Neo4jClient from Plan A (env vars NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)
neo4j_client = None

# main.py:122-123
_retrieval_gateway = RetrievalGateway(
    milvus_store=None,  # TODO: wire MilvusMemoryStore from Plan A
    ...
)
```

**影响**:
- `_retrieval_gateway` = `None`（line 126 条件 `if neo4j_client else None`）→ Plan C 检索从不执行
- `MemoryPipeline` 收到 `None` → 内部 null-guard 不 crash 但全部空转
- `ColdStartManager` / `MemoryControlHandler` / `FeedbackConsumer` 全部收到 `None`

**修复方向**: 在 lifespan 中恢复 Neo4jClient + MilvusMemoryStore 的初始化代码（从 git history `355ff0d` 或更早版本恢复）。

---

### P1-1: `source` 字段静默丢失

**位置**: `storage/models.py:ProfileBase` vs `memory/cold_start.py`

`cold_start.py` 在 5 处设置 `p.source = "behavior_import"`，但 `ProfileBase` dataclass 没有 `source` 字段：

```python
# cold_start.py:147, 160, 176, 189, 207
p.source = "behavior_import"
```

Python dataclass 允许动态赋值不报错，但 `_profile_to_neo4j_props()` 只遍历 `fields()` 列表中声明的字段 → `source` 不会写入 Neo4j。

**修复方向**: 在 `ProfileBase` 中添加 `source: str = "agent"` 字段。

---

### P1-2: `get_profiles_by_trace` 精度不足

**位置**: `storage/neo4j_client.py:203-223`

当前实现：查 `EventRef` → 取 `user_id` → 返回该用户**全部** Profile。而非只返回该次推荐实际引用的 Profile。

`FeedbackConsumer` 调用它时会对用户全部 Profile 做 REINFORCE，而非精准强化被引用的 Profile。

**修复方向**: 在 shop_card SSE 事件中携带 `referenced_profiles` 列表，`FeedbackConsumer` 基于此列表精准更新。

---

## 四、Plan E 扩展点（已回退，需恢复）

以下扩展点在上一个版本中存在，当前代码中已移除：

| 扩展点 | 文件 | 需恢复内容 |
|--------|------|-----------|
| `DeltaOperation.agent_role` | `models.py:DeltaOperation` | 添加 `agent_role: str = "main"` 字段 + `to_audit_dict()` 输出 |
| `write_session_ref.parent_thread_id` | `neo4j_client.py:write_session_ref` | 签名添加 `parent_thread_id: str\|None = None` + Cypher SET 子句 |
| `AgentCase.case_type` 枚举 | `models.py:AgentCase` | 注释从 `"recommendation"` 扩展为 `"recommendation" \| "purchase_flow" \| "error_recovery" \| "user_handling" \| "orchestration"` |
| `ProfileRef` 类 | `neo4j_client.py` | 恢复轻量引用类供 FeedbackConsumer 使用 |

**仍保留的扩展点**:

| 扩展点 | 文件 | 状态 |
|--------|------|------|
| `PickAgentState` 预留字段 | `agent.py:74-76` | ✅ 注释保留 `sub_tasks` / `candidate_memory_deltas` |

---

## 五、已修复问题（vs 上一轮审计）

| 问题 | 修复方式 |
|------|---------|
| `embed_single` 不存在 → `semantic_search.py` ImportError | `storage/embedding.py` 自己实现 `embed_single()` |
| `_save_history_safe()` 调用不存在的函数 | 调用已删除，改用 PostgresSaver 自动持久化 |
| `chat/resume` 中 `load_history` 未导入 | 引用已删除，改用 PostgresSaver checkpoint |
| `assistant_response=""` 硬编码 | SSE 流中累积 text token |
| `round_index=1` 硬编码 | `_round_tracker` 字典按 session 跟踪 |
| `redis_history` import + 调用残留 | 全部清理 |
| `delete_all_profiles` 方法缺失 | 已实现于 `neo4j_client.py:154` |

---

## 六、接口连通性详细矩阵

### Plan A → Plan B

| Plan A 接口 | Plan B 调用方 | 代码连通 | 运行时 |
|---|---|---|---|
| `Neo4jClient.write_profile()` | `ProfileUpdater._apply_single()` | ✅ | ❌ neo4j=None |
| `Neo4jClient.read_profiles()` | `VectorPreFilter.filter()` | ✅ | ❌ neo4j=None |
| `Neo4jClient.update_profile()` | `ProfileUpdater._apply_single()` | ✅ | ❌ neo4j=None |
| `Neo4jClient.delete_profile()` | `ProfileUpdater._apply_single()` | ✅ | ❌ neo4j=None |
| `Neo4jClient.get_hard_constraints()` | `VectorPreFilter.filter()` | ✅ | ❌ neo4j=None |
| `MilvusMemoryStore.insert_event()` | `MemoryPipeline.extract_memories()` | ❌ | to_milvus_dict crash |
| `MilvusMemoryStore.insert_session()` | `MemoryPipeline.extract_memories()` | ❌ | to_milvus_dict crash |
| `MilvusMemoryStore.insert_agent_case()` | `MemoryPipeline.extract_memories()` | ❌ | to_milvus_dict crash |
| `MilvusMemoryStore.search_dense()` | `VectorPreFilter.filter()` | ✅ | ❌ milvus=None |
| `embedding.embed_texts()` | `MemoryPipeline`, `VectorPreFilter` | ✅ | ✅ |

### Plan A → Plan C

| Plan A 接口 | Plan C 调用方 | 代码连通 | 运行时 |
|---|---|---|---|
| `MilvusMemoryStore.search_dense()` | `SemanticSearch.search()` | ✅ | ❌ milvus=None |
| `MilvusMemoryStore.search_sparse()` | `BM25Search.search()` | ✅ | ❌ milvus=None |
| `Neo4jClient.read_profiles()` | `EntityBoost.search()` | ✅ | ❌ neo4j=None |
| `Neo4jClient.get_hard_constraints()` | `EntityBoost.search()` | ✅ | ❌ neo4j=None |
| `Neo4jClient.subgraph_search()` | `EntityBoost.search()` | ✅ | ❌ neo4j=None |
| `embedding.embed_single()` | `SemanticSearch.search()` | ✅ | ✅ |

### Plan A → Plan D

| Plan A 接口 | Plan D 调用方 | 代码连通 | 运行时 |
|---|---|---|---|
| `Neo4jClient.read_profiles()` | `ColdStartManager.is_cold_start()`, `MemoryControlHandler.view_memories()` | ✅ | ❌ neo4j=None |
| `Neo4jClient.write_profile()` | `ColdStartManager.run_behavior_import()` | ✅ | ❌ neo4j=None |
| `Neo4jClient.delete_profile()` | `MemoryControlHandler.delete_memory()` | ✅ | ❌ neo4j=None |
| `Neo4jClient.delete_all_profiles()` | `MemoryControlHandler.clear_all_memories()` | ✅ | ❌ neo4j=None |
| `Neo4jClient.get_profiles_by_trace()` | `FeedbackConsumer.process_event()` | ✅ | ❌ neo4j=None |
| `Neo4jClient.update_profile()` | `FeedbackConsumer.process_event()` | ✅ | ❌ neo4j=None |

---

## 七、修复优先级

| 优先级 | 问题 | 预计工作量 |
|--------|------|-----------|
| **P0** | 初始化 Neo4jClient + MilvusMemoryStore（main.py:99-100, 122-123） | 15 行代码 |
| **P0** | 恢复 `to_milvus_dict()` 方法（models.py 三个类） | 30 行代码 |
| **P1** | ProfileBase 添加 `source` 字段 | 1 行 |
| **P2** | 恢复 Plan E 4 个扩展点 | 20 行代码 |
| **P3** | `get_profiles_by_trace` 精度优化 | 依赖 Phase 13c trace→profile 链路 |

---

## 八、Plan 文档与实际代码差异

| 差异点 | Plan 文档描述 | 实际代码 |
|--------|-------------|---------|
| `ProfileBase.source` | 未明确定义（各子类型隐含） | 不存在，cold_start 动态赋值会丢失 |
| `DeltaOperation.agent_role` | Plan E 要求存在 | 已删除 |
| `write_session_ref.parent_thread_id` | Plan E 要求存在 | 已删除 |
| `MemoryEvent.to_milvus_dict()` | 未描述 | 不存在 |
| `SessionSummary.to_milvus_dict()` | 未描述 | 不存在 |
| `AgentCase.to_milvus_dict()` | 未描述 | 不存在 |
| `MemoryEvent.id` 生成 | Plan A: `hashlib.md5(...)` | 当前: `uuid.uuid4().hex[:16]` |
| `ProfileRef` 类 | Plan A 定义了，FeedbackConsumer 依赖 | 已删除，改用 AnyProfile |
| `delete_all_profiles` | Plan D 需要，Plan A 未定义 | 已实现 |
| `get_profiles_by_trace` | Plan D 需要，Plan A 定义了 ProfileRef 版本 | 已重写为 AnyProfile 版本 |
