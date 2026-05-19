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
  Qwen AI Reverse Gateway -- OpenAI / Anthropic / Gemini API Compatible
</p>

<p align="center"><a href="README.md">中文</a> | English</p>

---

## Overview

qwen2api exposes Alibaba's Qwen (Tongyi Qianwen) web interface as standard API endpoints. It features multi-account pool rotation, automatic account registration, tool calling, streaming output, and works directly with Cherry Studio, Cursor, Claude Code, Cline, New-API, and other clients.

## Key Features

- **Multi-protocol** -- OpenAI Chat Completions / Responses API / Anthropic Messages / Gemini generateContent
- **Account pool scheduling** -- Min-Heap priority scheduling, 6-state lifecycle management, circuit breaker auto-fuse
- **Auto registration** -- MoeMail / TempMail / GuerrillaMail channels, emergency registration on account exhaustion
- **Tool calling** -- Native FC first + XML Fallback, streaming leak-prevention state machine, loop detection
- **Thinking mode** -- Model name suffix control (-thinking / -nothinking) or reasoning_effort parameter override
- **Image generation** -- OpenAI DALL-E compatible, auto-detects user intent and routes to T2I
- **Admin panel** -- Built-in React Web UI with real-time SSE events, account/key/settings/stats management
- **Multi-engine** -- httpx direct (fast) / Camoufox browser fingerprint (anti-detection) / hybrid mode
- **Fault tolerance** -- Auto retry with account rotation on upstream failure, NativeBlock detection with XML fallback

## Supported Endpoints

| Protocol | Endpoint | Function |
|----------|----------|----------|
| OpenAI | `POST /v1/chat/completions` | Chat completion (stream/non-stream/tools/thinking) |
| OpenAI | `POST /v1/responses` | Responses API (Codex / Agents) |
| OpenAI | `POST /v1/images/generations` | Image generation |
| OpenAI | `POST /v1/embeddings` | Text embeddings |
| OpenAI | `GET /v1/models` | Model list |
| Anthropic | `POST /v1/messages` | Claude compatible (tool_use / thinking) |
| Gemini | `POST /v1beta/models/{m}:generateContent` | Gemini compatible |
| Gemini | `POST /v1beta/models/{m}:streamGenerateContent` | Gemini streaming |

## Available Models

### Native Qwen Models

| Model | Description |
|-------|-------------|
| `qwen3.6-plus` | Primary model, auto thinking |
| `qwen3.6-plus-thinking` | Force deep thinking |
| `qwen3.6-plus-nothinking` | Fast mode |
| `qwen3.6-max-preview` | High performance preview |
| `qwen3.6-27b` | Lightweight |
| `qwen3.7-max-preview` | 3.7 series (thinking only) |
| `qwen3.7-plus-preview` | 3.7 Plus preview |

All models support `-thinking` / `-nothinking` suffix.

### Built-in Aliases

Use common model names directly without configuration:

```
gpt-4o / gpt-4o-mini / gpt-4.1 / gpt-3.5-turbo
o1 / o3 / o3-mini / o4-mini
claude-3-5-sonnet-latest / claude-sonnet-4-20250514 / claude-3-opus-latest
gemini-2.5-pro / gemini-2.5-flash / gemini-2.0-flash
deepseek-chat / deepseek-reasoner
```

## Quick Start

### Docker (Recommended)

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
# Edit .env to set ADMIN_KEY and mail channels
docker-compose up -d
```

### Local

```bash
# Python 3.12+
pip install -r backend/requirements.txt
python start.py
```

Visit `http://localhost:7860` after startup. Default admin key: `123456`.

## Configuration

Via `.env` or environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `ADMIN_KEY` | `123456` | Admin panel key |
| `PORT` | `7860` | Service port |
| `ENGINE_MODE` | `hybrid` | httpx / browser / hybrid |
| `AUTO_REPLENISH` | `false` | Auto registration toggle |
| `REPLENISH_TARGET` | `30` | Target account count |
| `MOEMAIL_DOMAIN` | - | MoeMail domain |
| `MOEMAIL_KEY` | - | MoeMail API key |
| `TEMPMAIL_DOMAIN` | - | TempMail domain |
| `TEMPMAIL_KEY` | - | TempMail API key |
| `PROXY_URL` | - | Registration proxy URL |
| `NATIVE_TOOL_PASSTHROUGH` | `true` | Prefer Qwen native FC |
| `MAX_INFLIGHT_PER_ACCOUNT` | `1` | Max concurrent per account |

See [.env.example](.env.example) for full configuration.

## Usage Examples

### OpenAI Format

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

### Anthropic Format

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

### Tool Calling

```bash
curl http://localhost:7860/v1/chat/completions \
  -H "Authorization: Bearer your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3.6-plus-nothinking",
    "messages": [{"role": "user", "content": "What is the weather in Beijing?"}],
    "tools": [{"type": "function", "function": {"name": "get_weather", "parameters": {"type": "object", "properties": {"city": {"type": "string"}}}}}],
    "stream": true
  }'
```

## Project Structure

```
qwen2api/
├── backend/
│   ├── api/              # Route layer (thin, parsing + formatting)
│   │   ├── chat.py           # OpenAI Chat Completions
│   │   ├── anthropic.py      # Anthropic Messages
│   │   ├── gemini.py         # Gemini generateContent
│   │   ├── responses.py      # OpenAI Responses API
│   │   ├── images.py         # Image generation
│   │   └── admin/            # Admin panel (accounts/keys/settings/stats)
│   ├── engine/           # Core engine (business logic)
│   │   └── completion.py     # Unified Completion Executor
│   ├── core/             # Infrastructure
│   │   ├── account_pool.py   # Account pool scheduling
│   │   ├── config.py         # Configuration
│   │   ├── auth.py           # API authentication
│   │   └── hybrid_engine.py  # HTTP engine
│   └── services/         # Business services
│       ├── qwen_client.py    # Qwen upstream client
│       ├── tool_parser.py    # Tool call parsing
│       ├── prompt_builder.py # Prompt building
│       └── register.py       # Auto registration
├── frontend/             # React admin panel
├── data/                 # Runtime data
├── Dockerfile
├── docker-compose.yml
└── start.py
```

## Client Integration

| Client | Configuration |
|--------|---------------|
| Cherry Studio | API Base: `http://host:7860/v1`, model: `qwen3.6-plus` |
| Cursor | Settings > Models > OpenAI API Base |
| Claude Code | `ANTHROPIC_BASE_URL=http://host:7860` |
| Cline | OpenAI Compatible, fill Base URL |
| New-API | Add channel, type OpenAI, proxy URL = this service |

## License

MIT
