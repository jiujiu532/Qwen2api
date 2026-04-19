<div align="center">

# Qwen2API

**Qwen Chat 账号池代理网关 · OpenAI 兼容接口**

[![Docker](https://img.shields.io/docker/v/jiujiu532/qwen2api?label=Docker&logo=docker)](https://hub.docker.com/r/jiujiu532/qwen2api)
[![License](https://img.shields.io/github/license/jiujiu532/Qwen2api)](LICENSE)

[快速开始](#-快速开始) · [功能特性](#-功能特性) · [API 文档](#-api-文档) · [配置说明](#-配置说明) · [开发指南](#-开发)

</div>

---

## 简介

Qwen2API 是一个针对 [Qwen Chat](https://chat.qwen.ai) 的逆向代理网关，将 Qwen 的网页会话接口封装为 **OpenAI 兼容的 REST API**，同时提供：

- **账号池管理**：批量维护多个 Qwen 账号，自动轮换、健康检测、状态监控
- **账号自动注册**：支持 GuerrillaMail / TempMail / MoeMail 等多种临时邮箱渠道批量注册
- **可视化管理面板**：实时仪表盘、账号列表、使用统计、Token 管理
- **企业级部署**：Docker 一键部署，支持多线程并发

---

## ✨ 功能特性

| 功能 | 描述 |
|------|------|
| 🔌 OpenAI 兼容 | 完整支持 `/v1/chat/completions`、`/v1/images/generations`、`/v1/models` 等接口 |
| 🏊 账号池 | 多账号自动负载均衡，VALID / RATE_LIMITED / BANNED 状态自动管理 |
| 📊 实时监控 | 30 秒间隔健康快照，30 分钟历史时间线，Sparkline 趋势图 |
| 🤖 批量注册 | 支持 4 种邮箱渠道，多线程并发，自动填写表单+处理验证码 |
| 🔑 Token 管理 | 自定义 API Key、用量限额、到期时间 |
| 🌙 主题切换 | 深色 / 浅色模式，自适应 CSS 变量主题 |
| 🐳 Docker | 完整 Dockerfile + Docker Compose + GitHub Actions 自动构建 |

---

## 🚀 快速开始

### Docker Compose（推荐）

```yaml
# docker-compose.yml
services:
  qwen2api:
    image: jiujiu532/qwen2api:latest
    ports:
      - "7860:7860"
    volumes:
      - ./data:/app/data
    environment:
      - ADMIN_KEY=your-admin-key-here
      - SECRET_KEY=your-secret-key-here
    restart: unless-stopped
```

```bash
docker compose up -d
```

访问 `http://localhost:7860` 即可打开管理面板。

### 本地开发

**环境要求：** Python 3.11+、Node.js 18+

```bash
# 克隆项目
git clone https://github.com/jiujiu532/Qwen2api.git
cd Qwen2api

# 安装依赖并启动（自动启动前后端）
pip install uv
uv sync
python start.py
```

---

## 📡 API 文档

所有接口兼容 OpenAI SDK，只需替换 `base_url` 和 `api_key`：

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:7860/v1",
    api_key="your-token-here"
)

response = client.chat.completions.create(
    model="qwen-max",
    messages=[{"role": "user", "content": "Hello!"}]
)
print(response.choices[0].message.content)
```

### 支持的接口

| 方法 | 路由 | 说明 |
|------|------|------|
| `POST` | `/v1/chat/completions` | 聊天对话（支持流式/非流式） |
| `POST` | `/v1/images/generations` | 文生图（Qwen ArtLab） |
| `GET` | `/v1/models` | 获取可用模型列表 |
| `POST` | `/v1/embeddings` | 文本嵌入（实验性） |

### 支持的模型

| 模型标识 | 说明 |
|----------|------|
| `qwen-max` | Qwen Max（默认） |
| `qwen-plus` | Qwen Plus |
| `qwen-turbo` | Qwen Turbo（快速） |
| `qwen-long` | Qwen Long（长文本） |
| `qwq-32b` | QwQ 推理模型 |

---

## ⚙️ 配置说明

复制 `.env.example` 为 `.env` 并填写：

```env
# 管理员密钥（登录管理面板使用）
ADMIN_KEY=your-admin-key

# JWT 签名密钥（用于用户 Token 生成）
SECRET_KEY=your-secret-key

# 服务端口（默认 7860）
PORT=7860

# 日志级别
LOG_LEVEL=INFO
```

### 代理池

在管理面板「系统设置 → 代理池」中配置 HTTP/SOCKS5 代理列表，格式：

```
http://user:pass@host:port
socks5://host:port
```

---

## 🏗️ 项目结构

```
Qwen2api/
├── backend/                # FastAPI 后端
│   ├── api/               # API 路由（admin, v1_chat, images, …）
│   ├── core/              # 核心模块（账号池、引擎、健康快照、缓存）
│   ├── services/          # 业务服务（注册、邮件、GC、提示词构建）
│   └── main.py            # 应用入口、生命周期管理
├── frontend/               # React + Vite 前端
│   └── src/
│       ├── pages/         # 页面（Dashboard, Accounts, Tokens, …）
│       ├── components/    # 公共组件
│       └── layouts/       # 布局框架
├── register/               # 独立账号注册工具（CLI）
├── data/                   # 运行时数据（gitignored）
│   ├── accounts.json      # 账号池存储
│   ├── api_keys.json      # API Token 列表
│   └── ...
├── start.py               # 一键启动脚本
├── Dockerfile
└── docker-compose.yml
```

---

## 🐳 Docker 镜像

```bash
docker pull jiujiu532/qwen2api:latest
```

镜像每次推送到 `main` 分支时自动通过 GitHub Actions 构建并发布到 Docker Hub。

---

## 📝 License

MIT © 2026 jiujiu532
