# QwenGateway 🚀

**English** | [中文](#中文)

High-performance Go gateway that exposes Qwen AI as a fully compatible OpenAI / Anthropic (Claude) / Gemini API — with parallel racing, session pre-warming, tool call parsing, and real-time error monitoring.

[![Build](https://github.com/jiujiu532/Qwen2api/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/jiujiu532/Qwen2api/actions)
[![Docker](https://img.shields.io/badge/docker-ghcr.io%2Fjiujiu532%2Fqwengateway-blue)](https://ghcr.io/jiujiu532/qwengateway)
[![Go](https://img.shields.io/badge/Go-1.22+-00ADD8?logo=go)](https://go.dev)

---

## Features

| Feature | Description |
|---------|-------------|
| **Parallel Racing** | Fires N simultaneous requests, returns the fastest winner, cancels the rest |
| **Session Pre-warming** | Pre-creates chat sessions per account, eliminating per-request setup latency |
| **EMA Latency Sorting** | Prioritizes historically fastest accounts with exponential moving average |
| **Circuit Breaker** | Auto-skips failing accounts for 60 s after 3 consecutive failures |
| **TLS Fingerprint Rotation** | Rotates Chrome/Firefox TLS fingerprints to avoid bot detection |
| **Tool Call Parsing** | Recursive XML DOM + Markup parser with JSON auto-repair |
| **Auto-continuation** | Transparently stitches truncated streams (`finish_reason: length`) |
| **Real-time Error Monitoring** | `/health` exposes `race_failed`, `empty_response`, `error_rate_pct` |
| **Multi-protocol** | OpenAI, Anthropic, Gemini, Responses API — one service |

## Supported Endpoints

| Protocol | Endpoint |
|----------|----------|
| **OpenAI Chat** | `POST /v1/chat/completions` |
| **OpenAI Images** | `POST /v1/images/generations` |
| **OpenAI Models** | `GET /v1/models` |
| **Anthropic** | `POST /v1/messages` (streaming + non-streaming) |
| **Gemini Generate** | `POST /v1beta/models/{model}:generateContent` |
| **Gemini Stream** | `POST /v1beta/models/{model}:streamGenerateContent` |
| **Responses API** | `POST /v1/responses` |
| **Health** | `GET /health` |

## Quick Start

```bash
# Pull the latest image
docker pull ghcr.io/jiujiu532/qwengateway:latest

# Run with an accounts JSON file
docker run -d \
  -p 8080:8080 \
  -e ACCOUNTS_FILE=/data/accounts.json \
  -e GATEWAY_API_KEY=your-secret-key \
  -v /path/to/accounts.json:/data/accounts.json \
  ghcr.io/jiujiu532/qwengateway:latest
```

## Accounts File Format

```json
[
  { "email": "user@example.com", "token": "eyJ...", "status_code": "VALID" }
]
```

## Health Endpoint

```bash
curl http://localhost:8080/health
```
```json
{
  "status": "ok",
  "accounts": 118,
  "requests_total": 2100,
  "success": 2058,
  "race_failed": 12,
  "empty_response": 30,
  "error_rate_pct": "2.0%"
}
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GATEWAY_ADDR` | `:8080` | Listen address |
| `ACCOUNTS_FILE` | — | Path to JSON accounts file (file mode, no Redis) |
| `REDIS_ADDR` | `localhost:6379` | Redis address (Redis mode) |
| `REDIS_PASSWORD` | — | Redis password |
| `GATEWAY_API_KEY` | — | Bearer key for auth (empty = no auth) |

## Build from Source

```bash
# Requires Go 1.22+
cd QwenGateway
go build -ldflags="-s -w" -o gateway ./cmd/
./gateway
```

---

## 中文

高性能 Go 网关，将 Qwen AI 私有接口转换为标准 OpenAI / Anthropic / Gemini 兼容 API，支持多账号并行竞速、工具调用解析、Session 预热和精准错误监控。

### 核心特性

| 特性 | 说明 |
|------|------|
| **并行竞速** | 同时向 N 个账号发请求，最快者胜出，其余取消 |
| **Session 预热** | 每账号预建 chat_id，消除每次请求的建立延迟 |
| **EMA 延迟排序** | 优先选历史最快账号 |
| **熔断器** | 连续失败 3 次，跳过该账号 60 秒 |
| **TLS 指纹轮转** | 轮换 Chrome / Firefox 指纹，规避风控 |
| **工具调用解析** | 递归 XML DOM + Markup 双层解析，自动修复 LLM 非标 JSON |
| **自动续写** | `finish_reason: length` 时无缝续写，最多 5 轮 |
| **请求级监控** | `/health` 暴露 `race_failed`、`empty_response`、`error_rate_pct` |
| **多协议支持** | OpenAI / Anthropic / Gemini / Responses API |

### 快速部署

```bash
docker pull ghcr.io/jiujiu532/qwengateway:latest

docker run -d \
  -p 8080:8080 \
  -e ACCOUNTS_FILE=/data/accounts.json \
  -e GATEWAY_API_KEY=your-secret-key \
  -v /path/to/accounts.json:/data/accounts.json \
  ghcr.io/jiujiu532/qwengateway:latest
```

### 账号文件格式

```json
[
  { "email": "user@example.com", "token": "eyJ...", "status_code": "VALID" }
]
```

### 项目结构

```
QwenGateway/
├── cmd/main.go                 # 入口：路由、计数器、账号池
├── internal/
│   ├── pool/                   # 账号池 + EMA 排序 + 熔断器 + 预热 + 探针
│   ├── racing/race.go          # 并行竞速引擎（带 SSE 多行 peek 验证）
│   ├── proxy/                  # SSE 透传 + 自动续写 + 图片生成
│   ├── toolcall/               # 工具调用三层解析 + JSON 修复
│   └── proto/                  # OpenAI / Anthropic / Gemini 协议适配
└── Dockerfile                  # 两阶段构建 → Alpine 镜像
```

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `GATEWAY_ADDR` | `:8080` | 监听地址 |
| `ACCOUNTS_FILE` | — | JSON 账号文件路径（无需 Redis） |
| `REDIS_ADDR` | `localhost:6379` | Redis 地址（Redis 模式） |
| `REDIS_PASSWORD` | — | Redis 密码 |
| `GATEWAY_API_KEY` | — | 网关鉴权 Key（空 = 不鉴权） |

---

## License

MIT
