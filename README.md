<p align="center">
  <img src="logo.svg" width="120" alt="QwenGateway"/>
</p>

<h1 align="center">QwenGateway 🚀</h1>

<p align="center">
  <a href="https://github.com/jiujiu532/Qwen2api/actions/workflows/docker-publish.yml">
    <img src="https://github.com/jiujiu532/Qwen2api/actions/workflows/docker-publish.yml/badge.svg" alt="Build"/>
  </a>
  <img src="https://img.shields.io/badge/docker-ghcr.io%2Fjiujiu532%2Fqwengateway-blue" alt="Docker"/>
  <img src="https://img.shields.io/badge/Go-1.22+-00ADD8?logo=go" alt="Go"/>
</p>

<p align="center">中文 | <a href="#english">English</a></p>

---

高性能 Go 网关，将 Qwen AI 私有接口转换为标准 **OpenAI / Anthropic / Gemini** 兼容 API。支持多账号并行竞速、工具调用解析、Session 预热和精准错误监控，可直接对接 Cherry Studio、New-API 等客户端。

## 核心特性

| 特性 | 说明 |
|------|------|
| **并行竞速** | 同时向 N 个账号发请求，最快者胜出，其余立即取消 |
| **Session 预热** | 每账号预建 chat_id，消除每次请求的建立延迟 |
| **EMA 延迟排序** | 优先选历史最快账号（指数移动平均） |
| **熔断器** | 连续失败 3 次，跳过该账号 60 秒 |
| **TLS 指纹轮转** | 轮换 Chrome / Firefox 指纹，规避风控 |
| **工具调用解析** | 递归 XML DOM + Markup 双层解析，自动修复 LLM 非标 JSON |
| **自动续写** | `finish_reason: length` 时无缝续写，最多 5 轮 |
| **请求级监控** | `/health` 暴露真实成功率、race 失败数、空响应数 |
| **多协议支持** | OpenAI / Anthropic / Gemini / Responses API |

## 支持接口

| 协议 | 端点 |
|------|------|
| **OpenAI Chat** | `POST /v1/chat/completions` |
| **OpenAI Images** | `POST /v1/images/generations` |
| **OpenAI Models** | `GET /v1/models` |
| **Anthropic** | `POST /v1/messages` |
| **Gemini Generate** | `POST /v1beta/models/{model}:generateContent` |
| **Gemini Stream** | `POST /v1beta/models/{model}:streamGenerateContent` |
| **Responses API** | `POST /v1/responses` |
| **健康检查** | `GET /health` |

## 快速部署

```bash
docker pull ghcr.io/jiujiu532/qwengateway:latest

docker run -d \
  -p 8080:8080 \
  -e ACCOUNTS_FILE=/data/accounts.json \
  -e GATEWAY_API_KEY=your-secret-key \
  -v /path/to/accounts.json:/data/accounts.json \
  ghcr.io/jiujiu532/qwengateway:latest
```

## 账号文件格式

```json
[
  { "email": "user@example.com", "token": "eyJ...", "status_code": "VALID" }
]
```

## 健康检查

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

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `GATEWAY_ADDR` | `:8080` | 监听地址 |
| `ACCOUNTS_FILE` | — | JSON 账号文件路径（无需 Redis） |
| `REDIS_ADDR` | `localhost:6379` | Redis 地址（Redis 模式） |
| `REDIS_PASSWORD` | — | Redis 密码 |
| `GATEWAY_API_KEY` | — | 网关鉴权 Key（空 = 不鉴权） |

## 本地编译

```bash
# 需要 Go 1.22+
cd QwenGateway
go build -ldflags="-s -w" -o gateway ./cmd/
./gateway
```

---

## English

High-performance Go gateway exposing Qwen AI as a fully compatible OpenAI / Anthropic / Gemini API, with parallel racing, session pre-warming, tool call parsing, and real-time error monitoring.

### Features

| Feature | Description |
|---------|-------------|
| **Parallel Racing** | N simultaneous requests, fastest winner returned, rest cancelled |
| **Session Pre-warming** | Pre-creates chat sessions per account, eliminates setup latency |
| **EMA Latency Sorting** | Prioritizes fastest accounts with exponential moving average |
| **Circuit Breaker** | Skips failing accounts for 60 s after 3 consecutive failures |
| **TLS Fingerprint Rotation** | Chrome/Firefox fingerprint rotation to avoid bot detection |
| **Tool Call Parsing** | Recursive XML DOM + Markup parser with JSON auto-repair |
| **Auto-continuation** | Transparently stitches truncated streams |
| **Real-time Monitoring** | `/health` exposes race_failed, empty_response, error_rate_pct |

### Quick Start

```bash
docker pull ghcr.io/jiujiu532/qwengateway:latest

docker run -d \
  -p 8080:8080 \
  -e ACCOUNTS_FILE=/data/accounts.json \
  -e GATEWAY_API_KEY=your-secret-key \
  -v /path/to/accounts.json:/data/accounts.json \
  ghcr.io/jiujiu532/qwengateway:latest
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GATEWAY_ADDR` | `:8080` | Listen address |
| `ACCOUNTS_FILE` | — | JSON accounts file path (no Redis needed) |
| `REDIS_ADDR` | `localhost:6379` | Redis address |
| `REDIS_PASSWORD` | — | Redis password |
| `GATEWAY_API_KEY` | — | Bearer auth key (empty = no auth) |

---

## License

MIT
