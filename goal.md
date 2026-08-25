AI 小镇 Web 游戏

目标
借助 AI 辅助开发工具，从 0 到 1 完成一个可运行、可体验的 Web 版 AI 小镇 MVP。
小镇里有若干名 NPC，每人有自己的属性和性格，能根据当前状态自主决定下一步行动。玩家可以观察小镇、查看 NPC、与 NPC 对话，并可影响世界状态。
不要求复刻斯坦福小镇，不要求复杂系统。
重点：你能否把需求拆清楚、把系统做出来、把 AI 真正用起来，并讲明白你做了什么、为什么这么做。
要求
●能本地启动并演示，最好能提供可访问地址；
●至少 2 个地点、2 名性格/属性有明显差异的 NPC；
●玩家可查看 NPC 信息，并与其对话；
●NPC 不靠写死的脚本循环，能依据自身状态决定下一步行动；
●前端通过后台 API 与数据交互，后台可保存/恢复世界状态；
●至少接入一次真实 AI 调用（用于决策或对话），未配置密钥时有可体验的降级方案；
●一份 README，说明怎么跑、用了什么技术、AI 怎么接入、你本人做了哪些关键决策。
技术栈、架构、接口设计、数据结构、NPC 人设与地图，全部由你决定，并自行在文档中说明取舍。
评估
1.能否按 README 启动并跑通主流程；
2.NPC 是否真的「自主决策」（而非固定动画 / 固定文案）；
3.不同人设的 NPC，其行为或对话是否有可辨识的差异；
4.AI 调用失败或未配置密钥时，能否降级到可体验模式；
5.候选人能否解释关键模块，并现场改一段代码；
6.工程基本素养：配置管理（密钥不入库）、错误处理、至少一处自动化测试。
交付物
●源代码（前端 + 后台 + 初始化数据 + .env.example）；
●技术方案文档（玩法、技术选型、接口与决策设计、AI / Mock 模式、你本人的关键决策与一处 AI 修改案例；可独立成文档，也可作为 README 专章）；
●可访问的线上体验地址（公开可访问的 Web 地址；若资源受限无法长期开放，需注明有效期及替代演示方式）；
●视频录制讲解（边操作边讲解，覆盖查看小镇、NPC 行动、对话及 AI 降级，3–5 分钟为宜）。

---

# 基础架构与设计（技术方案草案）

> 以下为在原始要求之上补充的技术选型与设计文档。参考了 2025 年港科大团队的多智能体沙盒作品 [Aivilization](https://hkust.edu.hk/news/hkust-launches-worlds-largest-ai-powered-educational-sandbox-game-advancing-ai-literacy-and)（10 万 AI agent 的 MMO 式社会模拟），取其可落地于 MVP 的设计思想，不复刻其规模。

## 0. 从 Aivilization 借鉴什么

| Aivilization 的做法 | 本项目的裁剪落地 |
|---|---|
| 三层架构：社会层 / 个体层 / 认知层 | 简化为两层：**世界模拟层**（tick 循环、地点、时间）+ **NPC 认知层**（状态 → 决策 → 行动 → 记忆） |
| 日记式记忆：短期事件 + 长期信念/情绪 | 短期记忆 = 最近 N 条事件环形缓冲；长期记忆 = LLM 定期摘要成「日记」 |
| MBTI 人格影响行为偏好 | 每个 NPC 有 personality 字段（人设 prompt + 数值化偏好权重），驱动可辨识的行为/对话差异 |
| 「游戏模式 / 数据模式」双视图 | 前端提供像素地图视图 + NPC 详情面板（属性、当前动作、记忆日志可视化） |
| 每 agent 每月 $2 的成本控制 | 用小模型 + 结构化 JSON 输出 + 低频决策（仅在 tick 到点或玩家交互时调用），无密钥时降级为规则引擎 |

## 1. 技术栈总览

| 层 | 选型 | 理由 |
|---|---|---|
| 前端框架 | **React 18 + TypeScript + Vite** | 生态成熟、AI 辅助开发资料最全、构建快 |
| 游戏渲染 | **Phaser 3**（嵌入 React 页面） | 自带 Tilemap/精灵/动画/相机，2D 像素小镇开箱即用 |
| 美术表现 | **2D 像素风**：免费素材（Kenney / itch.io LPC 角色集）+ Tiled 编辑地图 | 与斯坦福小镇/Aivilization 同一视觉语言，无需原创美术，NPC 头顶气泡显示当前动作 |
| 后端 | **Python 3.12 + FastAPI** | AI 生态最强（SDK/提示工程/结构化输出），异步支持 tick 循环，Pydantic 天然做接口校验 |
| 实时通道 | REST（指令/查询）+ **SSE**（世界事件推送） | 单向推送足够，比 WebSocket 简单，Nginx 反代零配置 |
| AI 接入 | **OpenAI 兼容抽象层**：默认 DeepSeek-V4 系列，`.env` 可换任意兼容端点 | 一套代码适配多家；决策用结构化 JSON 输出，对话用流式 |
| 降级方案 | **规则引擎（效用驱动）**：无密钥/调用失败时自动切换 | 取当前最低需求值（饿/困/社交）决定行动；对话走人设模板库，保证可体验 |
| 数据库 | **SQLite + SQLModel** | 单文件即全部世界状态，保存/恢复 = 文件快照，零运维；MVP 规模远够 |
| 部署 | **Docker Compose**（backend + Caddy）部署到自有服务器 | Caddy 自动 HTTPS + 托管前端静态产物 + 反代 API/SSE，一条 `docker compose up -d` 上线 |
| 测试 | pytest（决策引擎、降级切换、API 冒烟）+ 前端 Vitest 可选 | 满足「至少一处自动化测试」并覆盖核心风险点 |

## 2. 系统架构

```
┌─ 浏览器 ──────────────────────────────┐
│ React 壳层（NPC 面板 / 对话窗 / 上帝操作）│
│ Phaser 3 场景（Tilemap + NPC 精灵）      │
└──────── REST ↓ ↑ SSE ────────────────┘
┌─ FastAPI ────────────────────────────┐
│ API 层: /world /npcs /chat /actions   │
│ 模拟层: Tick 调度器（如 30s/tick）      │
│ 认知层: NPC 决策器 ──→ AI Provider 抽象 │
│                        ├─ LLM 模式    │
│                        └─ Mock 规则引擎│
│ 持久层: SQLModel → SQLite（可快照恢复） │
└──────────────────────────────────────┘
```

- **Tick 循环**：世界每 tick 推进一次；每个 NPC 在自己的决策间隔到期时被唤醒，组装上下文（人设 + 当前状态 + 短期记忆 + 长期日记摘要 + 可用行动列表）→ 请求决策 → 校验 JSON → 执行（移动/工作/休息/找人聊天）→ 写入记忆 → SSE 广播。
- **玩家影响世界**：提供 2–3 个「上帝操作」（如切换天气、发布小镇公告、给 NPC 送物品），写入世界状态并进入 NPC 下一次决策上下文，形成可演示的因果链。

## 3. NPC 数据结构（核心设计）

```jsonc
{
  "id": "npc_ling",
  "profile": {                     // 静态人设（初始化数据写死）
    "name": "小玲", "role": "咖啡店店主",
    "personality": "ENFP，热情外向，爱打听八卦",
    "backstory": "……",
    "weights": { "social": 1.4, "work": 1.0, "rest": 0.7 }  // 降级规则引擎用
  },
  "state": {                       // 动态状态（每 tick 演化）
    "location": "cafe",
    "action": { "type": "chat", "target": "npc_bo", "reason": "…" },
    "needs": { "energy": 62, "hunger": 40, "social": 85 },
    "mood": "cheerful"
  },
  "memory": {
    "short_term": [ "…最近 20 条事件…" ],   // 环形缓冲
    "diary": [ "第1天：……" ]               // LLM 定期摘要，超长截断
  },
  "relationships": { "npc_bo": { "affinity": 30, "impression": "话少但可靠" } }
}
```

**决策接口（LLM 结构化输出）**：`{ "action": "move|work|rest|eat|chat|idle", "target": "...", "say": "...", "reason": "..." }` —— `reason` 字段既用于头顶气泡展示「自主决策」，也用于答辩时解释 AI 行为。

**初始 NPC 与地点**：见 `outline.md`（Inconnewt 世界观：劫后小镇,莫莫/小柯/阿羯/利利 四位 NPC,人设卡直接映射到 persona prompt 与降级规则引擎 weights;prompt 按「共享世界观 + 每角色私有人设 + 输出格式」三层拆分）。

## 4. 接口设计（REST + SSE）

| 接口 | 说明 |
|---|---|
| `GET /api/world` | 世界快照（时间、天气、地点、全部 NPC 状态） |
| `GET /api/npcs/{id}` | NPC 详情（人设/状态/记忆/关系） |
| `POST /api/chat/{id}` | 玩家与 NPC 对话（流式返回，写入 NPC 记忆） |
| `POST /api/world/actions` | 上帝操作（天气/公告/送物品） |
| `GET /api/events` (SSE) | 推送 NPC 行动、位置变化、世界事件 |
| `POST /api/world/save` · `/load` | 世界状态保存 / 恢复 |

## 5. 工程约束

- 密钥仅走 `.env`（提供 `.env.example`），`AI_PROVIDER=mock|openai_compatible` 一键切换；
- AI 调用统一超时 + 重试一次 + 失败自动落规则引擎，前端标注当前模式（真实 AI / Mock）；
- pytest 覆盖：决策 JSON 校验、mock 决策的确定性、保存/恢复往返一致性。

---

# 基础设计 Todo List

## M0 — 项目脚手架
- [ ] 初始化 monorepo：`frontend/`（Vite + React + TS + Phaser）、`backend/`（FastAPI + SQLModel）、`docker-compose.yml`
- [ ] `.env.example`（AI_PROVIDER、API_KEY、BASE_URL、MODEL、TICK_SECONDS）
- [ ] git 初始化 + `.gitignore`（密钥/数据库文件不入库）

## M1 — 世界模拟层（先跑 Mock）
- [ ] 定义数据模型：World / Location / NPC(profile, state, memory, relationships)
- [ ] 初始化数据：按 `outline.md` 落地——首批 2 地点（杂物铺「拾光」、温室食堂「芽」,广场可选）+ 首批 2 NPC（莫莫、利利,后续增补小柯、阿羯）
- [ ] Tick 调度器 + 效用规则引擎（无 AI 也能自主行动）
- [ ] SQLite 持久化 + save/load 接口

## M2 — AI 认知层
- [ ] AI Provider 抽象（openai_compatible / mock 双实现）
- [ ] 决策 prompt：人设 + 状态 + 记忆 → 结构化 JSON 行动；校验失败落规则引擎
- [ ] 对话 prompt：人设 + 关系 + 记忆 → 流式回复；对话写入短期记忆
- [ ] 记忆摘要任务（短期 → 日记）
- [ ] 超时/重试/降级链路 + 模式标识

## M3 — 前端小镇
- [ ] Tiled 制作小镇地图（免费像素素材），Phaser 加载 Tilemap + NPC 精灵与移动动画
- [ ] SSE 接入：NPC 行动/位置实时同步，头顶气泡显示当前动作与 reason
- [ ] NPC 详情面板（人设/需求条/记忆日志）——「数据模式」视图
- [ ] 对话窗口（流式渲染）+ 上帝操作栏（天气/公告/送物品）

## M4 — 工程收尾
- [ ] pytest：决策校验 / mock 确定性 / 保存恢复往返
- [ ] README + 技术方案文档（含关键决策与一处 AI 修改案例）
- [ ] Docker Compose + Caddy 部署到自有服务器，验证公网可访问
- [ ] 录制 3–5 分钟演示视频（小镇总览 → NPC 自主行动 → 对话 → 拔掉密钥演示降级）
