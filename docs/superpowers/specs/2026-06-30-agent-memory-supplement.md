# Agent 记忆系统补充设计

> 2026-06-30 | brainstorming | 对 `2026-06-29-agent-memory-redesign.md` 的补充

## 背景

`2026-06-29-agent-memory-redesign.md` 定义了记忆系统的核心架构（数据模型、提取管道、检索管道、防膨胀等），但以下 6 个问题尚未覆盖或列为"未解决"。本文档在与作者逐条讨论后形成补充设计。

补充覆盖：
- **十二、冷启动策略**（原"未解决问题"之一）
- **十三、用户可见性与控制权**（原设计未涉及）
- **十四、记忆提取模型选择**（原"未解决问题"之一）
- **十五、记忆质量评估**（原"未解决问题"之一）
- **十六、反馈闭环**（原"未解决问题"之一，已有框架但缺具体通道）
- **十七、多 Agent 协作**（原设计未涉及，独立文档：`2026-06-30-agent-team-design.md`）

---

## 十二、冷启动策略

### 两种用户，两条路径

```
新用户首次对话
    │
    ├─ 有历史行为数据（浏览/收藏/订单）？
    │       │
    │       YES → ① 批量 Profile 提取（离线任务，Phase 0 之后执行一次）
    │             从 MySQL 提取：
    │               - 收藏店铺的 type/area/price → CuisinePreference + AreaPreference + BudgetPreference
    │               - 订单中的券类型/金额 → BudgetPreference
    │               - 浏览记录中的搜索关键词 → 弱 CuisinePreference（confidence: 0.4）
    │             提取后写入 Neo4j，标注 source: "behavior_import"
    │
    │       NO（纯新用户，零数据）
    │              │
    │              ▼
    │       ② 轻量 onboarding（最多 2 个问题，可选跳过）
    │         "嗨！我是你的 AI 导购。为了给你更好的推荐，能告诉我两件事吗？
    │          1. 有什么忌口或饮食偏好吗？（比如不吃辣、清真、素食…可以跳过）
    │          2. 人均预算大概多少？（比如 50 以内、50-100、100-200…可以跳过）"
    │         
    │         用户回答 → EventExtractor 直接从 onboarding 回答中提取初始 Profile
    │         用户跳过 → 零记忆开始，首轮推荐靠 LLM 自身知识，聊 1-2 轮后记忆自然积累
    │
    ▼
  正常对话流程（三路检索 + 记忆提取）
```

### 实现要点

| 项 | 说明 |
|---|---|
| 触发时机 | 每次新会话检索前先查 Neo4j：该用户无任何 Profile 节点 → 冷启动 |
| 行为数据导入 | 一次性批处理脚本，放在 Phase 0 环境就绪后执行 |
| onboarding 实现 | 不走新 API。在 system prompt 中加 `cold_start_onboarding` 逻辑，检测到用户无 Profile 时自动触发 |
| 跳过机制 | 用户说"不用了/跳过/直接搜吧" → 立即退出 onboarding |
| 导入的 confidence | 行为数据提取的 Profile 初始 confidence = 0.4-0.6（低于对话提取的 0.6），source 标记为 "behavior_import" |
| 导入后首次 REINFORCE | source="behavior_import" 的 Profile 首次被对话确认时，REINFORCE 幅度 +0.2（而非 +0.1），补偿弱信号起步 |

---

## 十三、用户可见性与控制权

### 纯对话通道，零前端成本

不做 UI 管理页。用户通过对话自然管理自己的记忆：

```
用户: "你知道我什么偏好？"
  → Agent 查 Neo4j 当前 Profile（排除 expired + confidence < 0.3）
  → 用自然语言呈现：
    "根据我们之前的交流，我记得：
     - 🍽️ 你不吃辣，偏好川渝火锅和粤菜
     - 💰 人均预算 50-100 元
     - 📍 常去春熙路和太古里
     - 🕌 清真饮食（这个我不会自动更改）
     有什么需要调整的吗？"

用户: "我现在吃辣了，把不吃辣去掉"
  → Agent 调内部 DELETE 操作 → "好的，已更新。"
```

### 对话中可用的记忆管理动词

| 用户意图 | 触发词 | 系统操作 |
|---------|--------|---------|
| 查看记忆 | "你知道我什么""记得我什么""我的画像" | 只读查询 Neo4j Profile |
| 删除单条 | "忘掉""删掉""去掉""不要记" | DELETE 指定 Profile 原子 |
| 修正 | "其实是""应该是""改成" | DELETE 旧 + ADD 新 |
| 清除全部 | "忘掉所有偏好" | DELETE 该用户全部 Profile（需确认） |
| 临时忽略 | "这次不用管我的偏好" | 本轮检索跳过 Profile 注入，不修改存储 |

### 清除全部的双重确认

```
用户: "忘掉我的所有偏好"
Agent: "这将清除我记住的关于你的所有偏好（口味、预算、商圈、场景等），
        后续推荐会像新用户一样。确认吗？(确认/取消)"
用户: "确认"
Agent: [执行 DELETE ALL] "已清除。"
```

### 同步执行

与正常记忆提取（异步, asyncio background task）不同，用户主动管理记忆时**同步执行**：立即写 Neo4j → 立即在下一轮检索中生效。不复用异步管道。

---

## 十四、记忆提取模型选择

### 独立低成本模型

提取任务是高频、结构化、低推理强度场景。使用独立低成本模型，与对话主模型分离：

| | 对话主模型 | 提取模型 |
|---|---|---|
| 角色 | 在线对话 + 工具调用 | 异步后台提取 |
| 模型级别 | gpt-4o-mini 或同等 | Qwen3-8B / DeepSeek-V3-Lite 或同等 8B-30B |
| 推理要求 | 高（多步推理 + 工具选择） | 低（分类 + JSON 输出） |
| 延迟 | 敏感（影响用户体验） | 不敏感（用户已拿到回复） |
| 成本 | 中等 | 需低于主模型的 1/5 |

### 提取模型能力要求

| 维度 | 最低要求 |
|------|---------|
| 指令跟随 | 高 — Event 和 Profile delta 是严格 JSON 结构化输出 |
| 推理能力 | 低 — 不需要多步推理 |
| 中文理解 | 高 — Pick 是纯中文平台 |
| 上下文窗口 | 4K token 足够 — 只输入本轮对话 |

### 配置方式

```bash
# 对话主模型（已有）
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini

# 记忆提取模型（新增）
EXTRACTOR_BASE_URL=https://api.deepseek.com/v1
EXTRACTOR_API_KEY=sk-yyy
EXTRACTOR_MODEL=deepseek-chat
```

`agent/config.py` 新增 `get_extractor_model()` 工厂函数。EventExtractor / ProfileUpdater / AgentCaseExtractor / SessionSummarizer 全部通过依赖注入获取提取模型，不硬编码。

### 渐进式接入

| 阶段 | 做法 |
|------|------|
| Phase 3-6 初期开发 | 用对话主模型跑通提取逻辑（功能正确性优先） |
| Phase 14 集成测试 | 切换到独立提取模型，对比提取质量 |
| 后续优化 | 如质量不达标，用 memory_diff 审计日志微调 domain-specific 提取模型 |

---

## 十五、记忆质量评估

### 两阶段路线

| | Phase 14 离线评估 | Phase 15+ 在线 A/B |
|---|---|---|
| 数据 | 50-100 条人工标注 | 全量用户 |
| 指标 | recall@k / precision@k / hallucination rate | 推荐点击率 / 下单转化率 |
| 目的 | 验证记忆系统基本正确性 | 验证记忆系统的业务价值 |

### 标注数据集

从对话日志中抽样 50-100 个场景，人工标注 ground truth：

```json
{
  "scenario_id": "eval_001",
  "user_context": {
    "known_profiles": [
      {"type": "TastePreference", "property": "spicy", "value": "avoid"},
      {"type": "CuisinePreference", "cuisine": "川渝火锅", "confidence": 0.85}
    ],
    "recent_events": ["在春熙路搜索火锅", "浏览了蜀大侠优惠券"],
    "current_session_summary": "用户想在春熙路附近找人均80以内的聚餐地点"
  },
  "user_query": "推荐一家春熙路附近适合聚餐的火锅店",
  "expected_retrieval": {
    "should_include": ["profile_taste_spicy_avoid", "event_search_chunxi_hotpot"],
    "should_exclude": ["profile_scene_romantic_date"]
  },
  "expected_recommendation_constraints": [
    "不推荐含辣的店铺", "优先川渝火锅类型", "人均 < 100", "商圈 = 春熙路"
  ]
}
```

### 评估指标

| 指标 | 计算方式 | 目标 |
|------|---------|------|
| Profile Recall | 检索返回中命中了多少 `should_include` | > 0.85 |
| Profile Precision | 检索返回中有多少真正相关 | > 0.80 |
| Constraint Compliance | Agent 推荐满足了多少 `expected_constraints` | > 0.90 |
| Hallucination Rate | 推荐是否包含标注明确排除的内容 | < 0.05 |

### 执行方式

- 非 CI 自动化，Phase 14 手动执行一次
- 脚本：`agent-service/eval/run_eval.py`，读取标注数据 → 调检索管道 + Agent → 输出指标
- 标注数据：`agent-service/eval/data/*.json`

---

## 十六、反馈闭环（Kafka 通道）

### 架构

```
Java 后端                                   Python agent
─────────                                  ─────────────
用户行为事件
  ├─ shop_card_click
  ├─ purchase_success
  └─ explicit_rejection
  │
  ▼
Kafka topic: user.behavior.feedback
  │
  ▼
FeedbackConsumer (Python agent)
  │
  ├─ 解析 trace_id → 反查引用链
  │     （推荐生成时在 shop_card SSE 中携带 trace_id，
  │       标记哪些 Profile 原子被用于本次推荐）
  │
  ├─ 更新 Neo4j Profile:
  │     shop_card_click → REINFORCE 相关 Profile (+0.1)
  │     purchase_success → 大幅 REINFORCE (+0.15)
  │     explicit_rejection → 降低 confidence (-0.1)
  │
  └─ 生成 memory_diff 审计记录（agent_role: "feedback_loop"）
```

### 反馈信号与记忆操作映射

| 信号 | 来源 | 对记忆的影响 |
|------|------|-------------|
| `shop_card_click` | 用户点击推荐卡片 | 相关 CuisinePreference/AreaPreference REINFORCE (+0.1) |
| `purchase_success` | 用户完成下单 | 相关 Profile 大幅 REINFORCE (+0.15) |
| 推荐展示但无点击 | 用户忽略推荐 | 无变化（不一定是负反馈） |
| `explicit_rejection` | 用户说"太贵了/不喜欢" | 相关 Profile 降低 confidence (-0.1) |
| 用户主动纠错 | "错了，其实是…" | DELETE 旧 + ADD 新 |

### 消息格式

```json
{
  "event_id": "evt_behav_001",
  "user_id": "u123",
  "event_type": "shop_card_click | purchase_success | explicit_rejection",
  "trace_id": "trace_rec_abc123",
  "shop_id": "shop_456",
  "timestamp": 1719696000,
  "context": { "session_id": "sess_xyz" }
}
```

### 引用链追溯

推荐生成时，`shop_card` SSE 事件携带：

```json
{
  "type": "shop_card",
  "shop": {...},
  "trace_id": "trace_rec_abc123",
  "referenced_profiles": ["profile_cuisine_001", "profile_taste_002", "profile_budget_003"]
}
```

反馈事件到达时，Consumer 通过 `trace_id` 反查到被引用的 Profile 原子，精准 REINFORCE/弱化，而不是模糊地"用户满意了但不知道是哪个因素起了作用"。

### 实现阶段

| 步骤 | 内容 | 依赖 |
|------|------|------|
| Phase 13a | Java 侧新增 Kafka topic `user.behavior.feedback` + Producer | Kafka 就绪 |
| Phase 13b | Python 侧 `FeedbackConsumer` + 引用链反查 + Neo4j 更新 | Phase 13a, Phase 4 |
| Phase 13c | `shop_card` SSE 增加 `trace_id` + `referenced_profiles` | Phase 8 |

### 初期降级方案

Kafka consumer 链路就绪前（Phase 8-12），在下一轮对话的 Profile Updater 中从对话上下文自然感知反馈（如用户说"上次那家太贵了"→ implicit rejection），不依赖独立事件链路。

---

## 十七、多 Agent 协作

独立文档：`2026-06-30-agent-team-design.md`。核心决策摘要：

| 决策 | 选择 |
|------|------|
| 协作模式 | Supervisor + Worker |
| 记忆传递给 Worker | Supervisor 按需裁剪（硬约束始终全量注入） |
| 记忆回写路径 | Worker → Supervisor 汇总 → MemoryExtractor 统一写入 |
| Supervisor 自身记忆 | 复用 AgentCase + `case_type: "orchestration"` |
| 当前 StateGraph | 不做改动，单 Agent 先跑通 |
| 扩展点预留 | `agent_case.case_type` 加枚举值、`SessionRef.parent_thread_id`、审计日志 `agent_role` 字段 |

---

## 十八、补充决策汇总

| 决策 | 选择 | 原因 |
|------|------|------|
| 冷启动 | 行为数据批量导入 + 轻量 onboarding 组合 | 覆盖有数据用户和纯新用户 |
| 用户可见性 | 对话中查看/修正记忆（同步执行） | 零前端成本，复用 DELETE/REVISE 操作 |
| 提取模型 | 独立低成本模型 | 提取是高频任务，成本需低于对话主模型的 1/5 |
| 记忆质量评估 | 50-100 条标注 → recall/precision/hallucination → A/B 测试 | 先验证正确性，再验证业务价值 |
| 反馈闭环 | 新 Kafka topic + trace_id 引用链 | 复用现有 Kafka 基础设施，精准追溯到被引用的 Profile |
| 多 Agent | Supervisor + Worker，当前预留扩展点 | 单 Agent 先落地，设计上不硬编码 |

## 关联文档

- `2026-06-29-agent-memory-redesign.md` — 记忆系统核心设计
- `2026-06-30-agent-team-design.md` — 多 Agent 协作设计
