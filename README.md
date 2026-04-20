<div align="center">

<img src="frontend/public/favicon.svg" width="120" alt="Qwen2API Logo" />

# Qwen2API

**将 Qwen Chat 逆向为 OpenAI 兼容 API · 账号池管理 · 可视化面板**

[![Docker](https://img.shields.io/badge/ghcr.io-jiujiu532%2Fqwen2api-blue?logo=docker)](https://github.com/jiujiu532/Qwen2api/pkgs/container/qwen2api)
[![License](https://img.shields.io/github/license/jiujiu532/Qwen2api)](LICENSE)

</div>

---

## 📖 项目简介

Qwen2API 将 [Qwen Chat](https://chat.qwen.ai) 的网页端会话接口逆向封装为标准的 **OpenAI API 格式**，让你可以直接使用 OpenAI SDK、Claude SDK 或任何兼容客户端调用 Qwen 模型。

**核心能力：**
- 🔌 **多协议兼容** — 同时支持 OpenAI (`/v1/chat/completions`)、Anthropic (`/v1/messages`)、Gemini (`/v1beta`) 和 OpenAI Responses API 格式
- 🏊 **账号池调度** — 多账号自动负载均衡，账号状态自动管理（VALID / RATE_LIMITED / BANNED），熔断保护
- 🤖 **批量注册** — 内置 4 种临时邮箱渠道（GuerrillaMail / TempMail / MoeMail / 手动），自动填表 + 邮箱验证
- 📊 **可视化面板** — 实时仪表盘、健康时间线、账号管理、密钥管理、API 调试 Playground
- 🛡️ **三引擎模式** — `httpx`（高速直连） / `browser`（Camoufox 反指纹浏览器） / `hybrid`（智能混合）
- 🐳 **一键部署** — Docker Compose 开箱即用，GitHub Actions 自动构建镜像

---

## 🚀 快速开始

### 方式一：Docker Compose（推荐）

```bash
# 1. 拉取镜像
docker pull ghcr.io/jiujiu532/qwen2api:latest

# 2. 创建配置
mkdir -p data
cat > .env << 'EOF'
ADMIN_KEY=your-admin-password
ENGINE_MODE=hybrid
EOF

# 3. 启动
docker compose up -d

# 4. 访问面板
# http://localhost:7860
```

`docker-compose.yml` 已包含在项目中，直接 clone 后启动即可：

```yaml
services:
  qwen2api:
    image: ghcr.io/jiujiu532/qwen2api:latest
    container_name: qwen2api
    restart: unless-stopped
    env_file:
      - path: .env
        required: false
    ports:
      - "7860:7860"
    volumes:
      - ./data:/workspace/data      # 账号/密钥等持久化数据
      - ./logs:/workspace/logs
    shm_size: '256m'                 # 浏览器引擎需要共享内存
    environment:
      PORT: "7860"
      ENGINE_MODE: "hybrid"
```

### 方式二：本地开发

**环境要求：** Python 3.10+ · Node.js 18+

```bash
# 克隆项目
git clone https://github.com/jiujiu532/Qwen2api.git
cd Qwen2api

# 一键启动（自动安装依赖 + 下载浏览器内核 + 启动前后端）
python start.py
```

启动后：
- **管理面板（前端）** → http://localhost:5174
- **API 网关（后端）** → http://localhost:7860

---

## 📡 API 使用

### OpenAI SDK（Python）

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:7860/v1",
    api_key="your-api-key"  # 在面板「密钥管理」中创建
)

# 普通对话
response = client.chat.completions.create(
    model="qwen-max",
    messages=[{"role": "user", "content": "你好，介绍一下自己"}]
)
print(response.choices[0].message.content)

# 流式对话
stream = client.chat.completions.create(
    model="qwen-plus",
    messages=[{"role": "user", "content": "写一首关于AI的诗"}],
    stream=True
)
for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
```

### 文生图

```python
response = client.images.generate(
    model="qwen-max",
    prompt="一只宇航员猫咪在月球上喝咖啡，赛博朋克风格",
    n=1,
    size="1024x1024"
)
print(response.data[0].url)
```

### cURL

```bash
# 对话
curl http://localhost:7860/v1/chat/completions \
  -H "Authorization: Bearer your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen-max",
    "messages": [{"role": "user", "content": "Hello!"}],
    "stream": false
  }'

# 查看可用模型
curl http://localhost:7860/v1/models \
  -H "Authorization: Bearer your-api-key"
```

### 支持的 API 接口

| 方法 | 路由 | 说明 |
|------|------|------|
| `POST` | `/v1/chat/completions` | OpenAI 兼容对话（支持流式） |
| `POST` | `/v1/images/generations` | 文生图（Qwen ArtLab） |
| `GET`  | `/v1/models` | 获取可用模型列表 |
| `POST` | `/v1/messages` | Anthropic Claude 兼容格式 |
| `POST` | `/v1beta/models/{model}:generateContent` | Google Gemini 兼容格式 |
| `POST` | `/v1/responses` | OpenAI Responses API 格式 |
| `POST` | `/v1/embeddings` | 文本嵌入（实验性） |

### 模型映射

发送请求时可以使用以下任意模型名，系统会自动映射到对应的 Qwen 模型：

| 模型别名 | 映射到 |
|----------|--------|
| `gpt-4o` / `gpt-4` / `gpt-4-turbo` / `gpt-4o-mini` / `gpt-4.1` | qwen3.6-plus |
| `claude-3-5-sonnet` / `claude-3-opus` / `claude-sonnet-4` | qwen3.6-plus |
| `gemini-2.0-flash` / `gemini-1.5-pro` | qwen3.6-plus |
| `deepseek-chat` / `deepseek-reasoner` | qwen3.6-plus |
| `qwen-max` / `qwen-plus` / `qwen-turbo` | qwen3.6-plus |

> 💡 所有请求最终都会调用 Qwen 的真实模型，模型映射只是为了兼容不同 SDK 的模型名格式。

---

## ⚙️ 配置说明

### 环境变量

复制 `.env.example` 为 `.env` 修改配置：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ADMIN_KEY` | `123456` | 管理面板登录密码 |
| `PORT` | `7860` | 服务端口 |
| `ENGINE_MODE` | `hybrid` | 引擎模式：`httpx` / `browser` / `hybrid` |
| `BROWSER_POOL_SIZE` | `2` | 浏览器实例池大小 |
| `MAX_INFLIGHT` | `1` | 每个账号同时最大请求数 |
| `MAX_RPM_PER_ACCOUNT` | `50` | 每个账号每分钟最大请求数 |
| `ACCOUNT_MIN_INTERVAL_MS` | `1200` | 同账号两次请求最小间隔（毫秒）|
| `MAX_RETRIES` | `2` | 请求失败最大重试次数 |
| `RATE_LIMIT_BASE_COOLDOWN` | `600` | 限流冷却时间（秒） |
| `RATE_LIMIT_MAX_COOLDOWN` | `3600` | 最大冷却时间（秒） |
| `CACHE_TTL_SECONDS` | `60` | 响应缓存 TTL |
| `RACING_ENABLED` | `false` | 竞速模式（多账号同时请求取最快） |

### 引擎模式

| 模式 | 说明 | 适用场景 |
|------|------|----------|
| `httpx` | 纯 HTTP 直连，速度最快 | 小规模、低风控环境 |
| `browser` | Camoufox 反指纹浏览器 | 高风控环境、需要绕过检测 |
| `hybrid` | 自动切换，优先 httpx，失败降级 browser | **推荐**，兼顾速度和稳定性 |

### 自动补号

当账号池中有效账号不足时，系统可以自动注册新账号：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `AUTO_REPLENISH` | `false` | 定期自动补号 |
| `REPLENISH_TARGET` | `30` | 目标账号数量 |
| `AUTO_REPLENISH_ON_EXHAUST` | `true` | 所有账号限流时紧急补号 |
| `REPLENISH_EXHAUST_COUNT` | `10` | 紧急补号数量 |

### 代理配置

在管理面板「系统设置 → 代理」中配置，或通过环境变量：

```env
PROXY_ENABLED=true
PROXY_URL=http://host:port          # 支持 http / socks5
PROXY_USERNAME=user                 # 可选
PROXY_PASSWORD=pass                 # 可选
```

### 临时邮箱配置（批量注册用）

| 变量 | 说明 |
|------|------|
| `MOEMAIL_DOMAIN` | MoeMail 自建邮箱域名 |
| `MOEMAIL_KEY` | MoeMail 管理密钥 |
| `TEMPMAIL_DOMAIN` | TempMail (CF Workers) 域名 |
| `TEMPMAIL_KEY` | TempMail 管理密钥 |

---

## 🏗️ 项目结构

```
Qwen2api/
├── backend/                    # FastAPI 后端服务
│   ├── api/                   # API 路由层
│   │   ├── chat.py            #   OpenAI /v1/chat/completions
│   │   ├── images.py          #   文生图 /v1/images/generations
│   │   ├── anthropic.py       #   Claude 兼容
│   │   ├── gemini.py          #   Gemini 兼容
│   │   ├── responses.py       #   OpenAI Responses API
│   │   ├── admin.py           #   管理面板 API
│   │   └── probes.py          #   健康探针 /healthz
│   ├── core/                  # 核心引擎层
│   │   ├── account_pool.py    #   账号池（调度/熔断/轮转）
│   │   ├── config.py          #   全局配置
│   │   ├── httpx_engine.py    #   HTTP 直连引擎
│   │   ├── browser_engine.py  #   Camoufox 浏览器引擎
│   │   ├── hybrid_engine.py   #   混合引擎（自动切换）
│   │   ├── health_snapshot.py #   30s 健康快照
│   │   └── database.py        #   异步 JSON 文件存储
│   ├── services/              # 业务服务层
│   │   ├── qwen_client.py     #   Qwen 会话客户端
│   │   ├── register.py        #   注册调度器
│   │   ├── browser_register.py#   浏览器自动注册
│   │   ├── mail_service.py    #   临时邮箱服务
│   │   ├── prompt_builder.py  #   提示词构建
│   │   └── garbage_collector.py#  会话回收
│   └── main.py                # 应用入口 + 生命周期
├── frontend/                   # React + TypeScript + Vite
│   └── src/
│       ├── pages/             # 页面组件
│       │   ├── Dashboard.tsx  #   仪表盘（健康时间线 + 统计）
│       │   ├── AccountsPage.tsx#  账号管理（验证/删除/批量操作）
│       │   ├── RegisterPage.tsx#  批量注册
│       │   ├── TokensPage.tsx #   API 密钥管理
│       │   ├── PlaygroundPage.tsx# API 调试
│       │   ├── ImagePage.tsx  #   文生图
│       │   └── SettingsPage.tsx#  系统设置
│       ├── layouts/           # 布局（侧边栏 + 主题切换）
│       └── components/        # 公共组件
├── tools/                      # 独立工具脚本
│   ├── standalone_register/   #   独立 CLI 注册工具
│   └── register_cli.py       #   批量注册命令行入口
├── data/                       # 运行时数据（自动创建，已 gitignore）
├── start.py                   # 一键启动脚本（自动装依赖）
├── Dockerfile                 # 多阶段构建镜像
└── docker-compose.yml         # Docker Compose 配置
```

---

## 🐳 Docker 镜像

```bash
# 拉取最新镜像
docker pull ghcr.io/jiujiu532/qwen2api:latest

# 运行
docker run -d \
  --name qwen2api \
  -p 7860:7860 \
  -v ./data:/workspace/data \
  -e ADMIN_KEY=your-password \
  -e ENGINE_MODE=hybrid \
  --shm-size=256m \
  ghcr.io/jiujiu532/qwen2api:latest
```

镜像在每次推送到 `main` 分支时自动通过 GitHub Actions 构建并发布到 GHCR。

---

## 📝 License

MIT © 2026 jiujiu532
