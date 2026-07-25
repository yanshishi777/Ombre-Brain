# Gateway 自动注入能力评估：被动带入 + 主动反射弧

> 目标：落实"记忆从被调用（breath）变成被带入（Gateway 自动注入）"。
> 评估对象：gateway.py `prepare_payload` 注入管线 + brain `/api/proactive-recall`。
> 数据基准：生产环境 208 个桶（2026-07-25 实测）。

---

## 一、现状（代码层）

Gateway 收到用户消息后，在 `prepare_payload`（gateway.py:2806）里做请求分类，然后走两条互斥的主路径：

| 路径 | 触发条件 | 匹配机制 | 代码位置 |
|---|---|---|---|
| **date_recall（窄路径）** | 查询含"昨天/前天/具体日期/上次…"等时间信号（gateway.py:8337 `_query_requests_date_recall`） | 按桶的 `date/created/updated_at/last_active` **精确等于解析出的日期**做匹配（gateway.py:8457 `_bucket_matches_date_recall`）+ 拉对应日期的对话轮次/raw event | gateway.py:8086 `_build_date_recall_context` |
| **dynamic recall（宽路径 / 语义）** | 其他查询 | 关键词锚点 + 向量语义检索（`_try_semantic_rescue`）+ query planner + rerank，按相关度排序 | gateway.py:15996 `_select_dynamic_buckets` |

**关键路由陷阱**：一旦命中 `date_recall`，系统会 `skip_broad_dynamic_recall = True`（gateway.py:2964、3100），即**跳过语义宽检索和 portrait_memory**，只走 date_recall 窄路径。两条路径不会同时生效。

**主动场景（反射弧）**已存在实现：`prepare_payload` 攒够 `proactive_trigger_user_msgs`（默认 10）条用户消息后，调 `_run_proactive_recall`（gateway.py:2662）→ brain `/api/proactive-recall`（server.py:3309）。该端点：
1. 候选池 = **仅 `metadata.proactive_eligible is True` 的桶**（server.py:3341-3344）
2. 向量相似度 > `similarity_threshold`（默认 0.48）粗筛
3. LLM 对候选打 0–10 分，>= `score_threshold`（默认 9）才保留
4. 4 小时冷却，最多返回 3 条

---

## 二、数据层实测（生产 208 桶）

| 字段 | 有值桶数 | 占比 | 对哪个场景致命 |
|---|---|---|---|
| `date`（事件日期） | **2 / 208** | 0.96% | 被动·日期类问句 |
| `proactive_eligible = True` | **0 / 208** | 0% | 主动·反射弧 |
| `last_active` | 208 / 208 | 100% | 非事件日期，是"最近被召回"时间 |
| `created` | 208 / 208 | 100% | 创建时间，非事件发生时间 |
| `dehydration_state` | 14 / 208 | 仅新桶 | 延迟脱水状态 |

**结论先行**：两个场景目前都"机制存在、数据不支持"。

---

## 三、场景一（被动带入）能力评分：半够 / 不够

### 1a. "上次听歌是什么时候"（无具体日期）
- 因"上次"解析不出具体日期 → **不触发 date_recall** → 落入 dynamic recall 语义宽路径。
- dynamic recall 本身是存在的、且有多路召回（关键词 + 语义救援 + query planner），理论上能靠"听歌"向量命中对应桶。
- **但有两个软肋**：
  - 准入阈值偏高：`recall_admission_semantic_score`(默认 0.72)、`recall_admission_rerank_score`(默认 0.65)，口语化问法容易卡在门槛外。
  - **无"时间排序"逻辑**：它返回的是"最相关"的桶，不是"最近一次听歌"的桶。模型需要自己从返回桶的元数据里读日期再回答"什么时候"——能答，但不稳。
- 评分：**机制可支撑，命中率中等，对时间类问法不鲁棒**。

### 1b. "昨天一起听歌"（具体日期）
- 命中 date_recall → 跳过语义宽路径 → 只按桶 `date == 昨天` 精确匹配。
- 但生产桶只有 **2/208** 有 `date` 字段，且这 2 个未必是"听歌"桶。
- 退路是 date_recall 还会拉"昨天"的对话轮次/raw event（gateway.py:8180），**前提是那些对话被记录进了 raw_event_store**；若没记，则这次查询直接落空。
- 评分：**当前基本失败**。用户最在意的"具体历史问句"恰恰走在最弱的那条窄路径上。

> 讽刺点：你之前看到的"调用工具: breath"之所以发生，正是因为自动注入（尤其 date 类）覆盖不足，模型被迫自己调 breath 补救。你的方向完全正确。

---

## 四、场景二（主动反射弧）能力评分：不够（致命缺口）

- 反射弧代码链路完整、默认开启（`proactive_recall_enabled` 默认 True，触发 10 条消息）。
- **但候选池要求 `proactive_eligible is True`，而生产 0/208 个桶带此标记** → 每次主动回忆都返回空，永远浮不出任何旧事。
- 这不是阈值问题，是"候选池为空"的硬阻断。
- 评分：**机制完备、数据层完全未供给，当前零产出**。

---

## 五、需要加强的点（按杠杆排序）

### P0 — 数据层补字段（一次性迁移脚本，最高杠杆）
1. **给存量桶补 `date`（事件发生日期）**：从 `created`/`last_active`/内容里推断事件日期写入 `date`。这是让 date_recall 从"2/208"变"全覆盖"的唯一办法。
2. **给存量桶打 `proactive_eligible=True`**：建议默认给 `dynamic`/`permanent` 类型打标（排除 `dont_surface`、`deleted_at`、`archived`、feel/anchor 类），让反射弧有候选可挑。

### P1 — 路由修正（不改数据也该做）
3. **date_recall 命中失败时回退到 dynamic recall**：当前"命中 date_recall 就跳过语义"太武断。建议：date_recall 若未找到任何 material（`no_material`，gateway.py:8150），自动降级走 `_select_dynamic_buckets`，而不是整轮只靠日期窄匹配。
4. **具体日期问句也并行跑语义**：至少在 date_recall 之外，追加一次语义宽检索补充上下文（打破两条路径互斥）。

### P2 — 召回策略增强
5. **dynamic recall 增加"时间排序"模式**：对"上次/最近一次 X 是什么时候"类问句，在语义命中后按事件日期取最近一条，而不是纯相关度。
6. **放宽准入阈值**：对历史事实类问法，`recall_admission_semantic_score` 从 0.72 降到 ~0.6，并允许"日期+主题"组合命中绕过单路门槛。

### P3 — 主动场景调参
7. 显式在部署配置里确认 `gateway.proactive_recall.enabled = true`。
8. `trigger_user_msgs` 从 10 降到 4–6，让反射弧更早出现。
9. `score_threshold` 从 9 降到 ~7，"偶尔提起"本就该宽松；`cooldown_hours` 保持 4 即可。

---

## 六、建议实施顺序

1. **先跑 P0 迁移脚本**（补 `date` + `proactive_eligible`），这是两个场景共同的地基。
2. 部署后，场景二（反射弧）立即从"零产出"变"可用"，先验证它。
3. 再做 P1 路由修正，把"昨天一起听歌"从落空变"日期窄匹配 + 语义兜底"。
4. 最后 P2/P3 调参打磨召回率与主动浮现频率。

---

## 七、一句话结论

Gateway 的自动注入**框架已经具备**（语义检索 + 日期回忆 + 主动反射弧三条线都在代码里），但**数据层没有供给**——`date` 字段覆盖率 1%、`proactive_eligible` 覆盖率 0%，导致"具体历史问句"和"主动提起旧事"两个核心场景今天都跑不起来。最该先做的是一份给存量桶补 `date` 和 `proactive_eligible` 的一次性迁移脚本，其次修正 date_recall 命中失败不回退语义的路由缺陷。
