// Package proto implements OpenAI Responses API format helpers.
package proto

import (
	"encoding/json"
	"fmt"
	"net/http"
	"time"

	"github.com/google/uuid"
)

// ResponsesAPIResponse is the non-streaming Responses API response format.
type ResponsesAPIResponse struct {
	ID        string         `json:"id"`
	Object    string         `json:"object"`
	CreatedAt int64          `json:"created_at"`
	Status    string         `json:"status"`
	Model     string         `json:"model"`
	Output    []ResponseItem `json:"output"`
	Usage     map[string]int `json:"usage"`
}

// ResponseItem is one output item in the Responses API.
type ResponseItem struct {
	ID      string         `json:"id"`
	Type    string         `json:"type"`
	Role    string         `json:"role"`
	Status  string         `json:"status"`
	Content []ResponsePart `json:"content"`
}

// ResponsePart is one content part in a ResponseItem.
type ResponsePart struct {
	Type string `json:"type"`
	Text string `json:"text"`
}

// BuildResponsesAPIResponse returns a Responses API JSON response for plain text.
func BuildResponsesAPIResponse(model, text string) ResponsesAPIResponse {
	respID := "resp_" + uuid.New().String()[:12]
	msgID := "msg_" + uuid.New().String()[:12]
	return ResponsesAPIResponse{
		ID:        respID,
		Object:    "realtime.response",
		CreatedAt: time.Now().Unix(),
		Status:    "completed",
		Model:     model,
		Output: []ResponseItem{{
			ID:     msgID,
			Type:   "message",
			Role:   "assistant",
			Status: "completed",
			Content: []ResponsePart{{
				Type: "output_text",
				Text: text,
			}},
		}},
		Usage: map[string]int{
			"input_tokens":  0,
			"output_tokens": len([]rune(text)) / 4,
			"total_tokens":  len([]rune(text)) / 4,
		},
	}
}

// StreamResponsesAPI writes the full text as Responses API SSE events
// in the format expected by @ai-sdk/openai's Responses adapter.
func StreamResponsesAPI(w http.ResponseWriter, model, text string) {
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	flusher, canFlush := w.(http.Flusher)

	emit := func(event string, data any) {
		b, _ := json.Marshal(data)
		fmt.Fprintf(w, "event: %s\ndata: %s\n\n", event, b)
		if canFlush {
			flusher.Flush()
		}
	}

	respID := "resp_" + uuid.New().String()[:12]
	msgID := "msg_" + uuid.New().String()[:12]
	created := time.Now().Unix()

	emit("response.created", map[string]any{
		"type": "response.created",
		"response": map[string]any{
			"id": respID, "object": "realtime.response",
			"created_at": created, "status": "in_progress", "model": model,
		},
	})
	emit("response.output_item.added", map[string]any{
		"type": "response.output_item.added", "output_index": 0,
		"item": map[string]any{"id": msgID, "type": "message", "role": "assistant", "status": "in_progress", "content": []any{}},
	})
	emit("response.content_part.added", map[string]any{
		"type": "response.content_part.added", "item_id": msgID,
		"output_index": 0, "content_index": 0,
		"part": map[string]any{"type": "output_text", "text": ""},
	})

	runes := []rune(text)
	chunkSize := 8
	for i := 0; i < len(runes); i += chunkSize {
		end := i + chunkSize
		if end > len(runes) {
			end = len(runes)
		}
		emit("response.output_text.delta", map[string]any{
			"type": "response.output_text.delta", "item_id": msgID,
			"output_index": 0, "content_index": 0, "delta": string(runes[i:end]),
		})
	}

	emit("response.output_text.done", map[string]any{
		"type": "response.output_text.done", "item_id": msgID,
		"output_index": 0, "content_index": 0, "text": text,
	})
	emit("response.content_part.done", map[string]any{
		"type": "response.content_part.done", "item_id": msgID,
		"output_index": 0, "content_index": 0,
		"part": map[string]any{"type": "output_text", "text": text},
	})
	emit("response.output_item.done", map[string]any{
		"type": "response.output_item.done", "output_index": 0,
		"item": map[string]any{
			"id": msgID, "type": "message", "role": "assistant", "status": "completed",
			"content": []any{map[string]any{"type": "output_text", "text": text}},
		},
	})
	emit("response.completed", map[string]any{
		"type": "response.completed",
		"response": map[string]any{
			"id": respID, "object": "realtime.response",
			"created_at": created, "status": "completed", "model": model,
			"output": []any{map[string]any{
				"id": msgID, "type": "message", "role": "assistant", "status": "completed",
				"content": []any{map[string]any{"type": "output_text", "text": text}},
			}},
		},
	})
}
