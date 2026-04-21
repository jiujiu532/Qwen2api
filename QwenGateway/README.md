# QwenGateway 🚀

高性能 Go 网关，将 Qwen AI 的私有 API 转换为标准 OpenAI / Anthropic / Gemini 兼容接口。支持多账号并行竞速、工具调用、Session 预热，可直接对接 Cherry Studio、New-API 等客户端。

[![Build](https://github.com/jiujiu532/Qwen2api/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/jiujiu532/Qwen2api/actions)
[![Docker](https://img.shields.io/badge/docker-ghcr.io%2Fjiujiu532%2Fqwengateway-blue)](https://ghcr.io/jiujiu532/qwengateway)

---

## 架构

```
Client (Cherry Studio / New-API / …)
    │
    ▼  Authorization: Bearer <API_KEY>
QwenGateway (:8080)
    ├── /v1/chat/completions      ← OpenAI
    ├── /v1/messages              ← Anthropic / Claude
    ├── /v1beta/models/*/…        ← Gemini
    ├── /v1/images/generations    ← DALL·E 兼容
    └── /health                   ← 监控端点
         │
         ▼  并行竞速 (Race N accounts)
    Qwen AI 上游
```

账号池支持两种模式：
- **文件模式**（无需 Redis）：`ACCOUNTS_FILE=accounts.json`
- **Redis 模式**：配合 Python 注册后端实时同步

---

## 核心特性

| 特性 | 说明 |
|------|------|
| **并行竞速** | 同时向 N 个账号发请求，最快者响应，其余取消 |
| **Session 预热** | 每个账号预建 2 个 chat_id，消除每请求的建立延迟 |
| **EMA 延迟排序** | 优先选历史最快账号（平滑延迟追踪） |
| **熔断器** | 连续失败 3 次后跳过该账号 60 秒 |
| **健康探针** | 每分钟探活，失效账号立刻踢出 |
| **TLS 指纹轮转** | Chrome / Firefox 指纹轮换，规避风控 |
| **工具调用解析** | 递归 XML DOM + Markup 双层解析，JSON 自动修复 |
| **自动续写** | `finish_reason: length` 时自动续写，最多 5 轮 |
| **请求级监控** | `/health` 暴露真实成功率、空响应数、race 失败数 |
| **多协议适配** | OpenAI / Anthropic / Gemini / Responses API |

---

## 工具调用

支持 Qwen 输出的多种工具调用格式，并自动修复 LLM 常见输出问题：

- `<tool_calls>`, `<function_calls>`, `<invoke>` 嵌套 XML
- 命名空间标签（`<ns:invoke>`）、CDATA 内容
- JSON 参数中的非标准反斜杠、缺失数组括号、非引号键名

---

## API 兼容性

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

---

## 快速部署

### Docker（推荐）

```bash
docker pull ghcr.io/jiujiu532/qwengateway:latest

docker run -d \
  -p 8080:8080 \
  -e ACCOUNTS_FILE=/data/accounts.json \
  -v /your/accounts.json:/data/accounts.json \
  ghcr.io/jiujiu532/qwengateway:latest
```

### docker-compose

```yaml
services:
  gateway:
    image: ghcr.io/jiujiu532/qwengateway:latest
    ports:
      - "8080:8080"
    environment:
      - ACCOUNTS_FILE=/data/accounts.json
      - GATEWAY_API_KEY=your-secret-key   # 可选
    volumes:
      - ./accounts.json:/data/accounts.json
    restart: unless-stopped
```

```bash
docker compose up -d
```

### 本地编译

```bash
# 需要 Go 1.22+
cd QwenGateway
go build -ldflags="-s -w" -o gateway ./cmd/
./gateway
```

---

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `GATEWAY_ADDR` | `:8080` | 监听地址 |
| `ACCOUNTS_FILE` | ` ` | JSON 账号文件路径（文件模式） |
| `REDIS_ADDR` | `localhost:6379` | Redis 地址（Redis 模式） |
| `REDIS_PASSWORD` | ` ` | Redis 密码 |
| `GATEWAY_API_KEY` | ` ` | 网关鉴权 Key（空 = 不鉴权） |
| `PYTHON_INTERNAL` | `http://localhost:7860/internal` | Python 后端内部 API |

---

## 账号文件格式

```json
[
  {
    "email": "user@example.com",
    "token": "eyJ...",
    "status_code": "VALID"
  }
]
```

---

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

---

## 项目结构

```
QwenGateway/
├── cmd/main.go              # 入口：路由、账号池初始化
├── internal/
│   ├── tls/                 # Chrome/Firefox TLS 指纹客户端池
│   ├── pool/
│   │   ├── pool.go          # 账号池 + EMA 排序
│   │   ├── breaker.go       # 熔断器
│   │   ├── warmer.go        # Session 预热
│   │   ├── probe.go         # 健康探针
│   │   └── file_loader.go   # 文件模式加载（无需 Redis）
│   ├── racing/race.go       # 并行竞速引擎
│   ├── proxy/
│   │   ├── sse.go           # SSE 流式代理 + ASCII 安全编码
│   │   ├── continue.go      # 自动续写（finish_reason:length）
│   │   └── image.go         # 图片生成
│   ├── toolcall/
│   │   ├── parse.go         # 三层工具调用解析（XML/Markup/JSON）
│   │   ├── xml.go           # 递归 XML DOM 解析器
│   │   ├── repair.go        # JSON 自动修复
│   │   ├── format.go        # 转换为 OpenAI tool_calls 格式
│   │   └── prompt.go        # System Prompt 注入
│   └── proto/
│       ├── openai.go        # OpenAI 协议
│       ├── anthropic.go     # Anthropic 协议
│       ├── gemini.go        # Gemini 协议
│       └── responses.go     # Responses API
└── Dockerfile               # 两阶段构建 → Alpine 镜像
```

---

## License

MIT
