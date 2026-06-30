# Agent Team 协作设计

> 2026-06-30 | brainstorming | 基于 2026-06-29 agent-memory-redesign 的补充

## 背景

`2026-06-29-agent-memory-redesign.md` 定义了单 Agent + 单用户的记忆系统。本文档在此基础上设计 Supervisor + Worker 多 Agent 协作模式，明确：

- Supervisor 与 Worker 之间的记忆传递策略
- Worker 执行过程中的记忆回写机制
- 对当前记忆系统的扩展点（预留但不立即实现）
- 未来落地的实施阶段

**核心原则**：单 Agent 记忆系统先落地（Phase 1-14），多 Agent 编排作为独立后续迭代。但在数据模型和接口层预留扩展空间，避免事后重构。

## 协作模式

### 拓扑

```
                        ┌─────────────────────────┐
                        │       Supervisor          │
                        │                           │
                        │  • 接收用户复合请求        │
                        │  • 全量检索用户记忆         │
                        │  • 规划 & 拆解子任务       │
                        │  • 按需裁剪记忆 → Worker   │
                        │  • 汇总 Worker 结果        │
                        │  • 统一回写记忆变更        │
                        │  • 合成最终回复            │
                        └─────┬───────┬───────┬─────┘
                              │       │       │
                    ┌─────────┘       │       └─────────┐
                    ▼                 ▼                 ▼
             ┌──────────┐    ┌──────────┐    ┌──────────┐
             │ Worker A  │    │ Worker B  │    │ Worker C  │
             │ (餐厅推荐) │    │ (KTV搜索)  │    │ (券查询)   │
             │           │    │           │    │           │
             │ 裁剪记忆:  │    │ 裁剪记忆:  │    │ 裁剪记忆:  │
             │ Cuisine   │    │ Area      │    │ Budget    │
             │ Taste     │    │ Scene     │    │ Voucher   │
             │ Budget    │    │           │    │           │
             └──────────┘    └──────────┘    └──────────┘
```

### 与单 Agent StateGraph 的关系

| | 当前（Phase 1-14） | 未来（Phase 15+） |
|---|---|---|
| 图拓扑 | 单图三路由：classify → chat/recommend/purchase | Supervisor 图 + 动态 Worker 子图 |
| 意图处理 | 路由到一个 handler | Supervisor 拆解为 N 个子任务 |
| 记忆检索 | 新会话三路检索 | Supervisor 执行（一次性），按需裁剪给 Worker |
| 记忆回写 | MemoryExtractor 异步写入 | Supervisor 汇总 Worker candidate_delta → 消重 → 统一写入 |

### 记忆传递策略：Supervisor 按需裁剪

Worker **不**自己调 Retrieval Gateway。Supervisor 在分派任务时明确指定记忆子集：

```
Supervisor → Worker A (餐厅推荐):
  注入记忆:
    ### 用户偏好
    - [口味] 不吃辣 (置信度:0.9)
    - [菜系] 川渝火锅 (置信度:0.85)
    - [预算] 人均50-100 (置信度:0.7)
    - [饮食约束] 清真 (硬约束, 置信度:1.0)

Supervisor → Worker B (KTV搜索):
  注入记忆:
    ### 用户偏好
    - [商圈] 春熙路 (置信度:0.8)
    - [场景] 朋友聚餐 (置信度:0.7)
    - [预算] 人均50-100 (置信度:0.7)
```

裁剪原则：
- Profile（≤30 条）：全量注入 Supervisor 自身，由 Supervisor 按任务类型裁剪后分发
- 硬约束（DietaryPreference, is_hard=true）：**始终注入所有 Worker**（遗漏后果严重）
- Event/Session：Supervisor 检索后提取与子任务相关的条目，按相关性分发
- 每个 Worker 只拿到自己需要的最小记忆子集 → 降低 Worker 调用的 token 消耗

### 记忆回写：Supervisor 统一汇总

Worker 执行完成后，将"候选记忆变更"随结果返回 Supervisor：

```
Worker A 返回格式:
{
  "result": "推荐了蜀大侠火锅...",
  "candidate_memory_deltas": [
    {
      "op": "ADD",
      "target_type": "ConstraintPreference",
      "new_value": {"constraint": "不吃牛肉", "confidence": 0.6},
      "reason": "用户明确表示不吃牛肉",
      "source_worker": "worker:restaurant"
    }
  ]
}
```

Supervisor 汇总所有 Worker 的 candidate_delta：
1. **消重**：多个 Worker 可能独立发现同一个偏好变更
2. **冲突解决**：如果 Worker-A 的 delta 与 Worker-B 的 delta 矛盾，Supervisor 做最终判断
3. **统一写入**：调用 MemoryExtractor 执行 Neo4j + Milvus 写入
4. **审计日志**：所有变更写入 `memory_diff.json`，标记 `agent_role: "supervisor"`

由于所有写入经过 Supervisor 单点，天然避免并发冲突。

### 冲突消解

| 场景 | 处理 |
|------|------|
| 两个 Worker 独立 ADD 同一个约束 | Supervisor 去重，取第一个 |
| Worker-A ADD "爱吃辣"，Worker-B 从旧对话推断 "不吃辣" | Supervisor 对比置信度 + 时间，高置信度 + 更新近的优先，标记另一方为 REVISE |
| Worker 返回的 delta 与已有 Profile 矛盾 | 与现有冲突处理矩阵一致：REVISE 旧 / ADD 新 |

## 对当前记忆系统的扩展点

以下预留**零额外实现成本**——只在数据模型定义阶段顺手加上：

### Milvus `agent_case` — 新增 `case_type` 枚举值

```diff
- case_type: "recommendation" | "purchase_flow" | "error_recovery" | "user_handling"
+ case_type: "recommendation" | "purchase_flow" | "error_recovery" | "user_handling" | "orchestration"
```

`orchestration` 在 Phase 6 实现 AgentCaseExtractor 时不产出，但 Schema 允许，未来平滑接入。

### Neo4j `SessionRef` — 新增 `parent_thread_id`

```
SessionRef {
  session_id: VARCHAR,
+ parent_thread_id: VARCHAR | null,  // 当前始终 null
  ...
}
```

未来 Supervisor 拆解任务时，Worker 子任务的 `parent_thread_id` 指向 Supervisor 的 `session_id`。不增加查询复杂度——加字段加索引即可。

### 审计日志 `memory_diff.json` — 新增 `agent_role`

```diff
{
  "timestamp": "...",
  "user_id": "u123",
  "session_id": "sess_abc",
+ "agent_role": "main",  // 当前固定 "main"，未来 "supervisor" | "worker:restaurant" | ...
  "operations": [...]
}
```

### `PickAgentState` — state schema 预留

```python
class PickAgentState(TypedDict):
    messages: Annotated[list, add_messages]
    intent: str
    # 预留（未来实现）:
    # sub_tasks: list[dict]           # Supervisor 拆解的子任务列表
    # candidate_memory_deltas: list   # Worker 返回的候选记忆变更
```

这些字段在当前单 Agent 模式下不使用，不影响任何逻辑。

## Supervisor 自身的记忆：AgentCase `orchestration`

Supervisor 的编排决策作为一种经验存入 `agent_case` collection（复用现有字段）：

| AgentCase 字段 | 编排场景 |
|---|---|
| `case_type` | `"orchestration"` |
| `description` | "用户请求'周五约会规划'，拆解为餐厅推荐 + KTV 搜索，用户满意" |
| `context` | `{original_query, available_workers, constraints}` |
| `action` | `{decomposition: [{task, worker, priority}], strategy: "parallel"}` |
| `outcome` | `"success"` |
| `outcome_reason` | "两个 Worker 结果互补，用户点击了推荐餐厅" |
| `lesson` | "类似'约会规划'请求拆 2 个 Worker 足够，拆 3 个用户觉得信息过载" |

这些编排经验进入三路检索管道，Supervisor 在未来会话中能检索到"上次类似请求我是怎么拆的"。

## 未来实施阶段

| 阶段 | 内容 | 依赖 |
|------|------|------|
| Phase 15 | PickAgentState 扩展 + Supervisor 图构建（含动态 Send fan-out） | Phase 14（记忆系统完整落地） |
| Phase 16 | 记忆路由实现（Supervisor 裁剪逻辑） | Phase 15 |
| Phase 17 | Worker candidate_delta 协议 + Supervisor 汇总回写 | Phase 15, 16 |
| Phase 18 | AgentCase `orchestration` Extractor | Phase 17 |
| Phase 19 | 多 Agent 集成测试 + 记忆传递正确性验证 | Phase 18 |

## 设计决策总结

| 决策 | 选择 | 原因 |
|------|------|------|
| 协作模式 | Supervisor + Worker | 适合"复合请求拆解"场景，Supervisor 单一写入者避免并发冲突 |
| 记忆传递给 Worker | Supervisor 按需裁剪 | 降低 Worker token 消耗，硬约束始终全量注入 |
| 记忆回写路径 | Worker → Supervisor 汇总 → MemoryExtractor 统一写入 | 单点写入避免冲突，Supervisor 全局视角消重 |
| Supervisor 自身记忆 | 复用 AgentCase + `case_type: "orchestration"` | 不新增独立 memory type，现有字段自然映射 |
| 当前 StateGraph | 不做改动 | 单 Agent 记忆系统先跑通，两件事解耦 |
| 扩展点策略 | 数据模型 + 审计日志预留字段，零实现成本 | 避免事后重构，但不增加 Phase 1-14 工作量 |
