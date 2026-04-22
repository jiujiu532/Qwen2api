package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/redis/go-redis/v9"

	"github.com/jiujiu532/qwengateway/internal/pool"
	"github.com/jiujiu532/qwengateway/internal/proto"
	"github.com/jiujiu532/qwengateway/internal/proxy"
	"github.com/jiujiu532/qwengateway/internal/racing"
	tlsclient "github.com/jiujiu532/qwengateway/internal/tls"
	"github.com/jiujiu532/qwengateway/internal/toolcall"
)

// Request-level counters — exposed in /health for accurate monitoring.
// New-API or any OpenAI-compatible frontend can compare these against its own
// error logs to detect empty/failed upstream responses.
var (
	counterTotal         int64 // every request received
	counterRaceFailed    int64 // race() returned error (all accounts failed)
	counterEmptyResponse int64 // race won but SSE produced 0 tokens
	counterSuccess       int64 // non-empty content returned
)

type Config struct {
	ListenAddr     string
	RedisAddr      string
	RedisPassword  string
	AccountsFile   string
	PythonInternal string
	RaceCount      int
	APIKey         string
}

func loadConfig() Config {
	accountsFile := getEnv("ACCOUNTS_FILE", "")
	if accountsFile == "" {
		exe, _ := os.Executable()
		candidates := []string{
			filepath.Join(filepath.Dir(exe), "..", "QwenAdmin", "data", "accounts.json"),
			filepath.Join(".", "..", "QwenAdmin", "data", "accounts.json"),
		}
		for _, c := range candidates {
			if _, err := os.Stat(c); err == nil {
				accountsFile = filepath.Clean(c)
				slog.Info("[config] ACCOUNTS_FILE auto-detected", "path", accountsFile)
				break
			}
		}
	}
	return Config{
		ListenAddr:     getEnv("GATEWAY_ADDR", ":8080"),
		RedisAddr:      getEnv("REDIS_ADDR", ""),
		RedisPassword:  getEnv("REDIS_PASSWORD", ""),
		AccountsFile:   accountsFile,
		PythonInternal: getEnv("PYTHON_INTERNAL", "http://localhost:7860/internal"),
		RaceCount:      3,
		APIKey:         getEnv("GATEWAY_API_KEY", ""),
	}
}

func getEnv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

type PoolManager interface {
	Size() int
	TopN(n int) []*pool.Account
	RecordSuccess(acc *pool.Account, latencyMs int64)
}

func main() {
	cfg := loadConfig()
	slog.Info("QwenGateway starting", "addr", cfg.ListenAddr)
	tlsclient.WarmPool()

	var pm PoolManager
	if cfg.AccountsFile != "" {
		slog.Info("File mode: loading accounts from JSON", "path", cfg.AccountsFile)
		fw := pool.NewFilePoolWrapper(cfg.AccountsFile)
		pool.NewWarmerFromWrapper(fw)
		pm = fw
	} else {
		redisAddr := cfg.RedisAddr
		if redisAddr == "" {
			redisAddr = "localhost:6379"
		}
		rdb := redis.NewClient(&redis.Options{Addr: redisAddr, Password: cfg.RedisPassword})
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		if err := rdb.Ping(ctx).Err(); err != nil {
			slog.Error("Redis connection failed", "error", err,
				"hint", "Set ACCOUNTS_FILE env var to use file mode without Redis")
			os.Exit(1)
		}
		slog.Info("Redis connected", "addr", redisAddr)
		accountPool := pool.New(rdb)
		pool.NewWarmer(accountPool)
		pool.NewProbe(accountPool, cfg.PythonInternal+"/accounts/mark")
		pm = accountPool
	}

	gin.SetMode(gin.ReleaseMode)
	r := gin.New()
	r.Use(gin.Recovery())

	if cfg.APIKey != "" {
		r.Use(func(c *gin.Context) {
			bearer := c.GetHeader("Authorization")
			xKey := c.GetHeader("x-api-key")
			qKey := c.Query("key")
			if bearer != "Bearer "+cfg.APIKey && xKey != cfg.APIKey && qKey != cfg.APIKey {
				c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "invalid API key"})
				return
			}
			c.Next()
		})
	}

	r.GET("/health", func(c *gin.Context) {
		total := atomic.LoadInt64(&counterTotal)
		success := atomic.LoadInt64(&counterSuccess)
		raceFail := atomic.LoadInt64(&counterRaceFailed)
		empty := atomic.LoadInt64(&counterEmptyResponse)
		var errorRate float64
		if total > 0 {
			errorRate = float64(raceFail+empty) / float64(total) * 100
		}
		c.JSON(http.StatusOK, gin.H{
			"status":         "ok",
			"accounts":       pm.Size(),
			"requests_total": total,
			"success":        success,
			"race_failed":    raceFail,
			"empty_response": empty,
			"error_rate_pct": fmt.Sprintf("%.1f%%", errorRate),
		})
	})

	r.GET("/v1/models", func(c *gin.Context) {
		mk := func(id string) gin.H { return gin.H{"id": id, "object": "model", "owned_by": "qwen"} }
		c.JSON(http.StatusOK, gin.H{"object": "list", "data": []gin.H{
			mk("qwen3.6-plus"), mk("qwen3.6-plus-thinking"), mk("qwen3.6-plus-no-think"),
			mk("qwen3.6-max-preview"), mk("qwen3.6-max-preview-no-think"),
		}})
	})

	geminiIDs := []string{"qwen3.6-plus", "qwen3.6-plus-thinking", "qwen3.6-plus-no-think", "qwen3.6-max-preview", "qwen3.6-max-preview-no-think"}
	mkGemini := func(id string) gin.H {
		return gin.H{"name": "models/" + id, "version": "001", "displayName": id,
			"supportedGenerationMethods": []string{"generateContent", "streamGenerateContent"}}
	}
	r.GET("/v1beta/models", func(c *gin.Context) {
		var list []gin.H
		for _, id := range geminiIDs {
			list = append(list, mkGemini(id))
		}
		c.JSON(http.StatusOK, gin.H{"models": list})
	})
	r.GET("/v1beta/models/:model", func(c *gin.Context) {
		c.JSON(http.StatusOK, mkGemini(c.Param("model")))
	})

	r.POST("/v1/chat/completions", func(c *gin.Context) {
		var req proto.OpenAIRequest
		if err := c.ShouldBindJSON(&req); err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
			return
		}
		handleChatRequest(c, pm, cfg, req)
	})

	r.POST("/v1/images/generations", func(c *gin.Context) {
		var req proxy.ImageRequest
		if err := c.ShouldBindJSON(&req); err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
			return
		}
		candidates := pm.TopN(1)
		if len(candidates) == 0 {
			c.JSON(http.StatusServiceUnavailable, gin.H{"error": "no valid accounts"})
			return
		}
		acc := candidates[0]
		sessionID, serr := pool.AcquireSession(c.Request.Context(), acc)
		if serr != nil {
			c.JSON(http.StatusBadGateway, gin.H{"error": serr.Error()})
			return
		}
		result, err := proxy.GenerateImage(c.Request.Context(), acc.Token, sessionID, req, cfg.PythonInternal)
		if err != nil {
			c.JSON(http.StatusBadGateway, gin.H{"error": err.Error()})
			return
		}
		c.JSON(http.StatusOK, result)
	})

	// ── Anthropic /v1/messages ────────────────────────────────────────────────
	r.POST("/v1/messages", func(c *gin.Context) {
		var req proto.AnthropicRequest
		if err := c.ShouldBindJSON(&req); err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
			return
		}
		openaiReq := proto.AnthropicToOpenAI(req)
		content, err := proto.MessagesToContent(openaiReq)
		if err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
			return
		}
		candidates := pm.TopN(cfg.RaceCount)
		if len(candidates) == 0 {
			c.JSON(http.StatusServiceUnavailable, gin.H{"error": "no valid accounts"})
			return
		}
		modelCfg := proto.ParseModel(openaiReq.Model)
		hasTools := len(openaiReq.Tools) > 0
		basePayload := proto.BuildQwenPayload("__placeholder__", modelCfg, content, hasTools, false)
		msgID := "msg_" + uuid.New().String()[:12]

		winner, werr := racing.Race(c.Request.Context(), candidates, modelCfg.QwenModelID, basePayload, pool.AcquireSession)
		if werr != nil {
			c.JSON(http.StatusBadGateway, gin.H{"error": werr.Error()})
			return
		}
		defer winner.Cancel()
		pm.RecordSuccess(winner.Account, winner.LatencyMs)

		// Estimate input tokens from converted messages.
		inputTokenEst := proto.EstimateInputTokens(openaiReq.Messages)

		if req.Stream {
			// Real-time streaming: convert Qwen SSE → Claude SSE token by token.
			proxy.AnthropicStreamToClient(
				c.Writer,
				winner.Resp.Body,
				winner.Resp.StatusCode,
				msgID,
				openaiReq.Model,
				openaiReq.Tools,
				inputTokenEst,
			)
		} else {
			// Non-streaming: collect full response then format as Claude JSON.
			nw := &nullWriter{h: http.Header{}}
			result := proxy.StreamSSE(nw, winner.Resp.Body, winner.Resp.StatusCode, msgID, openaiReq.Model, openaiReq.Tools)
			if len(result.ToolCalls) > 0 {
				c.JSON(http.StatusOK, proto.BuildAnthropicToolCallResponse(openaiReq.Model, result.ToolCalls))
			} else {
				resp := proto.BuildAnthropicTextResponse(openaiReq.Model, result.FullText)
				// Update usage with actual estimated tokens.
				if usage, ok := resp["usage"].(map[string]any); ok {
					usage["input_tokens"] = inputTokenEst
				}
				c.JSON(http.StatusOK, resp)
			}
		}
	})


	// ── Gemini /v1beta/models/* ───────────────────────────────────────────────
	r.POST("/v1beta/models/*modelaction", func(c *gin.Context) {
		raw := strings.TrimPrefix(c.Param("modelaction"), "/")
		var model string
		var isStream bool
		if idx := strings.Index(raw, ":"); idx >= 0 {
			model = raw[:idx]
			isStream = strings.Contains(strings.ToLower(raw[idx+1:]), "stream")
		} else if idx2 := strings.LastIndex(raw, "/"); idx2 >= 0 {
			model = raw[:idx2]
			isStream = strings.Contains(strings.ToLower(raw[idx2+1:]), "stream")
		} else {
			c.JSON(http.StatusNotFound, gin.H{"error": "unknown Gemini endpoint: " + raw})
			return
		}
		var req proto.GeminiRequest
		if err := c.ShouldBindJSON(&req); err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
			return
		}
		openaiReq := proto.GeminiToOpenAI(req)
		openaiReq.Stream = isStream
		content, err := proto.MessagesToContent(openaiReq)
		if err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
			return
		}
		candidates := pm.TopN(cfg.RaceCount)
		if len(candidates) == 0 {
			c.JSON(http.StatusServiceUnavailable, gin.H{"error": "no valid accounts"})
			return
		}
		modelCfg := proto.ParseModel(model)
		hasTools := len(openaiReq.Tools) > 0
		basePayload := proto.BuildQwenPayload("__placeholder__", modelCfg, content, hasTools, false)
		requestID := "chatcmpl-" + uuid.New().String()[:12]
		winner, werr := racing.Race(c.Request.Context(), candidates, modelCfg.QwenModelID, basePayload, pool.AcquireSession)
		if werr != nil {
			c.JSON(http.StatusBadGateway, gin.H{"error": werr.Error()})
			return
		}
		defer winner.Cancel()
		pm.RecordSuccess(winner.Account, winner.LatencyMs)
		var gWriter http.ResponseWriter
		if isStream {
			gWriter = c.Writer
		} else {
			gWriter = &nullWriter{h: http.Header{}}
		}
		result := proxy.StreamSSE(gWriter, winner.Resp.Body, winner.Resp.StatusCode, requestID, modelCfg.QwenModelID, openaiReq.Tools)
		if !isStream {
			if len(result.ToolCalls) > 0 {
				c.JSON(http.StatusOK, proto.BuildGeminiToolCallResponse(model, result.ToolCalls))
			} else {
				c.JSON(http.StatusOK, proto.BuildGeminiTextResponse(model, result.FullText))
			}
		}
	})

	// ── Responses API /v1/responses ───────────────────────────────────────────
	r.POST("/v1/responses", func(c *gin.Context) {
		var body struct {
			Model  string `json:"model"`
			Input  any    `json:"input"`
			Stream bool   `json:"stream"`
		}
		if err := c.ShouldBindJSON(&body); err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
			return
		}
		var messages []proto.OpenAIMessage
		switch v := body.Input.(type) {
		case string:
			messages = []proto.OpenAIMessage{{Role: "user", Content: v}}
		case []any:
			for _, item := range v {
				if m, ok := item.(map[string]any); ok {
					role, _ := m["role"].(string)
					if role == "" {
						role = "user"
					}
					var text string
					switch cv := m["content"].(type) {
					case string:
						text = cv
					case []any:
						for _, part := range cv {
							if p, ok2 := part.(map[string]any); ok2 {
								if t, ok3 := p["text"].(string); ok3 {
									text += t
								}
							}
						}
					}
					messages = append(messages, proto.OpenAIMessage{Role: role, Content: text})
				}
			}
		}
		if len(messages) == 0 {
			messages = []proto.OpenAIMessage{{Role: "user", Content: ""}}
		}
		openaiReq := proto.OpenAIRequest{Model: body.Model, Messages: messages, Stream: false}
		content, err := proto.MessagesToContent(openaiReq)
		if err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
			return
		}
		candidates := pm.TopN(cfg.RaceCount)
		if len(candidates) == 0 {
			c.JSON(http.StatusServiceUnavailable, gin.H{"error": "no valid accounts"})
			return
		}
		modelCfg := proto.ParseModel(openaiReq.Model)
		basePayload := proto.BuildQwenPayload("__placeholder__", modelCfg, content, false, false)
		winner, werr := racing.Race(c.Request.Context(), candidates, modelCfg.QwenModelID, basePayload, pool.AcquireSession)
		if werr != nil {
			c.JSON(http.StatusBadGateway, gin.H{"error": werr.Error()})
			return
		}
		defer winner.Cancel()
		pm.RecordSuccess(winner.Account, winner.LatencyMs)
		nw := &nullWriter{h: http.Header{}}
		result := proxy.StreamSSE(nw, winner.Resp.Body, winner.Resp.StatusCode, "resp_"+uuid.New().String()[:12], openaiReq.Model, nil)
		if body.Stream {
			proto.StreamResponsesAPI(c.Writer, openaiReq.Model, result.FullText)
		} else {
			c.JSON(http.StatusOK, proto.BuildResponsesAPIResponse(openaiReq.Model, result.FullText))
		}
	})

	slog.Info("Gateway ready", "addr", cfg.ListenAddr, "accounts", pm.Size())
	if err := r.Run(cfg.ListenAddr); err != nil {
		slog.Error("Gateway crashed", "error", err)
		os.Exit(1)
	}
}

// nullWriter discards all HTTP response writes.
type nullWriter struct{ h http.Header }

func (n *nullWriter) Header() http.Header         { return n.h }
func (n *nullWriter) Write(b []byte) (int, error) { return len(b), nil }
func (n *nullWriter) WriteHeader(_ int)           {}

func handleChatRequest(c *gin.Context, pm PoolManager, cfg Config, req proto.OpenAIRequest) {
	modelCfg := proto.ParseModel(req.Model)
	hasTools := len(req.Tools) > 0
	content, err := proto.MessagesToContent(req)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	candidates := pm.TopN(cfg.RaceCount)
	if len(candidates) == 0 {
		c.JSON(http.StatusServiceUnavailable, gin.H{
			"error": fmt.Sprintf("no valid accounts (pool size=%d)", pm.Size()),
		})
		return
	}
	basePayload := proto.BuildQwenPayload("__placeholder__", modelCfg, content, hasTools, false)
	requestID := "chatcmpl-" + uuid.New().String()[:12]

	atomic.AddInt64(&counterTotal, 1)
	winner, err := racing.Race(c.Request.Context(), candidates, modelCfg.QwenModelID, basePayload, pool.AcquireSession)
	if err != nil {
		atomic.AddInt64(&counterRaceFailed, 1)
		slog.Warn("[handler] race failed", "error", err, "race_failed_total", atomic.LoadInt64(&counterRaceFailed))
		c.JSON(http.StatusBadGateway, gin.H{"error": "upstream unavailable: " + err.Error()})
		return
	}
	slog.Info("[handler] race won", "email", winner.Account.Email, "latency_ms", winner.LatencyMs, "model", modelCfg.QwenModelID)
	defer winner.Cancel()
	pm.RecordSuccess(winner.Account, winner.LatencyMs)

	sseBody := proxy.WrapWithAutoContinue(c.Request.Context(), winner.Resp.Body,
		func(ctx context.Context) (io.ReadCloser, error) {
			bodyBytes, err := proxy.BuildContinueRequest(winner.SessionID, modelCfg.QwenModelID)
			if err != nil {
				return nil, err
			}
			url := fmt.Sprintf("%s/api/v2/chat/completions?chat_id=%s", tlsclient.BaseURL, winner.SessionID)
			req2, err := http.NewRequestWithContext(ctx, "POST", url, bytes.NewReader(bodyBytes))
			if err != nil {
				return nil, err
			}
			headers := tlsclient.BaseHeaders(winner.Account.Token)
			headers["Content-Type"] = "application/json"
			headers["Accept"] = "text/event-stream"
			for k, v := range headers {
				req2.Header.Set(k, v)
			}
			resp, err := tlsclient.FallbackClient().Do(req2)
			if err != nil {
				return nil, err
			}
			return resp.Body, nil
		})

	var sseWriter http.ResponseWriter = c.Writer
	if !req.Stream {
		sseWriter = &nullWriter{h: http.Header{}}
	}
	result := proxy.StreamSSE(sseWriter, sseBody, winner.Resp.StatusCode, requestID, req.Model, req.Tools)

	// Track outcome for /health accuracy
	isEmpty := result.FullText == "" && len(result.ToolCalls) == 0
	if isEmpty {
		atomic.AddInt64(&counterEmptyResponse, 1)
		slog.Warn("[handler] empty SSE result (0 tokens)",
			"email", winner.Account.Email,
			"model", modelCfg.QwenModelID,
			"empty_total", atomic.LoadInt64(&counterEmptyResponse))
	} else {
		atomic.AddInt64(&counterSuccess, 1)
	}

	if !req.Stream {
		if isEmpty {
			// Return 503 so New-API records this as a real failure
			// and channel health history turns red/orange.
			c.JSON(http.StatusServiceUnavailable, gin.H{
				"error": gin.H{
					"message": "upstream returned empty response",
					"type":    "upstream_error",
					"code":    "empty_response",
				},
			})
			return
		}
		if len(result.ToolCalls) > 0 {
			c.JSON(http.StatusOK, buildNonStreamToolResponse(requestID, req.Model, result.ToolCalls))
		} else {
			c.JSON(http.StatusOK, buildNonStreamTextResponse(requestID, req.Model, result.FullText))
		}
	} else if isEmpty {
		// Streaming: headers already sent, can't change status.
		// Emit an error SSE event so the client knows the response failed.
		fmt.Fprintf(c.Writer, "data: {\"error\":{\"message\":\"upstream returned empty response\",\"type\":\"upstream_error\"}}\n\n")
		if f, ok := c.Writer.(http.Flusher); ok {
			f.Flush()
		}
	}
}

func buildNonStreamTextResponse(id, model, text string) map[string]any {
	return map[string]any{
		"id": id, "object": "chat.completion", "created": time.Now().Unix(),
		"model": model,
		"choices": []map[string]any{{
			"index":         0,
			"message":       map[string]any{"role": "assistant", "content": text},
			"finish_reason": "stop",
		}},
		"usage": map[string]any{
			"prompt_tokens": 0, "completion_tokens": len([]rune(text)) / 4, "total_tokens": len([]rune(text)) / 4,
		},
	}
}

func buildNonStreamToolResponse(id, model string, calls []toolcall.OpenAIToolCall) map[string]any {
	b, _ := json.Marshal(calls)
	return map[string]any{
		"id": id, "object": "chat.completion", "created": time.Now().Unix(),
		"model": model,
		"choices": []map[string]any{{
			"index":         0,
			"message":       map[string]any{"role": "assistant", "content": nil, "tool_calls": json.RawMessage(b)},
			"finish_reason": "tool_calls",
		}},
	}
}
