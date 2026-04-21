package proto

import (
	"encoding/json"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jiujiu532/qwengateway/internal/toolcall"
)

// GeminiRequest is the Google Gemini generateContent request.
type GeminiRequest struct {
	Contents         []GeminiContent  `json:"contents"`
	SystemInstruction *GeminiContent  `json:"systemInstruction,omitempty"`
	Tools            []GeminiTool     `json:"tools,omitempty"`
	GenerationConfig *GeminiGenConfig `json:"generationConfig,omitempty"`
}

// GeminiContent is one conversation turn.
type GeminiContent struct {
	Role  string       `json:"role"`
	Parts []GeminiPart `json:"parts"`
}

// GeminiPart holds the text of one content part.
type GeminiPart struct {
	Text string `json:"text"`
}

// GeminiTool wraps function declarations.
type GeminiTool struct {
	FunctionDeclarations []GeminiFunctionDecl `json:"function_declarations"`
}

// GeminiFunctionDecl is a single function declaration.
type GeminiFunctionDecl struct {
	Name        string         `json:"name"`
	Description string         `json:"description"`
	Parameters  map[string]any `json:"parameters"`
}

// GeminiGenConfig holds generation parameters.
type GeminiGenConfig struct {
	Temperature     float64 `json:"temperature,omitempty"`
	MaxOutputTokens int     `json:"maxOutputTokens,omitempty"`
}

// GeminiToOpenAI converts a Gemini generateContent request to OpenAI format.
func GeminiToOpenAI(req GeminiRequest) OpenAIRequest {
	var messages []OpenAIMessage

	if req.SystemInstruction != nil {
		sys := extractGeminiText(req.SystemInstruction.Parts)
		if sys != "" {
			messages = append(messages, OpenAIMessage{Role: "system", Content: sys})
		}
	}

	for _, c := range req.Contents {
		role := c.Role
		if role == "model" {
			role = "assistant"
		}
		text := extractGeminiText(c.Parts)
		messages = append(messages, OpenAIMessage{Role: role, Content: text})
	}

	var tools []toolcall.Tool
	for _, gt := range req.Tools {
		for _, fn := range gt.FunctionDeclarations {
			tools = append(tools, toolcall.Tool{
				Type: "function",
				Function: toolcall.ToolFunc{
					Name:        fn.Name,
					Description: fn.Description,
					Parameters:  fn.Parameters,
				},
			})
		}
	}

	return OpenAIRequest{
		Model:    "qwen-plus",
		Messages: messages,
		Stream:   true,
		Tools:    tools,
	}
}

func extractGeminiText(parts []GeminiPart) string {
	var texts []string
	for _, p := range parts {
		if p.Text != "" {
			texts = append(texts, p.Text)
		}
	}
	return strings.Join(texts, "\n")
}

// BuildGeminiStreamChunk builds a Gemini-compatible streaming chunk.
func BuildGeminiStreamChunk(model, text string, done bool) map[string]any {
	finishReason := ""
	if done {
		finishReason = "STOP"
	}
	return map[string]any{
		"candidates": []map[string]any{{
			"content": map[string]any{
				"role":  "model",
				"parts": []map[string]any{{"text": text}},
			},
			"finishReason": finishReason,
			"index":        0,
		}},
		"usageMetadata": map[string]any{
			"promptTokenCount":     0,
			"candidatesTokenCount": len(text) / 4,
			"totalTokenCount":      len(text) / 4,
		},
		"modelVersion": model,
	}
}

// BuildGeminiToolCallResponse builds a Gemini-compatible function call response.
func BuildGeminiToolCallResponse(model string, calls []toolcall.OpenAIToolCall) map[string]any {
	parts := make([]map[string]any, 0, len(calls))
	for _, c := range calls {
		var args map[string]any
		_ = json.Unmarshal([]byte(c.Function.Arguments), &args)
		parts = append(parts, map[string]any{
			"functionCall": map[string]any{
				"name": c.Function.Name,
				"args": args,
			},
		})
	}
	return map[string]any{
		"candidates": []map[string]any{{
			"content":      map[string]any{"role": "model", "parts": parts},
			"finishReason": "STOP",
			"index":        0,
		}},
		"usageMetadata": map[string]any{"promptTokenCount": 0, "candidatesTokenCount": 0},
		"modelVersion":  model,
	}
}

// BuildGeminiTextResponse builds a non-streaming Gemini text response.
func BuildGeminiTextResponse(model, text string) map[string]any {
	return map[string]any{
		"candidates": []map[string]any{{
			"content": map[string]any{
				"role":  "model",
				"parts": []map[string]any{{"text": text}},
			},
			"finishReason": "STOP",
			"index":        0,
		}},
		"usageMetadata": map[string]any{
			"promptTokenCount":     0,
			"candidatesTokenCount": len(text) / 4,
			"totalTokenCount":      len(text) / 4,
		},
		"modelVersion": model,
		"createTime":   time.Now().Format(time.RFC3339),
		"responseId":   uuid.New().String(),
	}
}
