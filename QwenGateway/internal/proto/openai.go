// Package proto implements OpenAI 鈫?Qwen request conversion and payload building.
package proto

import (
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jiujiu532/qwengateway/internal/toolcall"
)

// OpenAIRequest is the parsed OpenAI chat completions request.
type OpenAIRequest struct {
	Model    string           `json:"model"`
	Messages []OpenAIMessage  `json:"messages"`
	Stream   bool             `json:"stream"`
	Tools    []toolcall.Tool  `json:"tools,omitempty"`
}

// OpenAIMessage is a single message in the conversation.
type OpenAIMessage struct {
	Role    string `json:"role"`
	Content any    `json:"content"` // string or []ContentPart
}

// 鈹€鈹€ Model Configuration 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

// ThinkingMode controls how the Qwen model "thinks" before answering.
type ThinkingMode int

const (
	ThinkingAuto    ThinkingMode = iota // Model decides (Auto) 鈥?default for most
	ThinkingEnabled                     // Always think ("Thinking") 鈥?default for max-preview
	ThinkingOff                         // Never think ("off") 鈥?fastest, no CoT
)

// ModelConfig holds the resolved Qwen model + thinking configuration.
type ModelConfig struct {
	QwenModelID  string       // Actual model ID sent to Qwen API
	Thinking     ThinkingMode // Thinking intensity
	NoSearch     bool         // Model doesn't support search (e.g. max-preview)
	NoCodeRunner bool         // Model doesn't support code interpreter
}

// ParseModel maps any user-facing model name to a ModelConfig.
//
// Supported suffixes (case-insensitive):
//   -thinking  鈫?Always think (ThinkingEnabled)
//   -no-think  鈫?Never think (ThinkingOff)
//   (none)     鈫?Model default
//
// Examples:
//   "qwen-plus"                  鈫?qwen-plus, Auto
//   "qwen3.6-plus-thinking"      鈫?qwen-plus, Thinking
//   "qwen-max-no-think"          鈫?qwen-max, off
//   "qwen3.6-max-preview"        鈫?qwen3.6-max-preview, Thinking (browser-verified)
//   "qwen3.6-max-preview-no-think" 鈫?qwen3.6-max-preview, off
func ParseModel(model string) ModelConfig {
	lower := strings.ToLower(strings.TrimSpace(model))

	// 鈹€鈹€ Step 1: extract thinking suffix 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
	var thinkOverride *ThinkingMode
	setThink := func(m ThinkingMode) { thinkOverride = &m }

	switch {
	case strings.HasSuffix(lower, "-thinking"):
		setThink(ThinkingEnabled)
		lower = strings.TrimSuffix(lower, "-thinking")
	case strings.HasSuffix(lower, "-no-think"), strings.HasSuffix(lower, "-nothink"):
		setThink(ThinkingOff)
		lower = strings.TrimSuffix(strings.TrimSuffix(lower, "-no-think"), "-nothink")
	}

	// 鈹€鈹€ Step 2: map base model 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
	var cfg ModelConfig
	switch {
	case strings.Contains(lower, "max-preview"):
		cfg = ModelConfig{
			QwenModelID:  "qwen3.6-max-preview",
			Thinking:     ThinkingEnabled, // browser-verified default
			NoSearch:     true,
			NoCodeRunner: true,
		}
	case strings.Contains(lower, "3.5-plus"), strings.Contains(lower, "3-5-plus"):
		cfg = ModelConfig{QwenModelID: "qwen3.5-plus", Thinking: ThinkingAuto, NoSearch: true, NoCodeRunner: true}
	case strings.Contains(lower, "3.6-plus"), strings.Contains(lower, "3-6-plus"), strings.Contains(lower, "plus"):
		cfg = ModelConfig{QwenModelID: "qwen3.6-plus", Thinking: ThinkingAuto, NoSearch: true, NoCodeRunner: true}
	case strings.Contains(lower, "max"):
		cfg = ModelConfig{QwenModelID: "qwen-max", Thinking: ThinkingAuto, NoSearch: true, NoCodeRunner: true}
	case strings.Contains(lower, "turbo"):
		cfg = ModelConfig{QwenModelID: "qwen-turbo", Thinking: ThinkingOff, NoSearch: true, NoCodeRunner: true}
	case strings.Contains(lower, "long"):
		cfg = ModelConfig{QwenModelID: "qwen-long", Thinking: ThinkingOff, NoSearch: true, NoCodeRunner: true}
	case strings.Contains(lower, "vl"), strings.Contains(lower, "vision"):
		cfg = ModelConfig{QwenModelID: "qwen-vl-plus", Thinking: ThinkingOff, NoSearch: true, NoCodeRunner: true}
	default:
		cfg = ModelConfig{QwenModelID: "qwen3.6-plus", Thinking: ThinkingAuto, NoSearch: true, NoCodeRunner: true}
	}

	// 鈹€鈹€ Step 3: apply suffix override if present 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
	if thinkOverride != nil {
		cfg.Thinking = *thinkOverride
	}

	return cfg
}

// ToQwenModel is a legacy helper that returns only the model ID.
// Prefer ParseModel for new code.
func ToQwenModel(model string) string {
	return ParseModel(model).QwenModelID
}

// BuildQwenPayload constructs the Qwen /api/v2/chat/completions payload.
func BuildQwenPayload(chatID string, cfg ModelConfig, content string, hasTools bool, enableNativeFC bool) map[string]any {
	ts := time.Now().Unix()

	// Resolve thinking settings 鈥?tools always disable thinking
	thinking := cfg.Thinking
	if hasTools {
		thinking = ThinkingOff
	}

	var thinkEnabled bool
	var thinkMode string
	var autoThink bool

	switch thinking {
	case ThinkingEnabled:
		thinkEnabled = true
		thinkMode = "Thinking"
		autoThink = false
	case ThinkingOff:
		thinkEnabled = false
		thinkMode = "off"
		autoThink = false
	default: // ThinkingAuto
		thinkEnabled = true
		thinkMode = "Auto"
		autoThink = true
	}

	featureCfg := map[string]any{
		"thinking_enabled": thinkEnabled,
		"research_mode":    "normal",
		"auto_thinking":    autoThink,
		"thinking_mode":    thinkMode,
		"auto_search":      !hasTools && !cfg.NoSearch,
		"code_interpreter": !hasTools && !cfg.NoCodeRunner,
		"function_calling": enableNativeFC,
		"plugins_enabled":  !hasTools && !cfg.NoSearch,
	}
	// thinking_format:"summary" is used in Thinking mode (from browser capture)
	if thinking == ThinkingEnabled {
		featureCfg["thinking_format"] = "summary"
	}

	return map[string]any{
		"stream":             true,
		"version":            "2.1",
		"incremental_output": true,
		"chat_id":            chatID,
		"chat_mode":          "normal",
		"model":              cfg.QwenModelID,
		"parent_id":          nil,
		"messages": []map[string]any{
			{
				"fid":          uuid.New().String(),
				"parentId":     nil,
				"childrenIds":  []string{uuid.New().String()},
				"role":         "user",
				"content":      content,
				"user_action":  "chat",
				"files":        []any{},
				"timestamp":    ts,
				"models":       []string{cfg.QwenModelID},
				"chat_type":    "t2t",
				"feature_config": featureCfg,
				"extra":        map[string]any{"meta": map[string]any{"subChatType": "t2t"}},
				"sub_chat_type": "t2t",
				"parent_id":    nil,
			},
		},
		"timestamp": ts,
	}
}

// MessagesToContent flattens OpenAI messages into a single string for Qwen.
// If tools are present, prepends the tool system prompt.
func MessagesToContent(req OpenAIRequest) (string, error) {
	var parts []string

	// Prepend tool system prompt if tools are defined
	if len(req.Tools) > 0 {
		toolPrompt := toolcall.BuildSystemPrompt(req.Tools)
		if toolPrompt != "" {
			parts = append(parts, "[SYSTEM]\n"+toolPrompt)
		}
	}

	for _, msg := range req.Messages {
		text, err := extractMessageText(msg)
		if err != nil {
			return "", err
		}
		switch msg.Role {
		case "system":
			parts = append(parts, "[SYSTEM]\n"+text)
		case "user":
			parts = append(parts, "[USER]\n"+text)
		case "assistant":
			parts = append(parts, "[ASSISTANT]\n"+text)
		case "tool":
			parts = append(parts, "[TOOL_RESULT]\n"+text)
		default:
			parts = append(parts, text)
		}
	}
	return strings.Join(parts, "\n\n"), nil
}

func extractMessageText(msg OpenAIMessage) (string, error) {
	switch v := msg.Content.(type) {
	case string:
		return v, nil
	case []any:
		// Multi-part content (text + image)
		var texts []string
		for _, part := range v {
			if p, ok := part.(map[string]any); ok {
				if p["type"] == "text" {
					if t, ok := p["text"].(string); ok {
						texts = append(texts, t)
					}
				}
			}
		}
		return strings.Join(texts, "\n"), nil
	case nil:
		return "", nil
	default:
		b, err := json.Marshal(v)
		if err != nil {
			return "", fmt.Errorf("cannot marshal message content: %w", err)
		}
		return string(b), nil
	}
}
