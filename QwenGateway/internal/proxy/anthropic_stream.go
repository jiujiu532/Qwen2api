// Package proxy — Anthropic (Claude) real-time SSE streaming.
//
// AnthropicStreamToClient converts Qwen SSE → Claude SSE events in real-time,
// flushing each token immediately instead of buffering everything first.
//
// Strategy (mirrors ds2api's claudeStreamRuntime):
//   - Without tools: emit content_block_delta per token immediately.
//   - With tools:    buffer full text, then on stream end parse XML tool calls
//     and emit tool_use blocks.

package proxy

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jiujiu532/qwengateway/internal/toolcall"
)

// AnthropicStreamToClient pipes Qwen SSE → Claude-compatible SSE in real-time.
// msgID should already be a "msg_..." string. messages is the original request
// messages slice used for estimating input_tokens.
func AnthropicStreamToClient(
	w http.ResponseWriter,
	body io.ReadCloser,
	statusCode int,
	msgID string,
	model string,
	tools []toolcall.Tool,
	inputTokenEst int,
) {
	defer body.Close()

	if statusCode != http.StatusOK {
		b, _ := io.ReadAll(body)
		slog.Warn("[anthropic_stream] upstream error", "status", statusCode, "body", string(b)[:min(200, len(b))])
		writeClaudeSSEError(w, "upstream error "+fmt.Sprint(statusCode))
		return
	}

	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache, no-transform")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("X-Accel-Buffering", "no")

	flusher, canFlush := w.(http.Flusher)

	hasTools := len(tools) > 0

	// ── message_start ──────────────────────────────────────────────────────────
	sendClaudeSSEEvent(w, flusher, canFlush, "message_start", map[string]any{
		"type": "message_start",
		"message": map[string]any{
			"id":             msgID,
			"type":           "message",
			"role":           "assistant",
			"model":          model,
			"content":        []any{},
			"stop_reason":    nil,
			"stop_sequence":  nil,
			"usage":          map[string]any{"input_tokens": inputTokenEst, "output_tokens": 0},
		},
	})

	// ── stream body ────────────────────────────────────────────────────────────
	scanner := bufio.NewScanner(body)
	scanner.Buffer(make([]byte, 64*1024), 512*1024)

	var fullTextBuf strings.Builder
	textBlockOpen := false
	textBlockIndex := 0

	// openTextBlock emits content_block_start for text (idempotent).
	openTextBlock := func() {
		if textBlockOpen {
			return
		}
		sendClaudeSSEEvent(w, flusher, canFlush, "content_block_start", map[string]any{
			"type":  "content_block_start",
			"index": textBlockIndex,
			"content_block": map[string]any{
				"type": "text",
				"text": "",
			},
		})
		textBlockOpen = true
	}

	// closeTextBlock emits content_block_stop.
	closeTextBlock := func() {
		if !textBlockOpen {
			return
		}
		sendClaudeSSEEvent(w, flusher, canFlush, "content_block_stop", map[string]any{
			"type":  "content_block_stop",
			"index": textBlockIndex,
		})
		textBlockOpen = false
	}

	for scanner.Scan() {
		line := scanner.Text()
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

		content := extractContent(raw)
		if content == "" {
			continue
		}

		fullTextBuf.WriteString(content)

		// When no tools: stream each token immediately as Claude SSE.
		if !hasTools {
			openTextBlock()
			sendClaudeSSEEvent(w, flusher, canFlush, "content_block_delta", map[string]any{
				"type":  "content_block_delta",
				"index": textBlockIndex,
				"delta": map[string]any{
					"type": "text_delta",
					"text": content,
				},
			})
		}
		// When tools: buffer silently (hasUnclosedCodeFence check is optional here).
	}

	if err := scanner.Err(); err != nil && err != io.EOF {
		slog.Warn("[anthropic_stream] scanner error", "error", err)
	}

	fullText := fullTextBuf.String()
	outputTokenEst := len([]rune(fullText)) / 4

	// ── finalize ───────────────────────────────────────────────────────────────
	if hasTools {
		// Parse XML tool calls from buffered text.
		parseResult := toolcall.Parse(fullText)

		if parseResult.SawToolCallSyntax && len(parseResult.Calls) > 0 {
			// Emit one tool_use block per detected call.
			nextBlock := textBlockIndex
			for i, tc := range parseResult.Calls {
				idx := nextBlock + i
				toolID := fmt.Sprintf("toolu_%s", uuid.New().String()[:8])
				inputBytes, _ := json.Marshal(tc.Input)

				sendClaudeSSEEvent(w, flusher, canFlush, "content_block_start", map[string]any{
					"type":  "content_block_start",
					"index": idx,
					"content_block": map[string]any{
						"type":  "tool_use",
						"id":    toolID,
						"name":  tc.Name,
						"input": map[string]any{},
					},
				})
				sendClaudeSSEEvent(w, flusher, canFlush, "content_block_delta", map[string]any{
					"type":  "content_block_delta",
					"index": idx,
					"delta": map[string]any{
						"type":         "input_json_delta",
						"partial_json": string(inputBytes),
					},
				})
				sendClaudeSSEEvent(w, flusher, canFlush, "content_block_stop", map[string]any{
					"type":  "content_block_stop",
					"index": idx,
				})
			}

			// End with tool_use stop reason.
			sendClaudeSSEEvent(w, flusher, canFlush, "message_delta", map[string]any{
				"type":  "message_delta",
				"delta": map[string]any{"stop_reason": "tool_use", "stop_sequence": nil},
				"usage": map[string]any{"output_tokens": outputTokenEst},
			})
		} else {
			// No tool calls detected — emit buffered text as a normal text block.
			if strings.TrimSpace(fullText) != "" {
				openTextBlock()
				sendClaudeSSEEvent(w, flusher, canFlush, "content_block_delta", map[string]any{
					"type":  "content_block_delta",
					"index": textBlockIndex,
					"delta": map[string]any{
						"type": "text_delta",
						"text": fullText,
					},
				})
			}
			closeTextBlock()
			sendClaudeSSEEvent(w, flusher, canFlush, "message_delta", map[string]any{
				"type":  "message_delta",
				"delta": map[string]any{"stop_reason": "end_turn", "stop_sequence": nil},
				"usage": map[string]any{"output_tokens": outputTokenEst},
			})
		}
	} else {
		closeTextBlock()
		sendClaudeSSEEvent(w, flusher, canFlush, "message_delta", map[string]any{
			"type":  "message_delta",
			"delta": map[string]any{"stop_reason": "end_turn", "stop_sequence": nil},
			"usage": map[string]any{"output_tokens": outputTokenEst},
		})
	}

	sendClaudeSSEEvent(w, flusher, canFlush, "message_stop", map[string]any{"type": "message_stop"})
}

// sendClaudeSSEEvent writes a single Claude-format SSE event and flushes.
func sendClaudeSSEEvent(w http.ResponseWriter, flusher http.Flusher, canFlush bool, event string, v any) {
	b, _ := json.Marshal(v)
	fmt.Fprintf(w, "event: %s\ndata: %s\n\n", event, string(b))
	if canFlush {
		flusher.Flush()
	}
}

// writeClaudeSSEError emits a Claude-format SSE error event.
func writeClaudeSSEError(w http.ResponseWriter, message string) {
	w.Header().Set("Content-Type", "text/event-stream")
	payload, _ := json.Marshal(map[string]any{
		"type":  "error",
		"error": map[string]any{"type": "api_error", "message": message},
	})
	fmt.Fprintf(w, "event: error\ndata: %s\n\n", string(payload))
	if f, ok := w.(http.Flusher); ok {
		f.Flush()
	}
}

// extractToolNames extracts just the tool function names from a tools slice.
func extractToolNames(tools []toolcall.Tool) []string {
	names := make([]string, 0, len(tools))
	for _, t := range tools {
		if t.Function.Name != "" {
			names = append(names, t.Function.Name)
		}
	}
	return names
}

// estimateTokens estimates tokens from a slice of messages for input_tokens reporting.
func estimateTokens(messages []string) int {
	total := 0
	for _, m := range messages {
		total += len([]rune(m)) / 4
	}
	if total < 1 {
		total = 1
	}
	return total
}

// estTokensFromInt returns a non-zero token estimate.
func estTokensFromInt(chars int) int {
	t := chars / 4
	if t < 1 {
		t = 1
	}
	return t
}

// Keep time import used (created variable in future expansion).
var _ = time.Now
