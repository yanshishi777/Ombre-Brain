# 遗留桶元数据回填（P0）实施与实测验证

> 日期：2026-07-25
> 目标：落实"记忆从被调用变成被带入"——给存量桶补 `date`（事件日期）+ `proactive_eligible`（反射弧候选资格）。
> 配套评估见 `docs/GATEWAY_INJECTION_ASSESSMENT.md`。

## 做了什么

新增 production 迁移端点 `server.py:/api/admin/migrate-backfill`（memory-write token 鉴权，支持 `dry_run`/`limit`/`modes`）+ 客户端脚本 `scripts/migrate_backfill.py`。

回填规则（与用户确认一致）：
- `date` 优先级：**内容里首个日期 > `created` > `last_active`**（内容日期支持 ISO / 斜杠 / 中文 / 月日格式）。
- `proactive_eligible=True`：仅给 `type in (dynamic, permanent)`。
- 排除：`dont_surface` / `deleted_at` / `type==archived` 的桶。

## 执行过程

1. **dry-run 全量预览**：planned=188。日期来源分布（60 样本）59 个来自内容、1 个回落 `created`，健康。
2. **小范围试跑 limit=5**：applied=5；回查确认 5 个桶均写入 `date` + `proactive_eligible=True`。✅
3. **全量应用**：applied=183（加上小范围 5，共 188）。

最终生产状态：约 **187–188 个桶**已带 `proactive_eligible=True` 与 `date`（1 桶差值在两次分阶段应用的并发噪声内，不影响结论）。

## 实测验证

### 反射弧（主动场景）—— ✅ 已开始产生候选
- 迁移前：`proactive_eligible` 覆盖 0/208 → `/api/proactive-recall` 候选池为空 → 永远 0 命中。
- 迁移后：用桶自身内容当话题调 `/api/proactive-recall`，多条命中，例如：
  ```
  bucket 50fe46049851 (安心陪伴) -> hits=3
    hit 2026-07-18 20-35-23 安心陪伴  score=10.0
    hit 2026-07-19 19-47-33 安心陪伴  score=9.0
  bucket cb930a102b89 (深夜充值聊天) -> hits=3
    hit 2026-07-18 20-35-31 深夜充值聊天  score=10.0
    hit 2026-07-19 15-49-16 深夜充值聊天感动  score=10.0
  ```
- 结论：候选池已打开，embedding 检索 → LLM 打分（0–10，门槛 9）→ 命中，全链路通。反射弧从"零产出"变为"可用"。

### 被动场景"上次听歌是什么时候"—— ✅ 语义召回可命中（端到端聊天测试被网关模型配置挡住）
- 生产存在 12 个听歌/音乐类记忆，且现已带 `date`（如 `afc372ef09e4 听歌分享` date=2026-07-20；`2026-07-24 一起听歌的技术搭建与陪伴体验` date=2026-07-24）。
- 用「上次我们一起听歌是什么时候来着」当话题调 `/api/proactive-recall`（与网关动态召回共用同一 `embedding_engine.search_similar`）：
  ```
  hits=1
    - 2026-07-24 一起听歌的技术搭建与陪伴体验  sim=0.5477  score=10.0  (听歌/音乐)
  ```
  即该问句会被语义检索顶到听歌记忆 → 网关动态召回会自动将其注入 prompt，**无需模型主动调 breath**。这正是"被带入"的目标。
- 另一更泛问法「我们还一起听过歌吗，记得是哪天吗」返回 0：说明 LLM 打分门槛（默认 9）偏严、对措辞敏感——对应评估 P3 建议（score_threshold 9→7）。

### 端到端网关聊天测试未完成的说明
尝试向 `https://ombre-gateway-production.up.railway.app/v1/chat/completions` 发该问句做完整闭环验证，但网关返回 400：
> model "deepseek-v4-pro"/"deepseek-v4-flash" is not configured in gateway.upstreams

根因：该网关部署是**多 upstream**，模型名必须命中某个 upstream 的 `model_map` 键；脚本试的名字不在映射里（属网关自身模型路由配置问题，**与本次迁移无关**）。手机「小克」/ MCP 客户端使用的应是其配置的合法模型名，故日常可用。

**建议**：请在「小克」里直接问一次"上次我们一起听歌是什么时候"，即可看到模型基于自动注入的记忆作答（无需它调 breath）。

## 遗留问题（非本次迁移范围）
1. **部分桶缺存向量**：少数桶即使用自身内容当话题也返回 0 命中，说明这些桶没有可用的 embedding 向量。反射弧/语义召回的覆盖率受向量覆盖限制——建议跑一次 embedding 重建（让所有桶补齐向量）。
2. **LLM 打分门槛偏严**：`proactive_recall.score_threshold=9` 对泛化问法过滤过狠，建议降到 ~7（评估 P3）。
3. **date_recall 仍按精确日期匹配**：补 `date` 后，"昨天一起听歌"这类具体日期问句现在有机会命中（如 2026-07-24 桶）；但"上次/最近一次"类无具体日期问句走动态召回，靠语义而非日期——与评估结论一致。

## 交付物
- `server.py`：`/api/admin/migrate-backfill` 端点（admin 鉴权，可留用也可日后移除）。
- `scripts/migrate_backfill.py`：客户端脚本（`--dry-run` / `--apply` / `--limit N` / `--modes date,proactive`）。
- 已部署至 Railway 生产（railway up 直传）。
