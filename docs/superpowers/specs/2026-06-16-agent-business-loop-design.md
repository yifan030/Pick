# Agent 业务闭环 + 代码整理迭代计划

## 背景

MVP 已完成：单轮推荐、流式输出、商品卡片、多轮记忆、优惠券查询下单、内容安全。当前 agent 侧代码存在目录结构混乱（工具文件职责过多、HTTP 客户端重复），且业务闭环仅覆盖到下单，缺少售后、收藏、到店、复购等场景。未来开发重点全部在 agent 侧。

## 目标

1. 整理 agent 目录结构，消除重复，明确职责边界
2. 补齐下单 → 售后 → 收藏 → 到店 → 复购的完整业务闭环

## 当前 Agent 结构

```
src/agent/
  agent.py            # agent 工厂 + SYSTEM_PROMPT
  chat.py             # SSE 流式辅助（命名模糊）
  config.py           # 模型配置
  middleware.py        # 日志 + 内容安全
  redis_history.py    # Redis 会话持久化
  tools/
    retrieval.py      # RAG 检索（391行，含 Milvus 客户端、搜索、合并、格式化）
    voucher.py         # 券查询（含独立 httpx 客户端）
    purchase.py        # 下单（含独立 httpx 客户端，与 voucher 重复）
```

## 迭代计划

### 迭代 1：抽共享基础设施

**目标**：不动功能，消除重复，理顺目录。零用户可见变化。

**动作**：

| 从 | 到 | 搬什么 |
|---|---|---|
| `tools/retrieval.py` | `services/milvus.py` | `_get_milvus_client`, `_search_shop_desc`, `_search_user_note`, `_normalize_results`, `_merge_results`, `_build_filter_expr`, 常量 |
| `tools/voucher.py` + `tools/purchase.py` | `services/java_client.py` | 统一 `JavaClient` 类：base_url + auth header + 超时，消除重复 |
| `chat.py` | `stream.py` | 纯重命名，`stream_agent_response()` 不变 |
| `tools/retrieval.py` 保留 | 保留 | 只留 `search_shops` @tool + `_format_context_for_llm` + `_format_shop_card` |

**目标结构**：

```
src/agent/
  agent.py
  config.py
  middleware.py
  stream.py           # 原 chat.py
  redis_history.py
  tools/
    __init__.py
    retrieval.py      # ~80 行
    voucher.py        # ~60 行
    purchase.py       # ~70 行
  services/
    __init__.py
    milvus.py         # MilvusClient 单例 + 搜索 + filter builder
    java_client.py    # httpx 客户端单例
```

**不改**：agent.py、SYSTEM_PROMPT、前端、Java 侧。

---

### 迭代 2：下单全链路增强

**目标**：下单不是终点，补齐售后链路。

| 场景 | 用户输入 | 新增 Tool | Java 依赖 |
|---|---|---|---|
| 订单状态 | "刚才那单怎么样了？" | `check_order_status(order_id)` | 新增 GET 内部接口 |
| 订单历史 | "我买过哪些券？" | `list_my_orders(user_id, status)` | 新增 GET 内部接口 |
| 退款申请 | "这个券能退吗？" | `request_refund(order_id, reason)` | 新增退款内部接口 |
| 核销指引 | "怎么用这个券？" | Agent 从订单数据提取核销码直接回复 | 复用已有 |

**下单流程增强**：已有 `place_order` + HumanInTheLoop，增加地址校验环节。

---

### 迭代 3：收藏与提醒

**目标**：收藏替代购物车（团券场景下购物车无意义），秒杀提醒复用已有 Java 能力。

| 场景 | 用户输入 | 新增 Tool | Java 依赖 |
|---|---|---|---|
| 收藏店铺 | "先收藏这家店" | `bookmark_shop(shop_id)` | 新增收藏接口 |
| 查看收藏 | "我的收藏有哪些？" | `list_bookmarks(user_id)` | 同上 |
| 取消收藏 | "取消收藏这家" | `remove_bookmark(bookmark_id)` | 同上 |
| 秒杀提醒 | "秒杀时提醒我" | `set_voucher_alert(voucher_id)` | **已有 subscribe 接口，直接复用** |
| 分享推荐 | "推荐给朋友" | Agent 生成分享文案 | 无 |

---

### 迭代 4：到店场景

**目标**：从线上决策延伸到线下到店。

| 场景 | 用户输入 | 新增 Tool | Java 依赖 |
|---|---|---|---|
| 店铺导航 | "这家怎么去？" | Agent 用经纬度数据，前端调起地图 | 无 |
| 排队取号 | "帮我排个号" | `queue_reservation(shop_id, guests)` | 新增排队接口 |
| 电话预约 | "帮我约今晚 7 点" | `make_reservation(shop_id, time, guests)` | 新增预约接口 |
| 营业确认 | "现在开门吗？" | Agent 用已有 open_hours 直接回答 | 无 |

---

### 迭代 5：评价与复购

**目标**：用户产生内容，偏好驱动复购。

| 场景 | 用户输入 | 新增 Tool | Java 依赖 |
|---|---|---|---|
| 写评价 | "这家不错，帮我写评价" | `post_review(shop_id, rating, content)` | 新增评价接口 |
| 复购推荐 | "上次那个还能买吗？" | `list_my_orders` + `query_vouchers` 组合 | 无 |
| 同类推荐 | "有没有跟上次类似的？" | RAG 以历史偏好查询相似店铺 | 无 |

---

## 迭代节奏

```
迭代1 → 迭代2 → 迭代3 → 迭代4 → 迭代5
 1-2天   2-3天   2-3天   2-3天   1-2天
```

每个迭代独立可交付，不互相阻塞。Java 侧接口跟每个迭代同步补齐。

## 设计原则

- 每个迭代不积累代码债务
- tools/ 只放 @tool 函数，services/ 放基础设施
- 新增 tool 一律使用共享 `java_client`，不复制 HTTP 逻辑
- SYSTEM_PROMPT 每个迭代按需追加，保持精简
- 前端在业务闭环阶段不做结构性改动，通过 SSE 事件的字段扩展来传递新信息
