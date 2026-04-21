// Package proxy — auto-continue: transparently stitches Qwen continuation streams.
// When Qwen signals finish_reason:"length" (output truncated), we send a follow-up
// "请继续" message to the same chat session and splice the SSE response seamlessly.
package proxy

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"strings"
)

const maxContinueRounds = 5

// ContinueFn is called to obtain the next SSE body for continuation.
// It should POST another request to Qwen using the same chat_id.
type ContinueFn func(ctx context.Context) (io.ReadCloser, error)

// WrapWithAutoContinue wraps `initial` so that when Qwen signals truncation
// (finish_reason:"length"), it automatically fetches continuation streams.
// The caller sees a single uninterrupted SSE byte stream.
// If continueFn is nil, the body is returned unchanged.
func WrapWithAutoContinue(ctx context.Context, initial io.ReadCloser, continueFn ContinueFn) io.ReadCloser {
	if continueFn == nil {
		return initial
	}
	pr, pw := io.Pipe()
	go pumpContinue(ctx, pw, initial, continueFn, maxContinueRounds)
	return pr
}

// pumpContinue drives the continuation loop in a goroutine.
func pumpContinue(ctx context.Context, pw *io.PipeWriter, first io.ReadCloser, continueFn ContinueFn, maxRounds int) {
	defer pw.Close()

	current := first
	for round := 0; ; round++ {
		truncated, err := copySSEStripping(ctx, pw, current)
		current.Close()

		if err != nil {
			if err != context.Canceled && err != context.DeadlineExceeded {
				slog.Warn("[continue] SSE copy error", "round", round, "error", err)
			}
			_ = pw.CloseWithError(err)
			return
		}

		if !truncated || round >= maxRounds {
			if truncated {
				slog.Warn("[continue] max continuation rounds reached", "limit", maxRounds)
			}
			// Emit final [DONE]
			_, _ = pw.Write([]byte("data: [DONE]\n\n"))
			return
		}

		slog.Info("[continue] response truncated, fetching continuation", "round", round+1)
		next, err := continueFn(ctx)
		if err != nil {
			slog.Warn("[continue] continuation request failed", "error", err)
			_, _ = pw.Write([]byte("data: [DONE]\n\n"))
			return
		}
		current = next
	}
}

// copySSEStripping copies SSE events from body → pw.
// Intermediate [DONE] signals are consumed (not forwarded).
// Returns truncated=true when finish_reason:"length" is observed.
func copySSEStripping(ctx context.Context, pw *io.PipeWriter, body io.ReadCloser) (truncated bool, err error) {
	scanner := bufio.NewScanner(body)
	scanner.Buffer(make([]byte, 64*1024), 2*1024*1024)

	for scanner.Scan() {
		select {
		case <-ctx.Done():
			return truncated, ctx.Err()
		default:
		}

		line := strings.TrimRight(scanner.Text(), "\r")

		if line == "" {
			// blank line separating SSE events — forward it
			if _, werr := pw.Write([]byte("\n")); werr != nil {
				return truncated, werr
			}
			continue
		}

		if strings.HasPrefix(line, "data:") {
			data := strings.TrimSpace(line[5:])
			if data == "[DONE]" {
				continue // suppress intermediate DONE; we'll emit one at the end
			}
			if isQwenTruncated(data) {
				truncated = true
				// don't forward the truncated finish event; the caller will continue
				continue
			}
		}

		// Forward the line as-is, using the `line` string (already a copy
		// from string(raw) on line 88). Never use scanner.Bytes() directly
		// for writes — the buffer can be reused by the scanner.
		if _, werr := pw.Write([]byte(line + "\n")); werr != nil {
			return truncated, werr
		}
	}
	return truncated, scanner.Err()
}

// isQwenTruncated returns true when the SSE data chunk signals truncation.
// Qwen uses finish_reason:"length" (OpenAI compat) when output was cut short.
func isQwenTruncated(data string) bool {
	var raw map[string]json.RawMessage
	if err := json.Unmarshal([]byte(data), &raw); err != nil {
		return false
	}
	choicesRaw, ok := raw["choices"]
	if !ok {
		return false
	}
	var choices []map[string]json.RawMessage
	if err := json.Unmarshal(choicesRaw, &choices); err != nil || len(choices) == 0 {
		return false
	}
	reasonRaw, ok := choices[0]["finish_reason"]
	if !ok {
		return false
	}
	var reason string
	if err := json.Unmarshal(reasonRaw, &reason); err != nil {
		return false
	}
	return reason == "length"
}

// BuildContinuePayload builds a Qwen payload for a "continue" message
// within an existing chat session (same chat_id, new user message "请继续").
func BuildContinuePayload(chatID, model string) map[string]any {
	return buildQwenMessage(chatID, model, "请继续")
}

// buildQwenMessage is a minimal Qwen payload builder for a follow-up message.
func buildQwenMessage(chatID, model, userContent string) map[string]any {
	return map[string]any{
		"stream":             true,
		"version":            "2.1",
		"incremental_output": true,
		"chat_id":            chatID,
		"chat_mode":          "normal",
		"model":              model,
		"parent_id":          nil,
		"messages": []map[string]any{
			{
				"role":    "user",
				"content": userContent,
				"files":   []any{},
				"extra":   map[string]any{"meta": map[string]any{"subChatType": "t2t"}},
			},
		},
	}
}

// BuildContinueRequest serializes the continue payload to JSON bytes.
func BuildContinueRequest(chatID, model string) ([]byte, error) {
	payload := BuildContinuePayload(chatID, model)
	b, err := json.Marshal(payload)
	if err != nil {
		return nil, fmt.Errorf("continue payload marshal: %w", err)
	}
	return b, nil
}

// NewContinueBody is a convenience that returns a fresh io.ReadCloser wrapping
// the JSON bytes, suitable for use as an http.Request body.
func NewContinueBody(chatID, model string) (io.ReadCloser, []byte, error) {
	b, err := BuildContinueRequest(chatID, model)
	if err != nil {
		return nil, nil, err
	}
	return io.NopCloser(bytes.NewReader(b)), b, nil
}
