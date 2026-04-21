package proxy

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"regexp"
	"strings"
	"time"

	fhttp "github.com/bogdanfinn/fhttp"
	tlsclient "github.com/jiujiu532/qwengateway/internal/tls"
)

// ImageRequest matches the OpenAI /v1/images/generations request.
type ImageRequest struct {
	Prompt  string `json:"prompt"`
	N       int    `json:"n"`
	Size    string `json:"size"`
	Model   string `json:"model"`
}

// ImageResponse is the OpenAI-compatible image generation response.
type ImageResponse struct {
	Created int64           `json:"created"`
	Data    []ImageDataItem `json:"data"`
}

// ImageDataItem holds a single generated image URL.
type ImageDataItem struct {
	URL           string `json:"url"`
	RevisedPrompt string `json:"revised_prompt,omitempty"`
}

var imageURLPattern = regexp.MustCompile(`https?://[^\s"'<>]+\.(?:png|jpg|jpeg|webp|gif)(?:\?[^\s"'<>]*)?`)

// GenerateImage calls Qwen's image generation API and returns an OpenAI-compatible response.
// Falls back to Python if the Go-side parsing fails.
func GenerateImage(
	ctx context.Context,
	token string,
	chatID string,
	req ImageRequest,
	pythonFallbackURL string,
) (*ImageResponse, error) {
	if req.N <= 0 {
		req.N = 1
	}

	// Build a Qwen chat payload requesting image generation
	prompt := fmt.Sprintf(
		"请根据以下描述生成%d张图片：%s\n图片尺寸：%s",
		req.N, req.Prompt, req.Size,
	)
	ts := time.Now().Unix()
	payload := map[string]any{
		"stream":             true,
		"version":            "2.1",
		"incremental_output": true,
		"chat_id":            chatID,
		"chat_mode":          "normal",
		"model":              "qwen-vl-plus",
		"timestamp":          ts,
		"messages": []map[string]any{{
			"fid":         fmt.Sprintf("img_%d", ts),
			"role":        "user",
			"content":     prompt,
			"user_action": "chat",
			"files":       []any{},
			"timestamp":   ts,
			"models":      []string{"qwen-vl-plus"},
			"chat_type":   "t2t",
			"extra":       map[string]any{},
		}},
	}

	bodyBytes, _ := json.Marshal(payload)
	client, err := tlsclient.NewStreamClient()
	if err != nil {
		return pythonFallback(ctx, req, pythonFallbackURL)
	}

	headers := tlsclient.BaseHeaders(token)
	headers["Content-Type"] = "application/json"
	headers["Accept"] = "text/event-stream"

	url := fmt.Sprintf("%s/api/v2/chat/completions?chat_id=%s", tlsclient.BaseURL, chatID)
	fReq, err := fhttp.NewRequestWithContext(ctx, "POST", url, bytes.NewReader(bodyBytes))
	if err != nil {
		return pythonFallback(ctx, req, pythonFallbackURL)
	}
	for k, v := range headers {
		fReq.Header.Set(k, v)
	}

	resp, err := client.Do(fReq)
	if err != nil || resp.StatusCode != 200 {
		slog.Warn("[image] upstream failed, falling back to Python", "error", err)
		return pythonFallback(ctx, req, pythonFallbackURL)
	}
	defer resp.Body.Close()

	// Collect all SSE text and extract image URLs
	fullText := collectSSEText(resp.Body)
	urls := imageURLPattern.FindAllString(fullText, req.N)

	if len(urls) == 0 {
		slog.Warn("[image] no URLs found in response, falling back to Python")
		return pythonFallback(ctx, req, pythonFallbackURL)
	}

	items := make([]ImageDataItem, 0, len(urls))
	for _, u := range urls {
		items = append(items, ImageDataItem{URL: u})
	}
	return &ImageResponse{
		Created: time.Now().Unix(),
		Data:    items,
	}, nil
}

func collectSSEText(body io.Reader) string {
	var sb strings.Builder
	buf, _ := io.ReadAll(body)
	for _, line := range strings.Split(string(buf), "\n") {
		if !strings.HasPrefix(line, "data:") {
			continue
		}
		dataStr := strings.TrimSpace(line[5:])
		if dataStr == "" || dataStr == "[DONE]" {
			continue
		}
		var raw map[string]any
		if err := json.Unmarshal([]byte(dataStr), &raw); err != nil {
			continue
		}
		if text := extractContent(raw); text != "" {
			sb.WriteString(text)
		}
	}
	return sb.String()
}

// pythonFallback proxies the image request to the Python backend.
func pythonFallback(ctx context.Context, req ImageRequest, pythonURL string) (*ImageResponse, error) {
	if pythonURL == "" {
		return nil, fmt.Errorf("no python fallback URL configured")
	}
	body, _ := json.Marshal(req)
	httpReq, err := http.NewRequestWithContext(ctx, "POST", pythonURL, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	httpReq.Header.Set("Content-Type", "application/json")

	client := &http.Client{Timeout: 120 * time.Second}
	resp, err := client.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("python fallback request failed: %w", err)
	}
	defer resp.Body.Close()

	var result ImageResponse
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("python fallback decode failed: %w", err)
	}
	return &result, nil
}
