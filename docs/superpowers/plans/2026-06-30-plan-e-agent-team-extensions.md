# Plan E: Agent Team 协作扩展点预留

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有数据模型和接口层预留 Agent Team（Supervisor + Worker）所需的 4 个扩展字段，零实现成本，避免事后重构。

**Architecture:** 本计划仅修改数据模型定义和接口签名——不实现任何 Supervisor/Worker 逻辑。扩展点包括：Milvus `agent_case` collection 的 `case_type` 枚举新增 `"orchestration"`；Neo4j `SessionRef` 节点新增 `parent_thread_id` 属性；审计日志 `DeltaOperation` 新增 `agent_role` 字段；`PickAgentState` TypedDict 新增注释预留字段。

**Tech Stack:** Python dataclasses, Neo4j Cypher, LangGraph TypedDict

**Prerequisites:** Plan A（存储基础）已完成（`models.py`、`neo4j_client.py`、`agent.py` 均已存在）

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `agent-service/src/storage/models.py` | Modify | AgentCase `case_type` docstring + `DeltaOperation.agent_role` |
| `agent-service/src/storage/neo4j_client.py` | Modify | `write_session_ref` 签名新增 `parent_thread_id` |
| `agent-service/src/agent/agent.py` | Modify | `PickAgentState` 新增注释预留字段 |
| `agent-service/tests/storage/test_models.py` | Modify | 验证 `agent_role` 默认值和 audit dict 输出 |
| `agent-service/tests/storage/test_neo4j_client.py` | Modify | 验证 `parent_thread_id` 写入和读取 |

---

### Task E1: AgentCase `case_type` 枚举扩展 + DeltaOperation `agent_role` 字段

**Files:**
- Modify: `agent-service/src/storage/models.py:237`
- Modify: `agent-service/src/storage/models.py:266-284`

- [ ] **Step 1: 扩展 `AgentCase.case_type` 的文档字符串**

在 `models.py` 第 237 行，将 `case_type` 的注释从 4 个枚举值扩展为 5 个：

```python
case_type: str            # "recommendation" | "purchase_flow" | "error_recovery" | "user_handling" | "orchestration"
```

`"orchestration"` 在 Phase 6（AgentCaseExtractor）不产出，但 Schema 允许，未来 Phase 18 平滑接入。

- [ ] **Step 2: 为 `DeltaOperation` 新增 `agent_role` 字段**

在 `models.py` 的 `DeltaOperation` dataclass（约第 266 行）中新增 `agent_role` 字段：

```python
@dataclass
class DeltaOperation:
    """A single memory delta produced by the Profile Updater."""
    op: str                   # ADD | REINFORCE | REVISE | DELETE | MERGE | NOCHANGE | EXPIRE
    target_type: str
    target_id: str | None = None
    old_value: AnyProfile | None = None
    new_value: AnyProfile | None = None
    reason: str = ""
    agent_role: str = "main"  # "main" | "supervisor" | "worker:restaurant" | ...

    def to_audit_dict(self) -> dict:
        return {
            "op": self.op,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "old_value": _profile_to_dict(self.old_value),
            "new_value": _profile_to_dict(self.new_value),
            "reason": self.reason,
            "agent_role": self.agent_role,
        }
```

当前所有调用方不传 `agent_role`，默认 `"main"`——与现有行为完全兼容。

- [ ] **Step 3: 运行现有测试确认无回归**

```bash
cd agent-service && python -m pytest tests/storage/test_models.py -v
```

Expected: 所有已有测试 PASS（`agent_role` 有默认值，不破坏现有断言）。

- [ ] **Step 4: 补充测试用例**

在 `tests/storage/test_models.py` 中新增测试：

```python
def test_delta_operation_default_agent_role():
    """agent_role defaults to 'main' for backward compatibility."""
    delta = DeltaOperation(
        op="ADD",
        target_type="CuisinePreference",
        new_value=CuisinePreference(user_id="u1", cuisine="川渝火锅"),
    )
    assert delta.agent_role == "main"

    audit = delta.to_audit_dict()
    assert audit["agent_role"] == "main"


def test_delta_operation_custom_agent_role():
    """agent_role can be set for supervisor/worker scenarios."""
    delta = DeltaOperation(
        op="ADD",
        target_type="CuisinePreference",
        agent_role="worker:restaurant",
        new_value=CuisinePreference(user_id="u1", cuisine="粤菜"),
    )
    assert delta.agent_role == "worker:restaurant"

    audit = delta.to_audit_dict()
    assert audit["agent_role"] == "worker:restaurant"
```

- [ ] **Step 5: 运行测试确认通过**

```bash
cd agent-service && python -m pytest tests/storage/test_models.py -v -k "test_delta"
```

Expected: 2 new tests PASS.

- [ ] **Step 6: Commit**

```bash
git add agent-service/src/storage/models.py agent-service/tests/storage/test_models.py
git commit -m "feat: add 'orchestration' to AgentCase case_type + agent_role to DeltaOperation"
```

---

### Task E2: Neo4j `SessionRef` 新增 `parent_thread_id` 属性

**Files:**
- Modify: `agent-service/src/storage/neo4j_client.py:297-321`

- [ ] **Step 1: 扩展 `write_session_ref` 方法签名和 Cypher 查询**

将 `write_session_ref` 方法（约第 297 行）修改为：

```python
async def write_session_ref(
    self,
    user_id: str,
    session_id: str,
    shop_ids: list[str],
    parent_thread_id: str | None = None,
) -> None:
    """Create a SessionRef node and link to mentioned shops.

    Args:
        parent_thread_id: 未来 Supervisor 拆解任务时，Worker 子任务的
                          parent_thread_id 指向 Supervisor 的 session_id。
                          当前始终为 None（单 Agent 模式）。
    """
    async with self.driver.session() as session:
        await session.run(
            """
            MERGE (u:User {user_id: $user_id})
            MERGE (sr:SessionRef {session_id: $session_id})
            SET sr.user_id = $user_id, sr.parent_thread_id = $parent_thread_id
            MERGE (u)-[:HAS_SESSION]->(sr)
            """,
            user_id=user_id,
            session_id=session_id,
            parent_thread_id=parent_thread_id,
        )
        for shop_id in shop_ids:
            await session.run(
                """
                MATCH (sr:SessionRef {session_id: $session_id})
                MERGE (s:Shop {shop_id: $shop_id})
                MERGE (sr)-[:MENTIONED]->(s)
                """,
                session_id=session_id,
                shop_id=shop_id,
            )
```

关键变更：
- 签名新增 `parent_thread_id: str | None = None`
- Cypher SET 子句新增 `sr.parent_thread_id = $parent_thread_id`
- Neo4j 中不存在的属性设为 null，不增加存储开销

- [ ] **Step 2: 检查现有调用方是否兼容**

搜索所有调用 `write_session_ref` 的位置：

```bash
cd agent-service && rg "write_session_ref" --type py
```

Expected: 现有调用方不传 `parent_thread_id`，利用默认值 `None`，零破坏。

- [ ] **Step 3: 补充测试用例**

在 `tests/storage/test_neo4j_client.py` 中新增测试：

```python
@pytest.mark.integration
async def test_write_session_ref_with_parent_thread_id(neo4j_client):
    """SessionRef stores parent_thread_id when provided."""
    await neo4j_client.write_session_ref(
        user_id="u_test",
        session_id="sess_parent",
        shop_ids=["shop_1"],
    )
    # Verify default null
    async with neo4j_client.driver.session() as session:
        result = await session.run(
            "MATCH (sr:SessionRef {session_id: 'sess_parent'}) RETURN sr.parent_thread_id AS ptid"
        )
        record = await result.single()
        assert record["ptid"] is None

    # Write child with parent reference
    await neo4j_client.write_session_ref(
        user_id="u_test",
        session_id="sess_child",
        shop_ids=["shop_2"],
        parent_thread_id="sess_parent",
    )
    async with neo4j_client.driver.session() as session:
        result = await session.run(
            "MATCH (sr:SessionRef {session_id: 'sess_child'}) RETURN sr.parent_thread_id AS ptid"
        )
        record = await result.single()
        assert record["ptid"] == "sess_parent"

    # Cleanup
    async with neo4j_client.driver.session() as session:
        await session.run("MATCH (sr:SessionRef) WHERE sr.session_id IN ['sess_parent', 'sess_child'] DETACH DELETE sr")
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd agent-service && python -m pytest tests/storage/test_neo4j_client.py -v -k "parent_thread_id"
```

Expected: 1 new test PASS.

- [ ] **Step 5: Commit**

```bash
git add agent-service/src/storage/neo4j_client.py agent-service/tests/storage/test_neo4j_client.py
git commit -m "feat: add parent_thread_id to SessionRef for future Supervisor worker threads"
```

---

### Task E3: `PickAgentState` 预留子任务和候选记忆字段

**Files:**
- Modify: `agent-service/src/agent/agent.py:59-68`

- [ ] **Step 1: 在 `PickAgentState` 中新增注释预留字段**

将 `PickAgentState`（第 59-68 行）修改为：

```python
class PickAgentState(TypedDict):
    """Shared state across the Pick agent graph.

    messages: conversation history, merged via add_messages reducer.
    intent:   classified user intent – set by classify_intent node,
              read by the conditional routing edge.

    Reserved for future Supervisor + Worker multi-agent (Phase 15+):
      sub_tasks:              Supervisor 拆解的子任务列表
      candidate_memory_deltas: Worker 返回的候选记忆变更列表
    """

    messages: Annotated[list, add_messages]
    intent: str  # "recommend_shop" | "chat" | "purchase"

    # === 预留：多 Agent 协作（Phase 15+） ===
    # sub_tasks: list[dict]           # Supervisor 拆解的子任务列表
    # candidate_memory_deltas: list   # Worker 返回的候选记忆变更
```

注意：注释掉的字段不会出现在 TypedDict 的运行时行为中，对现有代码零影响。

- [ ] **Step 2: 验证 `agent.py` 语法正确性**

```bash
cd agent-service && python -c "from src.agent.agent import PickAgentState, create_pick_agent; print('OK')"
```

Expected: `OK`，无 ImportError 或 SyntaxError。

- [ ] **Step 3: Commit**

```bash
git add agent-service/src/agent/agent.py
git commit -m "feat: reserve sub_tasks and candidate_memory_deltas fields in PickAgentState"
```

---

## Self-Review

### 1. Spec Coverage

| Spec 扩展点 | 对应任务 | 状态 |
|---|---|---|
| Milvus `agent_case` — `case_type` 新增 `"orchestration"` | Task E1 Step 1 | ✅ |
| Neo4j `SessionRef` — 新增 `parent_thread_id` | Task E2 | ✅ |
| 审计日志 `memory_diff.json` — 新增 `agent_role` | Task E1 Step 2 | ✅ |
| `PickAgentState` — state schema 预留字段 | Task E3 | ✅ |

### 2. Placeholder Scan

无 TBD/TODO/占位符。所有步骤包含具体代码和命令。

### 3. Type Consistency

- `agent_role` 在 `DeltaOperation` 中定义为 `str = "main"`，在 `to_audit_dict()` 中通过 `self.agent_role` 引用 → 一致
- `parent_thread_id` 在 `write_session_ref` 签名中为 `str | None = None`，在 Cypher 中通过 `$parent_thread_id` 传递 → 一致
- `PickAgentState` 的注释字段名 `sub_tasks` / `candidate_memory_deltas` 与 spec 第 162-163 行一致
