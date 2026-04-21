// Package proto implements Claude (Anthropic) → Qwen request conversion.
package proto

import (
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jiujiu532/qwengateway/internal/toolcall"
)

// AnthropicRequest is a Claude Messages API request.
type AnthropicRequest struct {
	Model     string             `json:"model"`
	Messages  []AnthropicMessage `json:"messages"`
	System    any                `json:"system,omitempty"` // string or []ContentBlock
	MaxTokens int                `json:"max_tokens,omitempty"`
	Stream    bool               `json:"stream"`
	RawTools  json.RawMessage    `json:"tools,omitempty"` // handles "[undefined]" strings from some clients
}

// AnthropicMessage is one Claude message.
type AnthropicMessage struct {
	Role    string `json:"role"`
	Content any    `json:"content"` // string or []ContentBlock
}

// ContentBlock is a multi-part content block in Claude messages.
type ContentBlock struct {
	Type string `json:"type"`
	Text string `json:"text,omitempty"`
}

// AnthropicToOpenAI converts a Claude request to our internal OpenAI format.
func AnthropicToOpenAI(req AnthropicRequest) OpenAIRequest {
	var messages []OpenAIMessage

	// Inject system message if present (can be string or array of content blocks)
	if req.System != nil {
		systemText := extractAnthropicContent(req.System)
		if systemText != "" {
			messages = append(messages, OpenAIMessage{Role: "system", Content: systemText})
		}
	}

	for _, m := range req.Messages {
		text := extractAnthropicContent(m.Content)
		messages = append(messages, OpenAIMessage{Role: m.Role, Content: text})
	}

	return OpenAIRequest{
		Model:    req.Model,
		Messages: messages,
		Stream:   req.Stream,
		Tools:    req.GetTools(),
	}
}

// GetTools parses the raw tools field, returning nil if it's "[undefined]" or invalid.
func (r AnthropicRequest) GetTools() []toolcall.Tool {
	if len(r.RawTools) == 0 {
		return nil
	}
	s := string(r.RawTools)
	if s == `"[undefined]"` || s == "null" || s[0] != '[' {
		return nil
	}
	var tools []toolcall.Tool
	if err := json.Unmarshal(r.RawTools, &tools); err != nil {
		return nil
	}
	return tools
}

func extractAnthropicContent(content any) string {
	switch v := content.(type) {
	case string:
		return v
	case []any:
		var parts []string
		for _, block := range v {
			if b, ok := block.(map[string]any); ok {
				blockType, _ := b["type"].(string)
				switch blockType {
				case "text":
					if t, ok := b["text"].(string); ok {
						parts = append(parts, t)
					}
				case "tool_result":
					// Include tool execution results so the model knows what happened.
					switch tc := b["content"].(type) {
					case string:
						parts = append(parts, tc)
					case []any:
						for _, item := range tc {
							if m, ok := item.(map[string]any); ok {
								if t, ok := m["text"].(string); ok {
									parts = append(parts, t)
								}
							}
						}
					}
				case "tool_use":
					// Represent outgoing tool calls as context so multi-turn works.
					name, _ := b["name"].(string)
					inputBytes, _ := json.Marshal(b["input"])
					parts = append(parts, fmt.Sprintf("[Tool call: %s(%s)]", name, string(inputBytes)))
				}
			}
		}
		return strings.Join(parts, "\n")
	default:
		b, _ := json.Marshal(v)
		return string(b)
	}
}

// BuildAnthropicStreamChunk produces a Claude-compatible SSE delta chunk.
func BuildAnthropicStreamChunk(msgID, model, text string, inputTokens int) []string {
	created := time.Now().Unix()
	_ = created

	start, _ := json.Marshal(map[string]any{
		"type": "message_start",
		"message": map[string]any{
			"id": msgID, "type": "message", "role": "assistant",
			"model":   model,
			"content": []any{},
			"usage":   map[string]any{"input_tokens": inputTokens, "output_tokens": 0},
		},
	})
	blockStart, _ := json.Marshal(map[string]any{
		"type": "content_block_start", "index": 0,
		"content_block": map[string]any{"type": "text", "text": ""},
	})
	delta, _ := json.Marshal(map[string]any{
		"type": "content_block_delta", "index": 0,
		"delta": map[string]any{"type": "text_delta", "text": text},
	})
	blockStop, _ := json.Marshal(map[string]any{"type": "content_block_stop", "index": 0})
	msgDelta, _ := json.Marshal(map[string]any{
		"type":  "message_delta",
		"delta": map[string]any{"stop_reason": "end_turn", "stop_sequence": nil},
		"usage": map[string]any{"output_tokens": len(text) / 4},
	})
	msgStop, _ := json.Marshal(map[string]any{"type": "message_stop"})

	return []string{
		"event: message_start\ndata: " + string(start),
		"event: content_block_start\ndata: " + string(blockStart),
		"event: content_block_delta\ndata: " + string(delta),
		"event: content_block_stop\ndata: " + string(blockStop),
		"event: message_delta\ndata: " + string(msgDelta),
		"event: message_stop\ndata: " + string(msgStop),
	}
}


// BuildAnthropicToolUseStreamChunk produces Claude-compatible SSE events for tool_use responses.
func BuildAnthropicToolUseStreamChunk(msgID, model string, calls []toolcall.OpenAIToolCall) []string {
	start, _ := json.Marshal(map[string]any{
		"type": "message_start",
		"message": map[string]any{
			"id": msgID, "type": "message", "role": "assistant",
			"model": model, "content": []any{},
			"usage": map[string]any{"input_tokens": 0, "output_tokens": 0},
		},
	})
	msgStop, _ := json.Marshal(map[string]any{"type": "message_stop"})
	msgDelta, _ := json.Marshal(map[string]any{
		"type": "message_delta",
		"delta": map[string]any{"stop_reason": "tool_use", "stop_sequence": nil},
		"usage": map[string]any{"output_tokens": 0},
	})
	chunks := []string{"event: message_start\ndata: " + string(start)}
	for i, call := range calls {
		toolID := "toolu_" + uuid.New().String()[:8]
		blockStart, _ := json.Marshal(map[string]any{
			"type": "content_block_start", "index": i,
			"content_block": map[string]any{
				"type": "tool_use", "id": toolID,
				"name": call.Function.Name, "input": map[string]any{},
			},
		})
		inputDelta, _ := json.Marshal(map[string]any{
			"type": "content_block_delta", "index": i,
			"delta": map[string]any{"type": "input_json_delta", "partial_json": call.Function.Arguments},
		})
		blockStop, _ := json.Marshal(map[string]any{"type": "content_block_stop", "index": i})
		chunks = append(chunks,
			"event: content_block_start\ndata: "+string(blockStart),
			"event: content_block_delta\ndata: "+string(inputDelta),
			"event: content_block_stop\ndata: "+string(blockStop),
		)
	}
	chunks = append(chunks,
		"event: message_delta\ndata: "+string(msgDelta),
		"event: message_stop\ndata: "+string(msgStop),
	)
	return chunks
}

// BuildAnthropicToolCallResponse builds a Claude-compatible tool use response.
func BuildAnthropicToolCallResponse(model string, calls []toolcall.OpenAIToolCall) map[string]any {
	content := make([]map[string]any, 0, len(calls))
	for _, c := range calls {
		var input map[string]any
		_ = json.Unmarshal([]byte(c.Function.Arguments), &input)
		content = append(content, map[string]any{
			"type":  "tool_use",
			"id":    "toolu_" + uuid.New().String()[:8],
			"name":  c.Function.Name,
			"input": input,
		})
	}
	return map[string]any{
		"id": "msg_" + uuid.New().String()[:12], "type": "message",
		"role": "assistant", "model": model,
		"content":      content,
		"stop_reason":  "tool_use",
		"stop_sequence": nil,
		"usage": map[string]any{
			"input_tokens": 0, "output_tokens": 0,
		},
	}
}

// BuildAnthropicTextResponse builds a Claude-compatible non-streaming text response.
func BuildAnthropicTextResponse(model, text string) map[string]any {
	return map[string]any{
		"id": "msg_" + uuid.New().String()[:12], "type": "message",
		"role": "assistant", "model": model,
		"content":      []map[string]any{{"type": "text", "text": text}},
		"stop_reason":  "end_turn",
		"stop_sequence": nil,
		"usage": map[string]any{
			"input_tokens": 0, "output_tokens": len(text) / 4,
		},
	}
}

// ToAnthropicModel maps internal model names to Claude-style names returned in responses.
func ToAnthropicModel(model string) string {
	// Just echo back the requested model — clients expect their requested model in responses
	if model == "" {
		return "claude-3-5-sonnet-20241022"
	}
	return model
}

func anthropicMsgID() string {
	return fmt.Sprintf("msg_%s", uuid.New().String()[:12])
}
