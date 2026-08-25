# Inconnewt · 新螈镇 AI 小镇 Demo

一个可运行、可观察、可干预的 Web 版 AI 小镇。v2 把原来的观察仪表盘升级成真正的一屏游戏舞台：四位居民会按日程和需求行动、在地点间走动、偶遇交谈并留下记忆；玩家可以打开档案、进入 AVG 式对话，或轻轻改变天气与小镇事件。

> 当前版本：`v0.2.0`。默认使用 Mock，不填写 API Key 也能完整体验场景、计划、互动、记忆和流式对话。

## v2 能体验什么

- Phaser 3 全屏小镇：5 个地点、道路锚点、4 位可点击且会移动的居民；
- 昼夜压色、雾效、夜间篝火光晕、公告板反馈和 SSE 事件横幅；
- 四角 HUD、上帝操作快捷栏，以及保留完整状态的“数据模式”；
- 角色档案：统一原创立绘、代号、标签、需求、日程、记忆和关系分页；
- AVG 对话：场景压暗、角色立绘、SSE 文本流和逐字演出；
- 每日计划 → tick 决策 → 行动记忆 → 日记摘要 → 次日计划的轻量闭环；
- 反重复决策、数据驱动的地点活动、`visit` 串门和同地点 NPC 自主互动；
- SQLite 存档、AI/Mock 自动降级，以及 v1 的保存、恢复和世界干预能力。

## 最快启动：Docker

要求：Docker Desktop / Docker Engine + Compose。

```bash
docker compose up --build
```

打开 <http://localhost:8080>。如果 `8080` 已占用，在 `.env` 设置 `WEB_PORT=18089` 后重新启动。

```bash
docker compose down
```

世界状态保存在 Docker volume `inconewt-data`；普通 `docker compose down` 不会删除存档。v1 数据会在首次加载时自动补齐 v2 地点、居民与日程。

## 本地开发

要求：Node.js 22+、Python 3.12+。

```bash
cp .env.example .env
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cd backend
uvicorn app.main:app --reload
```

另开终端：

```bash
cd frontend
npm install
npm run dev
```

打开 <http://localhost:5173>；Vite 会把 `/api` 代理到 `localhost:8000`。

## 填写 DeepSeek API Key

建议先用 Mock 跑通 Demo，再在项目根目录的 `.env` 填写真实配置：

```dotenv
AI_PROVIDER=deepseek
DEEPSEEK_API_KEY=你的_API_Key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
```

重启后端或执行 `docker compose up -d --build`。页面右上角显示 `DEEPSEEK V4` 即表示后端已识别配置。模型或端点变化时，只改 `.env`，不要改源码。

安全底线：

- `.env`、数据库和构建产物均被 `.gitignore` 排除；
- Key 只由 Python 后端读取，健康检查、世界响应和浏览器代码都不会返回 Key；
- 浏览器只访问本项目 `/api`，不会直连模型服务；
- 鉴权、网络、超时或结构化输出校验失败时自动回落到 Mock；
- `.env.example` 只保留空占位符，可安全提交。

## 自主决策链路

```text
每日计划（人设 + 昨日日记）
  → tick 更新需求与世界时间
  → 计划 + 最近行动 + 天气 + 公告进入决策上下文
  → DeepSeek 结构化决策 / Mock 效用决策
  → Pydantic 校验与重复动作复判
  → 执行动作、移动、更新需求和完成日程
  → 同地点互动、关系变化、叙事事件
  → 去重短期记忆、摘要日记、SQLite 与 SSE
```

Mock 并非固定脚本循环：低需求会触发休息或进食，未完成计划会提高对应行动权重，每位居民还有数据定义的特有活动；最近行动会参与惩罚，10 tick 验收会覆盖多种行为和居民互动。

三层提示词位于 `backend/prompts/`：

```text
backend/prompts/
├── world.md
├── format.md
└── npc/
    ├── momo.md
    ├── lili.md
    ├── xiaoke.md
    └── ajie.md
```

要现场修改角色口吻，只需调整对应 NPC prompt；业务动作仍必须通过后端模型校验，AI 不能绕过允许的动作与地点范围。

## 项目结构

```text
inconewt/
├── frontend/
│   ├── public/assets/       # 四位原创透明背景居民立绘
│   └── src/
│       ├── App.tsx          # HUD、事件、干预和模式编排
│       ├── TownStage.tsx    # Phaser 场景、移动与环境演出
│       ├── ArchivePanel.tsx # 角色档案
│       ├── DataMode.tsx     # 数据模式
│       ├── DialogueOverlay.tsx # AVG 对话演出
│       ├── api.ts           # REST / SSE 类型与封装
│       └── styles.css       # 纸质档案 × 橄榄绿视觉系统
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI、自动 tick 与流式接口
│   │   ├── models.py        # v2 世界、日程、活动、记忆模型
│   │   ├── world.py         # 模拟、互动、叙事与迁移
│   │   ├── ai.py            # DeepSeek / Mock 计划、决策、对话、摘要
│   │   └── store.py         # SQLite 快照与存档
│   ├── prompts/
│   └── tests/               # 8 项核心后端测试
├── docker-compose.yml
├── .env.example
├── goal.md
└── outline.md
```

功能按关联性集中到可 review 的模块中，没有为单个小函数拆文件；关键世界规则附有中文注释，界面命名与类型保持直接可读。

## API 一览

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/health` | 服务状态与 AI 模式，不暴露 Key |
| GET | `/api/world` | 当前世界快照、日程、事件与关系 |
| GET | `/api/npcs/{id}` | NPC 详情 |
| POST | `/api/world/tick` | 手动推进一刻 |
| POST | `/api/chat/{id}` | 普通 NPC 对话 |
| POST | `/api/chat/{id}/stream` | AVG 使用的 SSE 流式对话 |
| POST | `/api/world/actions` | 天气、公告、礼物干预 |
| POST | `/api/world/save` | 建立手动存档 |
| POST | `/api/world/load` | 恢复最近手动存档 |
| GET | `/api/events` | SSE 世界事件 |

FastAPI 交互文档：启动后打开 <http://localhost:8000/docs>。

## 最小验证

项目避免过度测试，只覆盖决定 Demo 能否成立的核心路径：

```bash
cd backend
../.venv/bin/pytest

cd ../frontend
npm run build
```

后端 8 项测试覆盖需求驱动、tick、存档往返、10 tick 行为多样性与互动、每日计划 Mock、反重复签名、记忆去重和非法 AI 决策拒绝。

## 关键取舍

- 场景先用 Phaser 内的手绘矢量底图和路径点，避免 v2 被 Tilemap 素材管线卡住；API 坐标已经数据化，之后可替换成 Tiled/A*。
- 立绘为本项目生成的原创角色资产，仅参考现有纸张与橄榄色气氛，不复刻具体游戏 UI 或角色。
- SQLite 继续保存整份 Pydantic 世界快照，v2 在读取时迁移旧快照；MVP 更容易部署、检查和回滚。
- 对话后端先生成完整回复，再按统一 SSE 协议逐字输出；Mock 和 DeepSeek 因而拥有相同的 AVG 演出与失败处理。
- AI 是可替换的认知层而不是运行前提：计划、决策、互动、摘要和对话均有 Mock 路径。

## 部署说明

仓库使用单一 `docker compose up --build -d` 部署；生产环境只需在服务器侧保管 `.env`。当前 homelab/Tailscale 体验地址为 <http://homelab-moyuin:18089>，访问者需要处于同一 Tailnet。公网发布时应在外层 Caddy/Nginx 配置域名、HTTPS 和访问策略。
