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
// Properly handles multi-turn tool conversations:
//   - tool_use blocks in assistant messages → OpenAIMessage with ToolCalls
//   - tool_result blocks in user messages → OpenAIMessage{Role:"tool"} with ToolCallID
func AnthropicToOpenAI(req AnthropicRequest) OpenAIRequest {
	var messages []OpenAIMessage

	// Inject system message if present (can be string or array of content blocks).
	if req.System != nil {
		systemText := flattenContentToText(req.System)
		if systemText != "" {
			messages = append(messages, OpenAIMessage{Role: "system", Content: systemText})
		}
	}

	for _, m := range req.Messages {
		switch m.Role {
		case "assistant":
			// Check if this assistant message contains tool_use blocks.
			msgs := expandAssistantMessage(m)
			messages = append(messages, msgs...)
		case "user":
			// Check if this user message contains tool_result blocks.
			msgs := expandUserMessage(m)
			messages = append(messages, msgs...)
		default:
			text := flattenContentToText(m.Content)
			messages = append(messages, OpenAIMessage{Role: m.Role, Content: text})
		}
	}

	return OpenAIRequest{
		Model:    req.Model,
		Messages: messages,
		Stream:   req.Stream,
		Tools:    req.GetTools(),
	}
}

// expandAssistantMessage handles assistant messages with potential tool_use blocks.
// tool_use → OpenAIToolCall; regular text → Content string.
func expandAssistantMessage(m AnthropicMessage) []OpenAIMessage {
	blocks, ok := toContentBlocks(m.Content)
	if !ok {
		// Plain string content.
		return []OpenAIMessage{{Role: "assistant", Content: flattenContentToText(m.Content)}}
	}

	var textParts []string
	var toolCalls []openAIToolCallRaw

	for _, b := range blocks {
		blockType, _ := b["type"].(string)
		switch blockType {
		case "text":
			if t, ok := b["text"].(string); ok && strings.TrimSpace(t) != "" {
				textParts = append(textParts, t)
			}
		case "tool_use":
			name, _ := b["name"].(string)
			id, _ := b["id"].(string)
			if id == "" {
				id = "call_" + uuid.New().String()[:8]
			}
			inputBytes, _ := json.Marshal(b["input"])
			toolCalls = append(toolCalls, openAIToolCallRaw{
				ID:        id,
				Type:      "function",
				FuncName:  name,
				Arguments: string(inputBytes),
			})
		}
	}

	var out []OpenAIMessage
	// Text part first (if any).
	textContent := strings.Join(textParts, "\n")
	if len(toolCalls) > 0 {
		// Build the assistant message with tool_calls.
		calls := make([]toolcall.OpenAIToolCall, 0, len(toolCalls))
		for _, tc := range toolCalls {
			calls = append(calls, toolcall.OpenAIToolCall{
				ID:   tc.ID,
				Type: "function",
				Function: toolcall.OpenAIFunctionCall{
					Name:      tc.FuncName,
					Arguments: tc.Arguments,
				},
			})
		}
		out = append(out, OpenAIMessage{
			Role:      "assistant",
			Content:   textContent,
			ToolCalls: calls,
		})
	} else {
		if textContent == "" {
			textContent = " " // prevent empty assistant messages
		}
		out = append(out, OpenAIMessage{Role: "assistant", Content: textContent})
	}
	return out
}

// expandUserMessage handles user messages that may contain tool_result blocks.
// tool_result blocks become role:tool messages (preserving tool_use_id).
// Regular text blocks become a single user message.
func expandUserMessage(m AnthropicMessage) []OpenAIMessage {
	blocks, ok := toContentBlocks(m.Content)
	if !ok {
		return []OpenAIMessage{{Role: "user", Content: flattenContentToText(m.Content)}}
	}

	var out []OpenAIMessage
	var userTextParts []string

	for _, b := range blocks {
		blockType, _ := b["type"].(string)
		switch blockType {
		case "tool_result":
			// tool_result → role:tool message preserving tool_use_id.
			toolUseID, _ := b["tool_use_id"].(string)
			resultText := extractToolResultContent(b["content"])
			out = append(out, OpenAIMessage{
				Role:       "tool",
				Content:    resultText,
				ToolCallID: toolUseID,
			})
		case "text":
			if t, ok := b["text"].(string); ok && strings.TrimSpace(t) != "" {
				userTextParts = append(userTextParts, t)
			}
		default:
			// Other block types: try to extract text.
			if t, ok := b["text"].(string); ok && t != "" {
				userTextParts = append(userTextParts, t)
			}
		}
	}

	// Prepend any regular user text.
	if len(userTextParts) > 0 {
		out = append([]OpenAIMessage{{Role: "user", Content: strings.Join(userTextParts, "\n")}}, out...)
	}
	if len(out) == 0 {
		out = append(out, OpenAIMessage{Role: "user", Content: flattenContentToText(m.Content)})
	}
	return out
}

// toContentBlocks tries to interpret content as a []map[string]any block list.
func toContentBlocks(content any) ([]map[string]any, bool) {
	arr, ok := content.([]any)
	if !ok {
		return nil, false
	}
	var blocks []map[string]any
	for _, item := range arr {
		if b, ok := item.(map[string]any); ok {
			blocks = append(blocks, b)
		}
	}
	return blocks, len(blocks) > 0
}

// extractToolResultContent extracts text from a tool_result's content field.
func extractToolResultContent(content any) string {
	switch tc := content.(type) {
	case string:
		return tc
	case []any:
		var parts []string
		for _, item := range tc {
			if m, ok := item.(map[string]any); ok {
				if t, ok := m["text"].(string); ok {
					parts = append(parts, t)
				}
			}
		}
		return strings.Join(parts, "\n")
	default:
		b, _ := json.Marshal(content)
		return string(b)
	}
}

// flattenContentToText converts any content type to a plain string.
// Used for system messages and simple user/assistant messages.
func flattenContentToText(content any) string {
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
					text := extractToolResultContent(b["content"])
					if text != "" {
						parts = append(parts, "[Tool Result: "+text+"]")
					}
				case "tool_use":
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

// openAIToolCallRaw is a temporary struct for building tool call arrays.
type openAIToolCallRaw struct {
	ID        string
	Type      string
	FuncName  string
	Arguments string
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

// EstimateInputTokens estimates the number of input tokens from messages.
func EstimateInputTokens(messages []OpenAIMessage) int {
	total := 0
	for _, m := range messages {
		total += len([]rune(m.Content)) / 4
		for _, tc := range m.ToolCalls {
			total += len([]rune(tc.Function.Arguments)) / 4
		}
	}
	if total < 1 {
		total = 1
	}
	return total
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
