# Agent 记忆系统重设计

> 2026-06-29 | brainstorming | 基于 mem0 + VikingMem 调研 | v2 修订

## 修订记录

v2 (2026-06-29) 基于 mem0 + VikingMem 深度调研的修订：
- 新增显式 Delete 操作和 TTL 硬过期（mem0）
- 新增 Vector Pre-Filter + 审计日志（VikingMem）
- 新增 Agent 侧记忆类型（VikingMem cases/patterns）
- 新增 Profile Consolidation 合并模式（mem0）
- 改进衰减公式：加入强化次数因子
- 新增 DietaryPreference 类型（硬约束，区别于口味偏好）
- Rank Fusion 增加归一化步骤说明
- 补充 Neo4j+Milvus 双写一致性讨论
- 新增记忆质量反馈闭环

---

## 背景

当前 agent 记忆方案：

| 组件 | 作用 | 问题 |
|------|------|------|
| `InMemorySaver` | LangGraph checkpoint | 进程重启即丢 |
| `redis_history.py` | 消息持久化到 Redis，TTL 30min | 手动序列化，非框架原生，超时蒸发 |
| 无 | 用户画像/偏好 | 完全缺失 |

调研了 mem0 和 VikingMem（VLDB 2026 论文）的记忆系统设计，决定完整重构：
- 采纳 VikingMem 的 Profile/Event/Session + Agent Cases/Patterns 五类结构化记忆模型
- 采纳 mem0 的多信号检索（语义+BM25+实体关联）
- 采纳 mem0 的 TTL 硬过期 + 显式 Delete/Update 操作
- 采纳 VikingMem 的 Vector Pre-Filter + 两阶段提交 + 审计日志
- 引入 VikingMem 的时序衰减压缩机制
- 引入 mem0 的 Entity 关联层
- 引入 mem0 的 Consolidation 合并模式
- PostgresSaver 仅用于框架级 checkpoint（容灾恢复）

## 架构总览

```
┌────────────────────────────────────────────────────────────┐
│                     agent-service (Python)                  │
│                                                            │
│  POST /chat                                                │
│    │                                                       │
│    ├─ ① Retrieval Gateway                                 │
│    │   ├─ MilvusClient (semantic + BM25)                  │
│    │   └─ Neo4jClient (entity boost + profile lookup)     │
│    │                                                       │
│    ├─ ② Memory-Augmented System Prompt                    │
│    │   └─ PromptBuilder → inject profile/event/session     │
│    │                                                       │
│    ├─ ③ LangGraph Agent                                    │
│    │   ├─ StateGraph (classify_intent → route → handler)   │
│    │   └─ PostgresSaver (checkpoint, failure recovery only)│
│    │                                                       │
│    └─ ④ Memory Extractor (post-stream, async)              │
│        ├─ EventExtractor (小模型)                          │
│        ├─ ProfileUpdater (Vector Pre-Filter + LLM delta)   │
│        ├─ AgentCaseExtractor (新：Agent 自身经验提取)      │
│        └─ SessionSummarizer (每 N 轮增量写入)              │
│                                                            │
└────────────────────────────────────────────────────────────┘
                         │
         ┌───────────────┼───────────────┐
         ▼               ▼               ▼
    ┌─────────┐    ┌──────────┐    ┌──────────────┐
    │  Milvus  │    │  Neo4j    │    │  Postgres     │
    │          │    │          │    │  (checkpoint)  │
    │ Event    │    │ Profile  │    │  LangGraph PG  │
    │ Session  │    │ Entity   │    │  Saver only    │
    │ AgentCase│    │ Graph    │    │                │
    │ sparse   │    │          │    │                │
    └─────────┘    └──────────┘    └────────────────┘
```

## 一、记忆数据模型

### 分层

```
┌──────────────────────────────────────────────┐
│       L1 工作记忆                              │
│  Context Window（LLM 自动管理）                 │
└──────────────────────────────────────────────┘
              │
    ┌─────────┼─────────┬──────────────┐
    ▼         ▼         ▼              ▼
┌────────┐ ┌──────┐ ┌─────────┐ ┌──────────┐
│Profile │ │Event │ │Session  │ │AgentCase │
│(Neo4j) │ │(Milvus)│ │(Milvus) │ │(Milvus)  │
│结构化偏好│ │行为事件│ │会话摘要  │ │Agent经验  │
└────────┘ └──────┘ └─────────┘ └──────────┘
    │         │         │              │
    └─────────┼─────────┴──────────────┘
              ▼
   ┌──────────────────┐
   │ Entity 关联层     │
   │     (Neo4j)      │
   │ User/Shop/Area/  │
   │ Category/Voucher │
   └──────────────────┘
```

### Profile 原子（Neo4j 节点）

| 节点类型 | 关键属性 | 示例 |
|---------|---------|------|
| `TastePreference` | property, value, confidence, source, reinforce_count, last_reinforced_at, created_at, updated_at, ttl_seconds, expires_at | `{property: "spicy", value: "avoid", confidence: 0.92, reinforce_count: 3}` |
| `DietaryPreference` | constraint, type, confidence, source, is_hard, created_at, updated_at | `{constraint: "清真", type: "religious", is_hard: true}` |
| `BudgetPreference` | range_min, range_max, type, confidence, source, reinforce_count, last_reinforced_at | `{range_min: 50, range_max: 100, type: "per_person", confidence: 0.8}` |
| `CuisinePreference` | cuisine, weight, confidence, source, reinforce_count, last_reinforced_at | `{cuisine: "川渝火锅", weight: 0.9, confidence: 0.85}` |
| `ScenePreference` | scene, weight, confidence, source, reinforce_count, last_reinforced_at | `{scene: "朋友聚餐", weight: 0.7}` |
| `AreaPreference` | area, weight, confidence, source, reinforce_count, last_reinforced_at | `{area: "春熙路", weight: 0.8}` |
| `ConstraintPreference` | constraint, type, confidence, source, is_hard, reinforce_count, last_reinforced_at | `{constraint: "不要辣", type: "taste", is_hard: false}` |

**新增字段说明**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `reinforce_count` | INT | 被强化次数，衰减时减缓速度 |
| `last_reinforced_at` | INT64 | 最后一次被 REINFORCE 的时间戳 |
| `is_hard` | BOOL | 是否为硬约束（宗教/过敏/医疗），硬约束不参与衰减、不可被 REVISE 自动降级 |
| `ttl_seconds` | INT | 可选，到时自动标记为 expired（用于临时偏好如"最近减肥不吃碳水"） |
| `expires_at` | INT64 | 可选，绝对过期时间戳 |

**新类型：DietaryPreference**

与 TastePreference（口味偏好，如"爱吃辣/不爱吃辣"）区分：
- DietaryPreference 是**硬约束**：清真、素食、过敏原、糖尿病饮食等
- 硬约束不参与自然衰减（不随时间淡化）
- 只能由用户显式声明或 LLM 从对话中提取为高置信度（≥ 0.9）后才创建
- 被 REVISE 需要额外确认信号（如用户明确说"我现在可以吃XX了"）

每种类型上限：

| 类型 | 上限 |
|------|------|
| TastePreference | 5 |
| DietaryPreference | 10（硬约束不自动淘汰，靠用户显式管理） |
| CuisinePreference | 5 |
| AreaPreference | 5 |
| ScenePreference | 3 |
| BudgetPreference | 1（仅保留最新） |
| ConstraintPreference | 5 |

### Event 原子（Milvus collection: `user_event`）

```
字段:
  id              VARCHAR   PK
  user_id         VARCHAR   partition key
  event_type      VARCHAR   "search" | "purchase" | "reservation" | "view" | "feedback"
  description     VARCHAR   自然语言描述（embedding 源）
  payload         JSON      结构化事件数据
  embedding       FLOAT[]   向量
  sparse_embedding FLOAT[]  BM25 sparse vector
  session_id      VARCHAR   来源会话
  compressed      BOOL      是否为压缩记录
  compressed_from VARCHAR[] 被压缩的原始 event ID 列表
  ttl_seconds     INT       可选，到时自动清理（用于临时事件）
  expires_at      INT64     可选，绝对过期时间戳
  created_at      INT64     unix timestamp
```

索引：HNSW on `embedding`，SPARSE_INVERTED_INDEX on `sparse_embedding`，cosine 相似度。

### Session 摘要（Milvus collection: `user_session`）

```
字段:
  id              VARCHAR   PK
  user_id         VARCHAR   partition key
  summary         VARCHAR   会话自然语言摘要（embedding 源）
  embedding       FLOAT[]   向量
  sparse_embedding FLOAT[]  BM25 sparse vector
  key_shops       VARCHAR[] 涉及店铺 ID 列表
  key_areas       VARCHAR[] 涉及商圈
  intent          VARCHAR   主导意图
  is_complete     BOOL      会话是否已结束（false=进行中，true=已结束）
  created_at      INT64
  updated_at      INT64
```

保留策略：
- 最近 30 天：完整保留（含 embedding）
- 30-90 天：仅保留文本，删除 embedding（不可语义搜）
- > 90 天：硬删除

### Agent 经验记忆（Milvus collection: `agent_case`）— 新增

```
字段:
  id              VARCHAR   PK
  user_id         VARCHAR   partition key（可为空，表示通用经验）
  case_type       VARCHAR   "recommendation" | "purchase_flow" | "error_recovery" | "user_handling"
  description     VARCHAR   自然语言描述（embedding 源）
  context         JSON      触发场景（intent, area, category, budget 等）
  action          VARCHAR   Agent 采取的行动
  outcome         VARCHAR   "success" | "partial" | "failure"
  outcome_reason  VARCHAR   结果原因分析
  lesson          VARCHAR   经验教训（"when user says X, prefer Y strategy"）
  embedding       FLOAT[]   向量
  sparse_embedding FLOAT[]  BM25 sparse vector
  created_at      INT64
  ttl_seconds     INT       可选，模式级经验可设更长 TTL
```

用途：
- Agent 在执行推荐前检索相似历史场景，参考成功经验
- "上次用户说不吃辣且人均预算 80，推荐了粤菜馆，用户点击并下单了" → 可复用模式
- "用户在春熙路搜索火锅被推荐了距离 5km 的店，用户未点击" → 避免重复失败模式

### Entity 图（Neo4j）

```
实体节点:
  (:User {user_id})
  (:Shop {shop_id, name, type, area, ...})
  (:Area {area_id, name})
  (:Category {category_id, name, parent_id})
  (:Voucher {voucher_id, name, shop_id, ...})

Profile 原子节点（依附于 User）:
  (:TastePreference {property, value, confidence, source, reinforce_count,
                     last_reinforced_at, created_at, updated_at,
                     ttl_seconds, expires_at})
  (:DietaryPreference {constraint, type, confidence, source, is_hard,
                       created_at, updated_at})
  (:BudgetPreference {range_min, range_max, type, confidence, source,
                      reinforce_count, last_reinforced_at})
  (:CuisinePreference {cuisine, weight, confidence, source,
                       reinforce_count, last_reinforced_at})
  (:ScenePreference {scene, weight, confidence, source,
                     reinforce_count, last_reinforced_at})
  (:AreaPreference {area, weight, confidence, source,
                    reinforce_count, last_reinforced_at})
  (:ConstraintPreference {constraint, type, confidence, source, is_hard,
                          reinforce_count, last_reinforced_at})

Milvus 引用节点（轻量引用，通过 ID 关联）:
  (:EventRef {event_id})
  (:SessionRef {session_id})
  (:AgentCaseRef {case_id})

关系:
  (User) -[:PREFERS_TASTE]->       (TastePreference)
  (User) -[:PREFERS_DIETARY]->     (DietaryPreference)
  (User) -[:PREFERS_CUISINE]->     (CuisinePreference)
  (User) -[:PREFERS_AREA]->        (AreaPreference)
  (User) -[:PREFERS_SCENE]->       (ScenePreference)
  (User) -[:HAS_BUDGET]->          (BudgetPreference)
  (User) -[:HAS_CONSTRAINT]->      (ConstraintPreference)
  (User) -[:PERFORMED]->           (EventRef)
  (User) -[:HAS_EXPERIENCE]->      (AgentCaseRef)
  (Shop) -[:LOCATED_IN]->          (Area)
  (Shop) -[:HAS_CATEGORY]->        (Category)
  (EventRef) -[:TARGETED]->        (Shop | Area | Category | Voucher)
  (SessionRef) -[:MENTIONED]->     (Shop)
  (AgentCaseRef) -[:INVOLVED]->    (Shop | Area | Category)
```

## 二、记忆提取管道

### 整体流程

```
每轮对话结束后:
  用户消息 + Agent响应 + 工具调用结果
         │
         ▼
  ┌─────────────────────┐
  │  Event Extractor    │  小模型：从本轮提取结构化 Event
  └────────┬────────────┘
           │ events[]
           ▼
  ┌─────────────────────┐
  │  Vector Pre-Filter  │  新：向量相似度预筛选已有记忆
  │  (Milvus search)    │     只把 top_k 相似的已有 Profile
  │                     │     注入 LLM prompt，降低成本
  └────────┬────────────┘
           │ candidate_existing_profiles
           ▼
  ┌─────────────────────┐
  │  Profile Updater    │  小模型：对比已有 Profile → 输出 delta
  └────────┬────────────┘
           │ profile_delta (含 ADD/REINFORCE/REVISE/MERGE/DELETE)
           ▼
  ┌─────────────────────┐
  │  Agent Case Extractor│ 新：从推荐结果+用户反馈中提取经验
  └────────┬────────────┘
           │ agent_cases[]
           ▼
  ┌─────────────────────┐
  │  Session Summarizer │  小模型：每 N 轮增量写入 Milvus
  └────────┬────────────┘
           │
           ▼
  ┌─────────────────────┐
  │  Embedding & Write   │  并行写入 Neo4j + Milvus
  │  + Audit Log         │  生成 memory_diff.json
  └─────────────────────┘
```

### Vector Pre-Filter 机制 — 新增

**动机**：直接将用户所有已有 Profile（最多 30 条）注入 LLM prompt 做 delta 计算，随着 Profile 积累，token 消耗和延迟线性增长。VikingMem 使用向量预筛选减少 LLM 调用上下文。

**流程**：

```
本轮对话 + 新提取的 events → embed → Milvus search(
    collection="user_event",  # 在历史 event 中搜索相似上下文
    data=[round_embedding],
    filter=f'user_id == "{user_id}"',
    limit=10,
) → 从相似历史 event 追溯到关联的 Profile 原子（通过 Neo4j PERFORMED 关系）
  → 仅将这些 Profile 注入 LLM prompt 做 delta 对比
  → 未被预筛选到的 Profile 本轮 NOCHANGE（不需要 LLM 过目）
```

**例外**：硬约束（DietaryPreference, is_hard=true）始终注入 — 因为遗漏硬约束的后果严重。

### 执行时机

| 步骤 | 时机 | 是否阻塞 |
|------|------|---------|
| Event 提取 | 每轮 SSE 流结束后 `asyncio.create_task` | 异步 |
| Vector Pre-Filter | Event 提取完成后 | 异步 |
| Profile 更新 | Vector Pre-Filter 完成后 | 异步 |
| Agent Case 提取 | Profile 更新完成后 | 异步 |
| Session 摘要 | 每 3 轮增量写入一次 | 异步 |

### Event 提取 prompt

```
从以下对话回合中提取用户行为事件。每个事件单独列出。

事件类型：search / purchase / reservation / view / feedback / constraint / dietary

特别注意：
- dietary 类型：用户提到的饮食约束（清真、素食、过敏原、糖尿病饮食等），
  这是硬约束，与 constraint（口味偏好如"不吃辣"）区分

输出格式（每行一个 JSON）：
{"type":"search","description":"用户在春熙路搜索川渝火锅",
 "payload":{"query":"火锅","area":"春熙路","category":"川渝火锅"}}
{"type":"dietary","description":"用户明确表示清真饮食要求",
 "payload":{"constraint":"清真","type":"religious"}, "is_hard":true}
{"type":"constraint","description":"用户表示今天不想吃辣",
 "payload":{"constraint":"不吃辣"}, "ttl_seconds":86400}

对话：
{user_message}
{assistant_response}
{tool_calls}
```

### Profile 更新策略

```
流程:
  1. Vector Pre-Filter: Milvus 语义搜索定位与本轮对话相关的已有 Profile
  2. 从 Neo4j 查预筛选后的 Profile 原子 → 注入 prompt 上下文
  3. LLM 对比新对话与已有 Profile → 输出 delta
  4. 执行 delta → Neo4j upsert/delete
  5. 生成 memory_diff.json 审计日志

Delta 操作类型（扩展）:
  - ADD:        新的偏好原子（之前没有的），confidence = 0.6
  - REINFORCE:  已有偏好再次体现，confidence += 0.1 (max 0.95)，
                reinforce_count += 1，last_reinforced_at = now()
  - REVISE:     偏好变更（矛盾），旧 confidence → 0.2，新从 0.6 起步
  - DELETE:     用户明确纠错（"我之前说错了"），直接删除旧原子
  - MERGE:      多个相似原子合并为一个（Consolidation），取最高 confidence，
                reinforce_count 累加
  - NOCHANGE:   未提及，不操作
  - EXPIRE:     标记为过期（ttl_seconds 到期），保留但在检索中排除

置信度生命周期（改进）:
  - 首次出现: confidence = 0.6
  - 每次 REINFORCE: confidence += 0.1 (max 0.95)，reinforce_count += 1
  - 自然衰减: confidence_at_time = initial_confidence × e^(-λ × days / log2(2 + reinforce_count))
    强化次数越多，衰减越慢（log2 平滑）
    示例: reinforce_count=0 → 除数 log2(2)=1 → 标准衰减
          reinforce_count=3 → 除数 log2(5)≈2.32 → 衰减速度降至 ~43%
          reinforce_count=7 → 除数 log2(9)≈3.17 → 衰减速度降至 ~32%
  - 低于 0.3: 自动删除
  - REVISE: 旧偏好降至 0.2（保留但不参与检索），新偏好从 0.6 起步
  - 硬约束（is_hard=true）: 不参与衰减，不可被 REVISE 自动降级
  - TTL 到期: 直接标记为 expired，从检索中排除，7 天后硬删除

DELETE 触发条件（显式纠错）:
  - "我以前说不吃辣，其实我吃" → DELETE old TastePreference
  - "我说错了，不是春熙路是太古里" → DELETE old AreaPreference, ADD new
  - 判断标准: 用户使用了"错了/不对/其实是/纠正"等明确纠错词

暂时性 vs 长期性区分:
  - "今天想吃辣" → 不形成偏好，不触发 ADD
  - "最近减肥，不吃碳水" → 可选 ADD 带 ttl_seconds=2592000 (30天)
  - "我最近爱/一直/从来/不吃" → 形成偏好变更
  - "我是回民/清真" → 形成 DietaryPreference，is_hard=true
```

### 时序衰减参数（改进）

| 类型 | λ | 半衰期 (reinforce_count=0) | 原因 |
|------|---|---------------------------|------|
| TastePreference | 0.01 | ~69天 | 口味变化慢 |
| DietaryPreference | N/A | 不衰减 | 硬约束永久 |
| BudgetPreference | 0.01 | ~69天 | 消费习惯稳定 |
| CuisinePreference | 0.02 | ~35天 | 菜系偏好中等波动 |
| AreaPreference | 0.05 | ~14天 | 商圈偏好变化快 |
| ScenePreference | 0.03 | ~23天 | 场景偏好中等 |
| ConstraintPreference | 0.005 | ~139天 | 宗教/过敏等不易变（但非硬约束） |

### Profile Consolidation（合并模式）— 新增

借鉴 mem0 的 consolidate atomic → rich memory 模式：

```
触发条件（定时任务，每日执行一次）:
  对每个用户，在 Neo4j 中查找同类型 Profile 原子，
  计算两两之间的向量相似度（用 Milvus embed 后 cosine）

合并条件:
  - 同类型（如两条 CuisinePreference）
  - 向量相似度 > 0.85
  - 含义可合并（LLM 最终判断）

合并操作:
  1. LLM 判断两条原子是否应合并
  2. 若是: MERGE → 生成一条新原子，description 包含两条的内容
     confidence = max(c1, c2)，reinforce_count = c1.rc + c2.rc
  3. DELETE 两条旧原子
  4. 记录到 memory_diff.json

示例:
  原子A: CuisinePreference {cuisine: "火锅", confidence: 0.7, reinforce_count: 2}
  原子B: CuisinePreference {cuisine: "川渝火锅", confidence: 0.8, reinforce_count: 3}
  → MERGE → CuisinePreference {cuisine: "川渝火锅", confidence: 0.8, reinforce_count: 5}
```

### Session 摘要策略（改进）

```
增量模式（改进）:
  - 每轮生成 round_summary（本轮要点），暂存内存
  - 每 3 轮增量写入一次 Milvus（is_complete=false，updated_at=now()）
    → 避免长会话摘要过时，避免崩溃丢失
  - 会话结束时：
    1. 将所有 round_summaries 合并为最终摘要
    2. upsert Milvus（is_complete=true）
  - 检索时：is_complete=true 的 session 优先，
    is_complete=false 的仅作为辅助上下文

摘要字段:
  summary:     "用户在春熙路附近搜索了火锅和粤菜，预算人均100以内，
                最终查看了蜀大侠的优惠券但未下单"
  key_shops:   ["shop_123", "shop_456"]
  key_areas:   ["春熙路"]
  intent:      "recommend_shop"
```

### 审计日志（memory_diff.json）— 新增

借鉴 VikingMem 的 memory_diff 审计机制：

每次 Profile 更新后，生成一条审计记录：

```json
{
  "timestamp": "2026-06-29T15:30:00Z",
  "user_id": "u123",
  "session_id": "sess_abc",
  "trigger_conversation": {
    "user_message": "我最近爱上吃粤菜了，不吃辣了",
    "round_index": 3
  },
  "operations": [
    {
      "op": "REVISE",
      "target_type": "TastePreference",
      "target_id": "profile_taste_001",
      "old_value": {"property": "spicy", "value": "like", "confidence": 0.75},
      "new_value": {"property": "spicy", "value": "like", "confidence": 0.2},
      "reason": "用户明确表示不吃辣了"
    },
    {
      "op": "ADD",
      "target_type": "CuisinePreference",
      "target_id": "profile_cuisine_new",
      "new_value": {"cuisine": "粤菜", "confidence": 0.6},
      "reason": "用户表示最近爱上吃粤菜"
    },
    {
      "op": "DELETE",
      "target_type": "ConstraintPreference",
      "target_id": "profile_constraint_003",
      "old_value": {"constraint": "不吃牛肉", "confidence": 0.5},
      "reason": "用户明确纠错：'之前说错了，我其实吃牛肉的'"
    }
  ]
}
```

存储：`agent-service/data/memory_diff/{user_id}/{YYYY-MM}.jsonl`（按用户+月份分文件，便于查询和清理）

## 三、记忆防膨胀

### Event 滚动压缩

```
原始 Events → 7天后按同 type + 同 category/area 聚合:

Day 1:  SearchEvent "春熙路 火锅"
Day 3:  SearchEvent "春熙路 川渝火锅"
Day 5:  SearchEvent "春熙路 火锅 人均80"
Day 8:  SearchEvent "春熙路 毛肚火锅"
     ↓ 触发压缩
压缩后:
  CompressedEvent {
    event_type: "search_compressed",
    description: "过去7天在春熙路搜索火锅4次，偏好川渝火锅/毛肚火锅，人均80"
    payload: {query_pattern: "火锅", area: "春熙路", count: 4, window: "7d"}
    compressed: true,
    compressed_from: ["evt_001", "evt_002", "evt_003", "evt_004"]
  }
  删除原始 4 条，保留 1 条压缩记录
```

压缩记录自身也可被二次压缩（30 天窗口 → 月级别摘要）。

### Profile 数量上限 + 合并

每种偏好类型达到上限时：
1. 先尝试 Consolidation：查找是否有可合并的相似原子
2. 无可合并时：新原子 confidence > 现有最低 → 替换，否则丢弃

### TTL 硬过期 — 新增

除了指数衰减（软遗忘），增加 TTL 硬过期机制：

| 机制 | 适用场景 | 示例 |
|------|---------|------|
| 指数衰减 | 长期偏好自然淡化 | 以前爱吃火锅但最近不提了 |
| TTL 硬过期 | 临时状态/约束 | "最近减肥不吃碳水"（30天） |
| 显式 DELETE | 用户纠错 | "我说错了，其实我吃辣" |

TTL 到期处理：
1. Profile 原子：标记 expired，从检索中排除，7 天后 Neo4j 硬删除
2. Event：直接从 Milvus 删除（event 是时序数据，过期即可丢弃）
3. 压缩记录中包含的原始 event 有 TTL → 压缩时 TTL 继承到压缩记录

### Session 过期

30 天内完整保留，30-90 天去 embedding，> 90 天硬删除。

### Agent Case 过期

Agent Case 的 TTL 默认更长（180 天），因为经验模式比用户行为更稳定。

## 四、记忆冲突处理

### 提取时显式判断

Profile Updater prompt 注入已有偏好上下文，要求区分 REVISE / REINFORCE / DELETE / MERGE / transient：

```
你已知该用户当前的偏好：
- PREFERS_CUISINE: 川渝火锅 (confidence: 0.85, reinforce_count: 3)
- TASTE: 不吃辣 (confidence: 0.9, reinforce_count: 5)
- BUDGET: 人均50-100 (confidence: 0.7, reinforce_count: 1)
- DIETARY: 清真 (confidence: 1.0, is_hard: true)

从本轮对话中判断，注意：
1. 用户表达与已有偏好矛盾 → REVISE
2. 用户明确纠错（"错了/不对/其实是"）→ DELETE 旧 + [可选 ADD 新]
3. 只是未提及已有偏好 → NOCHANGE（不做衰减，衰减由后台定时任务处理）
4. "今天想吃辣" → 不形成偏好变更（transient）
5. "最近减肥，不吃碳水" → ADD 带 ttl_seconds=2592000 (30天)
6. "我最近爱上吃辣" → 形成偏好变更
7. 硬约束（is_hard=true）不可被 REVISE → 需要额外确认信号
8. 两个同类型原子语义相似 → MERGE
```

### 显式纠错处理（DELETE）— 新增

```
用户说"我之前说错了，其实我..." → Profile Updater 识别为 DELETE 意图
  → 立即从 Neo4j 删除旧原子
  → 如有新信息，ADD 新原子
  → 不做 REVISE（旧原子不需要保留到 0.2）
```

### 检索层置信度竞争

矛盾偏好共存时（如旧 0.2 / 新 0.6），检索按 confidence 排序自然解决。

### 冲突处理矩阵（扩展）

| 场景 | 示例 | 处理 |
|------|------|------|
| 明确推翻 | "我以前不吃辣，现在吃了" | LLM 标记 REVISE，旧 confidence→0.2 |
| 明确纠错 | "我说错了，其实是春熙路不是太古里" | LLM 标记 DELETE 旧 + ADD 新 |
| 隐式矛盾 | 从爱火锅变成只搜粤菜（未明说） | 时间衰减自然淘汰旧偏好 |
| 暂时变化 | "今天想换个口味" | LLM 判断为 transient，不形成偏好 |
| 临时约束 | "最近减肥不吃碳水" | ADD 带 ttl_seconds，到期自动过期 |
| 双偏好共存 | 爱吃火锅 AND 爱吃粤菜 | 两种共存，使用中自然竞争 |
| 硬约束冲突 | 旧清真→新说"我可以吃猪肉了" | 需要额外确认，不可自动 REVISE |

## 五、检索管道

### 触发时机

- 新会话（无 checkpoint）：完整三路检索
- 已有会话（有 checkpoint）：跳过检索（上下文已在 L1 + checkpoint 延续）

### 三路并行

```
用户查询 → Query Preprocessing
  ├─ 提取实体 & 链接
  ├─ 生成 dense embedding
  └─ 生成 sparse embedding (BM25)
              │
    ┌─────────┼─────────┐
    ▼         ▼         ▼
┌────────┐ ┌───────┐ ┌──────────┐
│ 语义    │ │ BM25  │ │ Entity   │
│ Milvus  │ │ Milvus│ │ Boost    │
│         │ │ sparse│ │ Neo4j    │
│ Event   │ │ Event │ │ 子图遍历 │
│ Session │ │Session│ │ ID 加权  │
│ Agent   │ │ Agent │ │          │
│ Case    │ │ Case  │ │          │
│ top_k=20│ │top_k=20│ │ top_k=20│
└────┬────┘ └───┬───┘ └────┬─────┘
     │          │          │
     └──────────┼──────────┘
                ▼
     ┌──────────────────┐
     │   Score Normalize │  ← 新：各分数归一化到 [0,1]
     │   语义 → [0,1]    │
     │   BM25 → [0,1]    │
     │   Entity → [0,0.3]│
     └────────┬─────────┘
              ▼
     ┌──────────────────┐
     │   Rank Fusion     │
     │ 0.45/0.25/0.30    │
     └────────┬─────────┘
              ▼
       Top-K 记忆 (≤10)
```

### Score Normalization — 新增

各通道分数在融合前归一化到 [0,1]：

```
语义分数归一化: normalized = (score - min_score_of_results) / (max - min)
  如果只有 1 条结果 → normalized = 1.0
BM25 分数归一化: normalized = bm25_score / max_bm25_in_results
Entity boost: 直接就是 [0, 0.30] 区间，不另归一化
  直接实体关联: +0.30
  Profile 间接关联: +0.15
  无关联: 0

融合后: final_score = semantic_normalized × 0.45 + bm25_normalized × 0.25 + entity_boost
  → 最终区间 [0, 1]
```

### 子图遍历逻辑

```cypher
MATCH (u:User {user_id: $uid})-[:PREFERS_CUISINE|PREFERS_AREA|PREFERS_DIETARY|PERFORMED]->(pref)
WHERE (pref:AreaPreference AND pref.area IN $areas)
   OR (pref:CuisinePreference AND pref.cuisine IN $cuisines)
   OR (pref:DietaryPreference AND pref.is_hard = true)  // 硬约束总是匹配
OPTIONAL MATCH (pref)-[:RELATED_TO]->(e:EventRef)
OPTIONAL MATCH (pref)-[:MENTIONED]->(s:SessionRef)
OPTIONAL MATCH (pref)-[:HAS_EXPERIENCE]->(ac:AgentCaseRef)
RETURN pref, e, s, ac, pref.confidence * pref.weight AS boost_score
ORDER BY boost_score DESC
LIMIT 20
```

### Rank Fusion 权重

```
final_score = semantic_norm × 0.45 + bm25_norm × 0.25 + entity_boost × 0.30

权重来源：mem0 v3 默认行为，通过归一化后的加权融合。
后续可通过离线评估（标注数据集）调整。
初始值：语义为主（0.45），实体增强为辅（0.30），关键词为补充（0.25）
```

### 注入格式

```
## 用户记忆

### 偏好
- [口味] 不吃辣 (置信度:0.9, 提及5次)
- [饮食约束] 清真 (硬约束, 置信度:1.0)
- [预算] 人均50-100 (置信度:0.7)
- [菜系] 川渝火锅 (置信度:0.85)

### 近期行为
- [搜索] 在春熙路搜索川渝火锅
- [浏览] 查看了蜀大侠的优惠券

### 历史会话
- 用户之前在春熙路附近搜索了火锅和粤菜，预算人均100以内...

### Agent 经验（内部，不注入用户可见 prompt）
- 类似场景下推荐粤菜馆转化率高
- 用户对 5km 以上的推荐未点击
```

## 六、记忆质量反馈闭环 — 新增

### 设计动机

当前设计和 mem0/VikingMem 都没有记忆质量的闭环反馈。偏好被提取后，其"正确性"完全依赖 LLM 判断和置信度衰减，没有来自下游任务的真实反馈信号。

### 反馈信号

| 信号 | 来源 | 对记忆的影响 |
|------|------|-------------|
| `shop_card_click` | 用户点击推荐卡片 | 相关 CuisinePreference/AreaPreference REINFORCE |
| `chat_purchase_success` | 用户完成下单 | 相关 BudgetPreference/偏好大幅 REINFORCE (+0.15) |
| 推荐展示但无点击 | 用户忽略推荐 | 相关偏好无变化（可能不感兴趣，也可能只是不需要） |
| 用户明确拒绝 | "这个太贵了""不喜欢这家" | 触发 ConstraintPreference 更新 |
| 用户主动纠错 | "错了，其实…" | 触发 DELETE |

### 实现方式

```
推荐生成时:
  - 在 shop_card SSE 事件中携带 trace_id
  - 标记哪些 Profile 原子被用于本次推荐（引用链）

用户行为事件到达时（埋点日志）:
  - shop_card_click + trace_id → 反查引用链 → 强化相关 Profile
  - purchase_success + trace_id → 大幅强化相关 Profile
  - explicit_rejection → 降低相关 Profile confidence

执行方式:
  - 通过 Java 后端埋点事件异步传递到 Python agent
  - 或 Python 侧直接消费埋点日志（后续迭代）
  - 初期：在下一轮对话时，Profile Updater 从对话中自然感知用户反馈
```

## 七、Neo4j + Milvus 双写一致性 — 新增

### 问题

Profile 在 Neo4j、Event/Session/AgentCase 在 Milvus，Entity 引用在两边。写入是异步的（asyncio background task），需要考虑一致性。

### 策略

```
写入顺序（同步部分）:
  1. Neo4j: 写入 Profile 原子 + EventRef/SessionRef 节点
  2. Milvus: 写入 Event/Session embedding
  → 如果 Milvus 写入失败，Neo4j 的引用节点指向一个尚不存在的 Milvus 实体
  → 检索时做防御性过滤：JOIN Milvus 检查实体是否存在，不存在则跳过

修复机制:
  - 后台定时任务（每 10 分钟）检查 Neo4j 中的 EventRef/SessionRef
    是否在 Milvus 中有对应实体
  - 孤儿引用超过 1 小时 → 从 Neo4j 删除
  - 写入失败重试 3 次（指数退避），仍失败 → 写入 dead_letter 日志

读路径（检索时）:
  - Neo4j 子图遍历返回 Entity boost → Milvus 语义搜索
  - 结果取交集（两个数据库都有才算有效）
  - 单边故障：Neo4j 不可用 → Entity boost 跳过，仅语义+BM25
                Milvus 不可用 → 推荐降级，闲聊不中断
```

## 八、请求完整链路（更新）

```
POST /chat {query, thread_id, user_id}
│
├─ Step 0: 鉴权 & 参数校验
│
├─ Step 1: 检查是否需要检索
│   agent.get_state({"thread_id": thread_id})
│   ├─ 无已有 state → 新会话，执行 Step 2
│   └─ 有已有 state → 跳过 Step 2，直接用 checkpoint 恢复
│
├─ Step 2: 三路检索（仅新会话）
│   ├─ Milvus.search(Event + Session + AgentCase, dense_embedding) → semantic
│   ├─ Milvus.search(Event + Session + AgentCase, sparse_embedding) → bm25
│   ├─ Neo4j.subgraph(user_id, extracted_entities) → entity_boosted_ids
│   ├─ ScoreNormalization (各通道归一化到 [0,1])
│   └─ RankFusion(top_k=10, per_type_limit: profile≤5, event≤3, session≤2)
│
├─ Step 3: 记忆注入 system prompt
│   ├─ Neo4j.get_profiles(user_id) → 偏好列表（排除 expired + confidence < 0.3）
│   ├─ Neo4j.get_hard_constraints(user_id) → 硬约束列表（is_hard=true, 全部注入）
│   └─ PromptBuilder.augment(SYSTEM_PROMPT, profiles, events, sessions, agent_cases)
│
├─ Step 4: Agent 执行
│   └─ agent.astream(input, config={"thread_id": thread_id})
│       ├─ classify_intent → route → handler
│       └─ PostgresSaver 自动 checkpoint 每个节点
│
├─ Step 5: SSE 流结束，触发异步提取
│   └─ asyncio.create_task(extract_memories(...))  // 不阻塞响应
│
└─ Step 6: 异步记忆提取（后台）
    ├─ get_state(thread_id) → 本轮完整 messages + tool_calls
    ├─ EventExtractor.extract(本轮user_msg, assistant_msg, tool_calls)
    │   → events[] → Milvus insert
    ├─ Vector Pre-Filter: Milvus.search(本轮 events embedding, user_event)
    │   → 追溯关联的已有 Profile 候选集
    ├─ ProfileUpdater.update(user_id, 本轮对话, prefiltered_profiles)
    │   → delta (含 ADD/REINFORCE/REVISE/MERGE/DELETE/EXPIRE)
    │   → Neo4j 执行 upsert/delete
    │   → 生成 memory_diff.jsonl 审计记录
    ├─ AgentCaseExtractor.extract(user_id, 本轮推荐结果 + 用户反馈)
    │   → agent_cases[] → Milvus insert
    └─ SessionSummarizer.update(session_id, round_summary)
        → 每 3 轮: upsert Milvus (is_complete=false)
        → 会话结束: 合并最终摘要, upsert Milvus (is_complete=true)
```

## 九、基础设施 & 依赖

### 新增组件

| 组件 | 用途 | 部署方式 |
|------|------|---------|
| Neo4j | Profile 原子存储 + Entity 图 | Docker 独立实例 |
| Milvus `user_event` collection | 行为事件语义搜索 | 复用现有 Milvus |
| Milvus `user_session` collection | 会话摘要语义搜索 | 复用现有 Milvus |
| Milvus `agent_case` collection | Agent 经验语义搜索 | 复用现有 Milvus |
| Postgres | LangGraph checkpoint | Docker 独立实例 |

### 新增 Python 依赖

```
neo4j>=5.0           # Neo4j Python driver
milvus-model         # BM25 sparse embedder（Milvus 2.4+）
```

### 新增本地存储

```
agent-service/data/memory_diff/{user_id}/{YYYY-MM}.jsonl  # 审计日志
agent-service/data/dead_letter/                            # 写入失败队列
```

### 环境变量

```
# Neo4j
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password

# Postgres (checkpoint)
PG_CHECKPOINT_URI=postgres://user:pass@localhost:5432/pick_agent_checkpoint
```

### 删除项

- `agent-service/src/agent/memory/redis_history.py` — 完全删除
- `main.py` 中的 `load_history()`、`save_history()`、`_save_history_safe()` 调用
- 不再需要 Kafka（当前设计中记忆提取为 asyncio background task）

## 十、实施阶段（更新）

| 阶段 | 内容 | 依赖 |
|------|------|------|
| Phase 0 | 搭建 Neo4j + PG 环境 | 运维 |
| Phase 1 | Neo4j Entity 图初始化（从现有 MySQL 同步 Shop/Area/Category） | Neo4j 就绪 |
| Phase 2 | Milvus `user_event` + `user_session` + `agent_case` collection 创建 + sparse index | — |
| Phase 3 | Event 提取器（小模型提取 + TTL 支持 + Milvus 写入） | Phase 2 |
| Phase 4 | Profile Updater（Vector Pre-Filter + Neo4j 读写 + delta 逻辑 + DELETE/MERGE + 置信度/衰减 + 审计日志） | Phase 1 |
| Phase 5 | Session Summarizer（每 3 轮增量写入 + 过期策略） | Phase 2 |
| Phase 6 | Agent Case Extractor（经验提取 + 写入） | Phase 2 |
| Phase 7 | 三路检索管道（semantic + BM25 + entity boost + score normalization + rank fusion） | Phase 1, 2 |
| Phase 8 | 检索注入 system prompt + 新会话触发逻辑 + 硬约束注入 | Phase 7 |
| Phase 9 | Profile Consolidation 定时任务 | Phase 4 |
| Phase 10 | TTL 过期清理定时任务 + Event 滚动压缩 + 防膨胀全部机制 | Phase 3, 4, 5 |
| Phase 11 | PostgresSaver 替换 InMemorySaver + 删除 redis_history.py | PG 就绪 |
| Phase 12 | 双写一致性检查 + 孤儿引用清理 + dead_letter 处理 | Phase 4 |
| Phase 13 | 记忆质量反馈闭环（埋点事件 → Profile 强化/弱化） | Phase 4, 埋点就绪 |
| Phase 14 | 集成测试 + 记忆质量评估 | 全部 |

## 十一、设计决策总结（更新）

| 决策 | 选择 | 原因 |
|------|------|------|
| 记忆数据模型 | VikingMem 的 Profile/Event/Session + AgentCase 五类 | 结构完整，覆盖用户+Agent 两侧 |
| Entity 关联 | Neo4j 图存储 | Profile/实体天然同库，图遍历高效 |
| Event/Session/AgentCase 存储 | Milvus（dense + sparse 双向量） | 语义+关键词双路检索 |
| BM25 实现 | Milvus sparse vector | 免额外 ES 组件，渐进式 |
| 检索模式 | 语义 + BM25 + Entity boost 三路 fusion | mem0 v3 验证有效 |
| 分数融合 | 先归一化到 [0,1] 再加权求和 | mem0 v3 做法，比分数字面相加更合理 |
| 提取模式 | 每轮增量提取，asyncio background task | 不阻塞响应 |
| Vector Pre-Filter | 语义相似度预筛选，只把相关 Profile 送 LLM | VikingMem 做法，大幅降低 LLM token 消耗 |
| 冲突处理 | DELETE/REVISE/REINFORCE/MERGE + 置信度竞争 + 时间衰减 | 多层防护，支持显式纠错 |
| 防膨胀 | TTL 硬过期 + Event 滚动压缩 + Profile 数量上限 + Session 过期 | 自动化，区分临时/长期 |
| 时序衰减 | 指数衰减 + 强化次数阻尼 + 硬约束豁免 | 比纯指数更精细 |
| 审计日志 | memory_diff.jsonl 按用户+月份分文件 | 可回溯、可评估记忆质量 |
| 双写一致性 | 写入顺序 + 孤儿引用清理 + 读路径防御 | 最终一致，单边故障可降级 |
| 反馈闭环 | 埋点事件 → 相关 Profile 强化/弱化 | 让记忆质量随使用持续改进 |
| Checkpoint | PostgresSaver，纯容灾 | 与记忆系统解耦 |
| Redis 去留 | 删除 history 功能，保留限流/秒杀/会话 | 退回到缓存/业务层 |

## 十二、未解决问题

- **Neo4j 实例**：新建，与企业现有基础设施协调
- **Profile 初始导入**：是否从已有用户行为数据做一次冷启动批量提取？
- **记忆质量评估**：如何衡量检索召回率/准确率？是否需要标注数据集？
- **BM25 sparse vector**：Milvus 2.4+ Python SDK 对 sparse float vector 的支持需验证
- **小模型选择**：Event 提取和 Profile 更新使用哪个模型？与对话主模型共用还是独立低成本模型？
- **Agent Case 冷启动**：初期无经验数据时，Agent 如何做推荐决策？是否需要人工标注种子经验？
- **反馈闭环的延迟**：埋点事件从 Java → Python 的传递链路待设计（轮询埋点日志 vs Kafka vs 下一轮对话中自然感知）
- **memory_diff 存储增长**：长期累积的审计日志需要清理策略（建议 > 180 天归档压缩）
