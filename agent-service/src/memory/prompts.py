# src/memory/prompts.py
"""LLM prompts for memory extraction pipeline.

All prompts are designed for small/cheap models (e.g., gpt-4o-mini, haiku)
to keep extraction costs low. They expect structured JSON output.
"""

# ── Event Extraction ──────────────────────────────────────────────────

EVENT_EXTRACTION_PROMPT = """从以下对话回合中提取用户行为事件。以 JSON Lines 格式输出，每行一个完整的 JSON 对象，不要外层数组括号。

事件类型（event_type）：
- search: 用户搜索/查找店铺
- purchase: 用户完成购买/下单
- reservation: 用户预约/排队
- view: 用户浏览/查看店铺详情或优惠券
- feedback: 用户对推荐结果的反馈（喜欢/不喜欢/太贵/太远等）
- constraint: 用户表达的约束条件（不吃辣、要包间、人均预算等）
- dietary: 用户的饮食硬约束（清真、素食、过敏原等）— 这是硬约束，与口味偏好区分

特别注意：
- dietary 类型：用户提到的饮食约束（清真、素食、过敏原、糖尿病饮食等），is_hard=true
- constraint 类型：口味偏好/软约束（"不吃辣"、"不要香菜"），is_hard=false
- "今天想吃辣" → 不形成事件（transient，临时性的）
- "最近减肥，不吃碳水" → constraint 类型，可设 ttl_seconds=2592000（30天）
- "我是回民/清真" → dietary 类型，is_hard=true

输出格式（每行一个 JSON 对象，不要外层数组括号）：
{{"event_type":"search","description":"用户在春熙路搜索川渝火锅","payload":{{"query":"火锅","area":"春熙路","category":"川渝火锅"}},"ttl_seconds":null}}
{{"event_type":"dietary","description":"用户明确表示清真饮食要求","payload":{{"constraint":"清真","type":"religious"}},"is_hard":true,"ttl_seconds":null}}
{{"event_type":"constraint","description":"用户表示今天不想吃辣","payload":{{"constraint":"不吃辣"}},"ttl_seconds":86400}}

对话：
用户: {user_message}
助手: {assistant_response}
工具调用: {tool_calls}
"""

# ── Profile Update ────────────────────────────────────────────────────

PROFILE_UPDATE_PROMPT = """你已知该用户当前的偏好档案（仅包含与本轮对话相关的已有偏好）：

{existing_profiles}

从本轮对话中判断以下用户的偏好变化。对每条变化，输出一个 JSON 对象（每行一个）。

操作类型（op）：
- ADD: 新的偏好（之前没有的），confidence=0.6
- REINFORCE: 已有偏好再次体现，旧 confidence += 0.1（上限 0.95），reinforce_count += 1
- REVISE: 偏好变更（与已有偏好矛盾），旧 confidence→0.2，新 preference 从 0.6 起步
- DELETE: 用户明确纠错（"我说错了"、"其实是"、"不对"），直接删除旧原子
- MERGE: 多个同类型原子语义相似应合并
- NOCHANGE: 本轮未涉及该偏好
- EXPIRE: 标记为过期（TTL 到期）

判断规则：
1. 用户表达与已有偏好矛盾 → REVISE
2. 用户明确纠错（"错了/不对/其实是"）→ DELETE 旧 + [可选 ADD 新]
3. 只是未提及已有偏好 → NOCHANGE（后台定时任务处理衰减，你不需要在此处理）
4. "今天想吃辣" → 不形成偏好（transient），不输出任何操作
5. "最近减肥，不吃碳水" → ADD 带 ttl_seconds=2592000（30天）
6. "我最近爱吃/一直爱吃辣" → ADD 或 REINFORCE
7. 硬约束（is_hard=true）不可被 REVISE → 输出 NOCHANGE，reason 说明"硬约束需用户显式确认才能变更"
8. 两个同类型原子语义相似（如"火锅"和"川渝火锅"）→ MERGE

偏好类型（target_type）：
- TastePreference: 口味偏好，属性 property + value（like/avoid）
- DietaryPreference: 饮食硬约束，属性 constraint + type（religious/health/allergy/ethical）
- BudgetPreference: 预算范围，属性 range_min + range_max + type（per_person/total）
- CuisinePreference: 菜系偏好，属性 cuisine + weight
- AreaPreference: 商圈偏好，属性 area + weight
- ScenePreference: 场景偏好，属性 scene + weight
- ConstraintPreference: 软约束，属性 constraint + type

输出格式（每行一个 JSON）：
{{"op":"REINFORCE","target_type":"CuisinePreference","target_id":"profile_cuisine_001","new_value":{{"cuisine":"川渝火锅","confidence":0.85,"reinforce_count":4}},"reason":"用户再次搜索川渝火锅"}}
{{"op":"ADD","target_type":"CuisinePreference","new_value":{{"cuisine":"粤菜","confidence":0.6,"weight":0.7}},"reason":"用户表示最近爱上吃粤菜"}}
{{"op":"REVISE","target_type":"TastePreference","target_id":"profile_taste_001","old_value":{{"property":"spicy","value":"like","confidence":0.75}},"new_value":{{"property":"spicy","value":"avoid","confidence":0.6}},"reason":"用户明确表示不吃辣了"}}
{{"op":"DELETE","target_type":"ConstraintPreference","target_id":"profile_constraint_003","old_value":{{"constraint":"不吃牛肉","confidence":0.5}},"reason":"用户明确纠错：'之前说错了，我其实吃牛肉'"}}

本轮对话：
用户: {user_message}
助手: {assistant_response}
本轮提取的事件: {events}
"""

# ── Session Summarization ─────────────────────────────────────────────

SESSION_SUMMARY_PROMPT = """将以下对话回合的要点总结为一段简洁的自然语言摘要（不超过 200 字），并提取关键实体。

输出 JSON 格式：
{{"summary":"用户在春熙路附近搜索了火锅和粤菜，预算人均100以内，最终查看了蜀大侠的优惠券但未下单","key_shops":["shop_123","shop_456"],"key_areas":["春熙路"],"intent":"recommend_shop"}}

对话回合：
{round_content}
"""

# ── Session Final Merge ──────────────────────────────────────────────

SESSION_FINAL_MERGE_PROMPT = """将以下多轮会话的增量摘要合并为一个完整的最终摘要（不超过 400 字）。

输出 JSON 格式：
{{"summary":"完整的会话摘要...","key_shops":["shop_1","shop_2"],"key_areas":["春熙路","太古里"],"intent":"recommend_shop"}}

增量摘要列表：
{round_summaries}
"""

# ── Agent Case Extraction ────────────────────────────────────────────

AGENT_CASE_EXTRACTION_PROMPT = """从以下推荐交互中提取 Agent 经验案例。如果推荐产生了明确的用户反馈（点击、购买、拒绝、忽略），提取为一条经验。

输出 JSON 格式（如果没有可提取的经验，输出空对象 {{}}）：
{{"case_type":"recommendation","description":"用户搜索春熙路火锅，Agent推荐了蜀大侠和川西坝子","context":{{"intent":"recommend_shop","area":"春熙路","category":"川渝火锅","budget_range":[50,100],"user_constraints":["不吃辣"]}},"action":"推荐粤菜馆点都德和潮汕牛肉火锅","outcome":"success","outcome_reason":"用户点击了点都德并查看了优惠券","lesson":"用户表示不吃辣但搜索火锅时，优先推荐粤菜等不辣的高评分类别"}}

交互信息：
用户查询: {user_query}
Agent 推荐: {recommendations}
用户反馈: {user_feedback}
"""

# ── Consolidation Merge Judgment ─────────────────────────────────────

CONSOLIDATION_MERGE_PROMPT = """判断以下两个偏好原子是否应该合并为一个。如果应该合并，输出合并后的新原子。

原子A: {atom_a}
原子B: {atom_b}

输出 JSON 格式：
如果应合并：{{"should_merge":true,"merged":{{...完整的新原子...}},"reason":"合并原因"}}
如果不合并：{{"should_merge":false,"reason":"不合并原因"}}
"""
