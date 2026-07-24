# 延迟脱水机制（Delayed Dehydration）

> 状态：已实现，并已通过 `railway up` 上线到 Railway 生产环境（2026-07-25 验证）。代码位于 `yanshishi777/Ombre-Brain` 的 `feat/delayed-dehydration` 分支（也含在本地 `main`）。

## 1. 目标

最近 N 天（默认 7 天，可调）内的 `dynamic` 记忆保持**原文存储**，不立刻脱水压缩；
超过时间窗口后，由 worker 自动跑脱水流程，把这批内容压成高密度摘要并固化。

设计意图：
- 近期记忆保留完整细节与情感浓度，召回时更真实自然；
- 时间久了自然压缩成摘要，控制存储成本，也符合"记忆随时间自然淡化"的逻辑。

## 2. 设计问答（当初评估的 5 个问题）

**Q1. 现有脱水机制能否加时间窗口判断（只处理超 N 天内容）？**
能。注入层已改造为按 `dehydration_state` + 距上次激活天数判断；历史桶（无 `dehydration_state`）保持原"实时脱水"行为，向后兼容。

**Q2. 是否需要新增定时任务来扫描触发？**
是。新增 `scripts/delayed_dehydration_worker.py` 扫描超期 `fresh` 桶并固化脱水。
可两种调度：
- worker 自带 `--loop --interval-minutes N` 常驻循环；
- 或外部 cron / 定时任务周期性调用 `POST /api/delayed-dehydrate`（不带 `dry_run`）。

**Q3. N 天具体数值建议设多少？**
默认 **7 天**（`dehydrated_freshness_days`）。理由：一周覆盖了大多数"近期上下文"需求，
又不会让未脱水原文无限堆积。可用环境变量 `OMBRE_DEHYDRATE_FRESHNESS_DAYS` 随时覆盖，无需改代码。

**Q4. 召回近期原文是否会因过长挤占 token 预算？**
会控制。保鲜期内原文经过 `_clip_text` 截断到 `RAW_RECALL_CHAR_CAP = 1500` 字再注入，
单独的长度上限避免挤占 recall token 预算。

**Q5. 原文依赖语境突兀的问题，摘要是否同样存在？原文是否更严重？**
两者都依赖语境，但原文更严重（长且细、信息密度低）。缓解方式：
- 保鲜期内用 1500 字截断，降低单条长度；
- 超期桶由 worker **提前**脱水并固化，召回时直接取已存摘要，不再现场拉原文，避免突兀；
- 摘要本身也带 `raw_content` 备份，必要时可回溯。

## 3. 存储字段（bucket frontmatter）

| 字段 | 取值 | 说明 |
|------|------|------|
| `raw_content` | str / null | 原文备份；worker 脱水后写入，便于回溯 |
| `dehydration_state` | `"fresh"` / `"dehydrated"` / null | `fresh`=保鲜期；`dehydrated`=已固化脱水；null=历史桶（向后兼容） |
| `dehydrated_at` | ISO 时间 / null | 脱水完成时间 |

新桶（`dynamic` 且非 pinned/protected）创建时 `dehydration_state` 默认 `"fresh"`；其余类型不设该字段，保持原实时脱水行为。

## 4. 配置项

| 配置 | 默认 | 覆盖方式 |
|------|------|----------|
| `dehydrated_freshness_days` | 7 | 环境变量 `OMBRE_DEHYDRATE_FRESHNESS_DAYS`（正整数） |
| `transport` | `stdio` | 环境变量 `OMBRE_TRANSPORT=sse`（HTTP 模式才暴露 `/api/*` 路由，否则只跑 MCP stdio） |

## 5. 召回注入层 `_recall_render_content(bucket)`

- `state == "dehydrated"` → 返回已存摘要（`_format_output(content, meta)`），**不调 API**；
- `state == "fresh"` 且 `days_since_last_active <= N` → 返回原文（`_clip_text(raw, 1500)`），**不调 API**；
- 其余（fresh 超期待处理 / 历史桶无 state）→ 实时脱水（原行为，需 `OMBRE_API_KEY`）。

> 替换了 recall 路径上 6 处原来的 `dehydrator.dehydrate(...)` 调用（保留 `diffused` 联想、resurface 两条弱相关/超期路径走原实时脱水）。

## 6. Worker：`scripts/delayed_dehydration_worker.py`

只处理满足以下全部的桶：
- `type == "dynamic"`
- 非 `pinned` 且非 `protected`
- `dehydration_state == "fresh"`
- `days_since_last_active > N`

`write` 模式对每个命中桶：调 `dehydrator.dehydrate(...)` → 更新
`content=摘要, raw_content=原文, dehydration_state="dehydrated", dehydrated_at=now`。

参数：`--dry-run`（默认，只列不写） / `--write` / `--freshness-days N` / `--limit K` / `--loop` / `--interval-minutes M`。

> **实际上线采用「进程内常驻循环」**（而非独立 worker 进程）：在 `server.py` 的 sse 启动块里启一个 daemon 线程循环（沿用 reflection/dream 同一定式），周期调用 `run_delayed_dehydration(dry_run=False, limit=50)`。这样与 brain 共享同一 `bucket_mgr` 与数据，避免跨服务文件系统不一致。
> 配置项：
> - `delayed_dehydration_loop`（默认 true；env `OMBRE_DD_LOOP=0`/`false`/`no`/`off` 可关闭）
> - `delayed_dehydration_loop_minutes`（默认 60；env `OMBRE_DD_LOOP_MINUTES` 覆盖）
> 独立 `scripts/delayed_dehydration_worker.py` 仍可用（本地调试或单独部署），但生产环境走进程内循环。

## 7. HTTP 端点

`POST /api/delayed-dehydrate`
- 鉴权：Bearer，令牌取 `OMBRE_DEHYDRATION_TOKEN` 或回退 `OMBRE_GATEWAY_TOKEN`
- Body：`{"dry_run": true, "freshness_days": 7, "limit": 50}`
- 返回：`{"freshness_days": 7, "scanned": 0, "due": 0, "processed": [], "dry_run": true}`

## 8. 部署

- **代码位置**：`yanshishi777/Ombre-Brain` @ `feat/delayed-dehydration`（也含在本地 `main`，提交 `1e2a6b9`）。
- **更正 earlier 误判**：Railway 的 ombre-brain 服务实际连接的就是 `yanshishi777/Ombre-Brain`（用户自己的仓库），
  并非 `Yinglianchun`——之前那次 403 是误推到 `Yinglianchun` 远程被拒。因此无需改 GitHub 授权。
- **实际上线方式**：`railway up --service ombre-brain --environment production --yes`
  （railway CLI 5.28.0，路径 `/c/Users/91543/.workbuddy/binaries/node/workspace/node_modules/.bin/railway`，
  登录态 915439839@qq.com 有效；部署前加 `.railwayignore` 排除 `CREDENTIALS.md`/`buckets`/`fix_address.py`）。
  该命令把"本地目录"直传部署，覆盖当前运行实例（最新部署 ID `10598d8e-16ff-4ead-9ee2-cbe4010e787e`，transport 为 `streamable-http`）。
  ⚠️ 注意：`railway up` 是本地直传，会**脱离 GitHub 自动部署**；若以后想恢复"push 即部署"，
  可在 Railway 后台把该 service 的源分支设为 `feat/delayed-dehydration`（仓库已是 yanshishi777，无需重新授权）。
- **本地运行（调试用）**：`OMBRE_TRANSPORT=sse python server.py`（需配 `OMBRE_API_KEY` / `OMBRE_BASE_URL` 才能实际脱水）。
- **常驻循环已启用（生产）**：`server.py` sse 启动即拉起延迟脱水 daemon 线程循环（日志见 `Delayed dehydration scheduler enabled`），每 60 分钟把超期 `fresh` 桶固化脱水；无需额外 cron / worker 进程。

## 8.1 关于存量 188 个历史桶的行为（重要）

生产环境现有约 188 个 `dynamic` 桶是**本功能上线前**创建的，它们的 frontmatter **没有 `dehydration_state` 字段**（值为 null）。
按设计，worker 只处理 `state == "fresh"` 的桶，因此这 188 个存量桶被视为"历史桶"，**继续走原实时脱水行为**，不会被延迟脱水机制接管。

- 新创建的 `dynamic` 桶（上线后）才会带 `state="fresh"`，享受"7 天保鲜原文 + 超期自动脱水"。
- 若希望存量桶也纳入延迟脱水（例如让 7 天前的旧记忆先保持原文、再超期脱水），需要一次性的迁移脚本把存量 `dynamic` 桶补写 `dehydration_state="fresh"`，再让 worker 处理超期部分。该迁移会改变存量记忆的召回行为，**默认不做**，需要时可单独执行。

## 9. 验证记录（2026-07-25）

### 9.1 本地（代码即生产代码）
- `POST /api/delayed-dehydrate` dry-run 返回 200，结构合法，`freshness_days=7` 正确读取。
- 3 个合成 `dynamic` 桶（近期 fresh / 超期 fresh / 已脱水）：
  - `scanned=3, due=1`，仅**超期 fresh** 命中；近期 fresh 与已脱水均被正确跳过。
- `_recall_render_content`：
  - 近期 fresh → 返回原文（截断 1500，保留细节）✅
  - 已脱水 → 返回已存摘要 ✅
  - 超期 fresh（worker 尚未处理）→ 回退实时脱水（沙箱无 `OMBRE_API_KEY` 故抛"API 不可用"，属预期兜底路径正确接线）✅

### 9.2 生产环境（Railway，部署后实测）
- 新部署 `10598d8e-...`（transport `streamable-http`）上线，`GET /health` 返回 200。
- Railway 日志确认常驻循环启动：`Ombre Brain starting | transport: streamable-http` → `Delayed dehydration scheduler enabled / 延迟脱水定时器已启用` → `Application startup complete`。
- `POST /api/delayed-dehydrate` dry-run 返回 200，扫到**真实生产数据 188 个 dynamic 桶**：
  `{"freshness_days": 7, "scanned": 188, "due": 0, "processed": [], "dry_run": true}`。
  - `scanned=188` 证明端点已对接真实桶数据；
  - `due=0` 因为 188 个均为存量历史桶（`dehydration_state=null`，非 `fresh`），按设计跳过，常驻循环当前暂无事可做，符合预期。
- 本地另做了**写路径端到端测试**（mock 脱水 API）：超期 fresh 桶经 `run_delayed_dehydration(dry_run=False)` 后 `dehydration_state` 变为 `dehydrated`、`content` 为摘要、`raw_content` 保留原文、`dehydrated_at` 已写，验证通过。
- 召回注入层 `_recall_render_content` 与端点同属已部署的 `server.py`，逻辑已在 9.1 验证一致。
