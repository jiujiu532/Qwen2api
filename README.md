<p align="center">
  <img src="logo.svg" width="120" alt="qwen2api"/>
</p>

<h1 align="center">qwen2api</h1>

<p align="center">
  <a href="https://github.com/jiujiu532/Qwen2api/actions/workflows/docker-publish.yml">
    <img src="https://github.com/jiujiu532/Qwen2api/actions/workflows/docker-publish.yml/badge.svg" alt="Build"/>
  </a>
  <img src="https://img.shields.io/badge/python-3.12+-blue?logo=python" alt="Python"/>
  <img src="https://img.shields.io/badge/docker-ghcr.io%2Fjiujiu532%2Fqwen2api-blue?logo=docker" alt="Docker"/>
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License"/>
</p>

<p align="center">
  Qwen AI 逆向网关 -- 标准 OpenAI / Anthropic / Gemini API 兼容
</p>

<p align="center">中文 | <a href="README.en.md">English</a></p>

---

## 概述

qwen2api 将阿里通义千问（Qwen）网页版的能力以标准 API 格式对外暴露。多账号池轮询、自动注册补号、工具调用、流式输出，可直接对接 Cherry Studio、Cursor、Claude Code、Cline、New-API 等客户端。

## 核心特性

- **多协议兼容** -- OpenAI Chat Completions / Responses API / Anthropic Messages / Gemini generateContent 四协议同时支持
- **账号池调度** -- Min-Heap 优先级调度，6 态生命周期管理（valid/rate_limited/auth_error/banned/activation_pending/cooldown），断路器自动熔断
- **自动注册补号** -- 支持 MoeMail / TempMail / GuerrillaMail 渠道，账号耗尽时自动触发应急注册
- **工具调用** -- Native FC 优先 + XML Fallback 双模式，流式防泄漏状态机，重复调用循环检测
- **思考模式** -- 模型名后缀控制（-thinking / -nothinking），或请求参数 reasoning_effort 覆盖
- **图片生成** -- 兼容 OpenAI DALL-E 接口，自动检测用户意图路由到 T2I
- **管理面板** -- 内置 React Web UI，实时 SSE 事件流，账号/密钥/设置/统计一站式管理
- **多引擎** -- httpx 直连（快）/ Camoufox 浏览器指纹（防封）/ hybrid 混合模式
- **容灾重试** -- 上游失败自动换号重试，NativeBlock 检测自动切 XML 模式

## 支持的端点

| 协议 | 端点 | 功能 |
|------|------|------|
| OpenAI | `POST /v1/chat/completions` | 聊天补全（流式/非流式/工具调用/思考模式） |
| OpenAI | `POST /v1/responses` | Responses API（Codex / Agents 使用） |
| OpenAI | `POST /v1/images/generations` | 图片生成 |
| OpenAI | `POST /v1/embeddings` | 文本嵌入 |
| OpenAI | `GET /v1/models` | 模型列表 |
| Anthropic | `POST /v1/messages` | Claude 兼容（含 tool_use / thinking） |
| Gemini | `POST /v1beta/models/{m}:generateContent` | Gemini 兼容 |
| Gemini | `POST /v1beta/models/{m}:streamGenerateContent` | Gemini 流式 |

## 可用模型

### Qwen 原生模型

| 模型名 | 说明 |
|--------|------|
| `qwen3.6-plus` | 主力模型，自动思考 |
| `qwen3.6-plus-thinking` | 强制深度思考 |
| `qwen3.6-plus-nothinking` | 快速模式 |
| `qwen3.6-max-preview` | 高性能预览版 |
| `qwen3.6-27b` | 轻量版 |
| `qwen3.7-max-preview` | 3.7 系列（仅思考模式） |
| `qwen3.7-plus-preview` | 3.7 Plus 预览 |

每个模型均支持 `-thinking` / `-nothinking` 后缀切换思考模式。

### 内置别名映射

无需配置，直接使用常见模型名：

```
gpt-4o / gpt-4o-mini / gpt-4.1 / gpt-3.5-turbo
o1 / o3 / o3-mini / o4-mini
claude-3-5-sonnet-latest / claude-sonnet-4-20250514 / claude-3-opus-latest
gemini-2.5-pro / gemini-2.5-flash / gemini-2.0-flash
deepseek-chat / deepseek-reasoner
```

管理面板可自定义追加映射。

## 快速开始

### Docker（推荐）

```bash
docker run -d \
  --name qwen2api \
  -p 7860:7860 \
  -e ADMIN_KEY=your-admin-key \
  -v ./data:/workspace/data \
  ghcr.io/jiujiu532/qwen2api:latest
```

docker-compose:

```bash
cp .env.example .env
# 编辑 .env 设置 ADMIN_KEY 和邮箱渠道
docker-compose up -d
```

### 本地运行

```bash
# Python 3.12+
pip install -r backend/requirements.txt
python start.py
```

启动后访问 `http://localhost:7860`，默认管理密钥 `123456`。

## 配置

通过 `.env` 或环境变量：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ADMIN_KEY` | `123456` | 管理面板密钥 |
| `PORT` | `7860` | 服务端口 |
| `ENGINE_MODE` | `hybrid` | httpx / browser / hybrid |
| `AUTO_REPLENISH` | `false` | 自动补号开关 |
| `REPLENISH_TARGET` | `30` | 目标账号数 |
| `MOEMAIL_DOMAIN` | - | MoeMail 域名 |
| `MOEMAIL_KEY` | - | MoeMail 密钥 |
| `TEMPMAIL_DOMAIN` | - | TempMail 域名 |
| `TEMPMAIL_KEY` | - | TempMail 密钥 |
| `PROXY_URL` | - | 注册代理地址 |
| `NATIVE_TOOL_PASSTHROUGH` | `true` | 优先使用 Qwen 原生 FC |
| `MAX_INFLIGHT_PER_ACCOUNT` | `1` | 单账号最大并发 |

完整配置见 [.env.example](.env.example)。

## 使用示例

### OpenAI 格式

```bash
curl http://localhost:7860/v1/chat/completions \
  -H "Authorization: Bearer your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3.6-plus",
    "messages": [{"role": "user", "content": "Hello"}],
    "stream": true
  }'
```

### Anthropic 格式

```bash
curl http://localhost:7860/v1/messages \
  -H "x-api-key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-3-5-sonnet-latest",
    "messages": [{"role": "user", "content": "Hello"}],
    "max_tokens": 4096
  }'
```

### 工具调用

```bash
curl http://localhost:7860/v1/chat/completions \
  -H "Authorization: Bearer your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3.6-plus-nothinking",
    "messages": [{"role": "user", "content": "北京今天天气怎么样"}],
    "tools": [{"type": "function", "function": {"name": "get_weather", "parameters": {"type": "object", "properties": {"city": {"type": "string"}}}}}],
    "stream": true
  }'
```

## 项目结构

```
qwen2api/
├── backend/
│   ├── api/              # 路由层（薄，参数解析 + 响应格式化）
│   │   ├── chat.py           # OpenAI Chat Completions
│   │   ├── anthropic.py      # Anthropic Messages
│   │   ├── gemini.py         # Gemini generateContent
│   │   ├── responses.py      # OpenAI Responses API
│   │   ├── images.py         # 图片生成
│   │   └── admin/            # 管理后台（accounts/keys/settings/stats）
│   ├── engine/           # 核心引擎（业务逻辑）
│   │   └── completion.py     # 统一 Completion 执行器
│   ├── core/             # 基础设施
│   │   ├── account_pool.py   # 账号池调度
│   │   ├── config.py         # 配置管理
│   │   ├── auth.py           # API 鉴权
│   │   └── hybrid_engine.py  # HTTP 引擎
│   └── services/         # 业务服务
│       ├── qwen_client.py    # Qwen 上游客户端
│       ├── tool_parser.py    # 工具调用解析
│       ├── prompt_builder.py # Prompt 构建
│       └── register.py       # 自动注册
├── frontend/             # React 管理面板
├── data/                 # 运行时数据
├── Dockerfile
├── docker-compose.yml
└── start.py
```

## 管理面板

| 页面 | 功能 |
|------|------|
| 监控总览 | 请求量、Token 消耗、RPM/TPM 曲线、健康度 |
| 账号管理 | 添加/删除/验证/激活，批量导入，JSON 编辑 |
| 扩容中心 | 批量注册，多邮箱渠道，并发控制 |
| 系统设置 | 模型映射、引擎模式、代理、自动补号 |
| API 密钥 | 生成/删除下游 Key |

## 客户端对接

| 客户端 | 配置方式 |
|--------|----------|
| Cherry Studio | API Base: `http://host:7860/v1`，模型选 `qwen3.6-plus` |
| Cursor | Settings > Models > OpenAI API Base |
| Claude Code | `ANTHROPIC_BASE_URL=http://host:7860` |
| Cline | OpenAI Compatible，填入 Base URL |
| New-API | 添加渠道，类型 OpenAI，代理地址填本服务 |

## License

MIT
