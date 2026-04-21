// Package proxy implements SSE zero-copy proxying from Qwen upstream to the client.

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

	"unicode/utf8"



	"github.com/jiujiu532/qwengateway/internal/toolcall"

)



// StreamResult is the outcome of a full SSE stream.

type StreamResult struct {

	FullText  string

	ToolCalls []toolcall.OpenAIToolCall

	Done      bool

}



// StreamSSE reads the upstream Qwen SSE body and writes OpenAI-compatible SSE events

// to w in real-time. For tool calls, it buffers the full response and parses at the end.

// Accepts an io.ReadCloser so it works with both *http.Response and *fhttp.Response.

func StreamSSE(

	w http.ResponseWriter,

	body io.ReadCloser,

	statusCode int,

	requestID string,

	model string,

	tools []toolcall.Tool,

) StreamResult {

	defer body.Close()



	if statusCode != http.StatusOK {

		b, _ := io.ReadAll(body)

		slog.Warn("[sse] upstream error", "status", statusCode, "body", string(b)[:min(200, len(b))])

		http.Error(w, "upstream error", statusCode)

		return StreamResult{}

	}



	w.Header().Set("Content-Type", "text/event-stream")

	w.Header().Set("Cache-Control", "no-cache, no-transform")

	w.Header().Set("Connection", "keep-alive")

	w.Header().Set("X-Accel-Buffering", "no")



	flusher, canFlush := w.(http.Flusher)

	hasTools := len(tools) > 0



	scanner := bufio.NewScanner(body)

	scanner.Buffer(make([]byte, 64*1024), 512*1024)



	var fullTextBuf strings.Builder

	created := time.Now().Unix()



	writeChunk := func(content string) {
		if content == "" {
			return
		}
		// Emit one SSE event per rune for Cherry Studio compatibility.
		// AiSdkToChunkAdapter misbehaves when receiving multi-char chunks.
		// marshalASCIISafe ensures each event is pure ASCII (no UTF-8 split risk).
		for _, r := range content {
			ch := buildOpenAIChunk(requestID, model, string(r), created)
			data, _ := marshalASCIISafe(ch)
			fmt.Fprintf(w, "data: %s\n\n", data)
		}
		if canFlush {
			flusher.Flush()
		}
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



		if !hasTools {

			writeChunk(content)

		}

	}



	if err := scanner.Err(); err != nil && err != io.EOF {

		slog.Warn("[sse] scanner error", "error", err)

	}



	fullText := fullTextBuf.String()

	result := StreamResult{FullText: fullText, Done: true}



	if hasTools {

		parseResult := toolcall.Parse(fullText)

		if parseResult.SawToolCallSyntax && len(parseResult.Calls) > 0 {

			result.ToolCalls = toolcall.FormatAsOpenAI(parseResult.Calls)

			// Send tool call delta chunk

			chunk := buildToolCallChunk(requestID, model, result.ToolCalls, created)

			data, _ := marshalASCIISafe(chunk)

			fmt.Fprintf(w, "data: %s\n\n", data)

			if canFlush {

				flusher.Flush()

			}

		} else {

			// No tool calls â€?stream the buffered text in chunks

			for i := 0; i < len(fullText); i += 32 {

				end := i + 32

				if end > len(fullText) {

					end = len(fullText)

				}

				writeChunk(fullText[i:end])

			}

		}

	}



	// Send [DONE]

	fmt.Fprintf(w, "data: [DONE]\n\n")

	if canFlush {

		flusher.Flush()

	}

	return result

}



func extractContent(raw map[string]any) string {

	if choices, ok := raw["choices"].([]any); ok && len(choices) > 0 {

		if c, ok := choices[0].(map[string]any); ok {

			if delta, ok := c["delta"].(map[string]any); ok {

				if content, ok := delta["content"].(string); ok {

					return content

				}

			}

		}

	}

	if content, ok := raw["content"].(string); ok {

		return content

	}

	if text, ok := raw["text"].(string); ok {

		return text

	}

	return ""

}



func buildOpenAIChunk(id, model, content string, created int64) map[string]any {

	return map[string]any{

		"id":      id,

		"object":  "chat.completion.chunk",

		"created": created,

		"model":   model,

		"choices": []map[string]any{{

			"index":         0,

			"delta":         map[string]any{"role": "assistant", "content": content},

			"finish_reason": nil,

		}},

	}

}



func buildToolCallChunk(id, model string, calls []toolcall.OpenAIToolCall, created int64) map[string]any {

	return map[string]any{

		"id":      id,

		"object":  "chat.completion.chunk",

		"created": created,

		"model":   model,

		"choices": []map[string]any{{

			"index":         0,

			"delta":         map[string]any{"role": "assistant", "content": nil, "tool_calls": calls},

			"finish_reason": "tool_calls",

		}},

	}

}



func min(a, b int) int {

	if a < b {

		return a

	}

	return b

}



// marshalASCIISafe produces JSON where all non-ASCII runes are \uXXXX escaped.

// This prevents garbled characters when SSE clients split HTTP chunks mid-UTF-8.

func marshalASCIISafe(v any) ([]byte, error) {

	data, err := json.Marshal(v)

	if err != nil {

		return nil, err

	}

	// Fast path: if all bytes are ASCII, return as-is

	allASCII := true

	for _, b := range data {

		if b > 127 {

			allASCII = false

			break

		}

	}

	if allASCII {

		return data, nil

	}

	// Slow path: re-encode with unicode escaping

	var buf strings.Builder

	buf.Grow(len(data) + len(data)/4)

	for i := 0; i < len(data); {

		b := data[i]

		if b <= 127 {

			buf.WriteByte(b)

			i++

			continue

		}

		// Decode UTF-8 rune

		r, size := utf8.DecodeRune(data[i:])

		if r == utf8.RuneError {

			i++

			continue

		}

		if r <= 0xFFFF {

			fmt.Fprintf(&buf, "\\u%04x", r)

		} else {

			// Surrogate pair for non-BMP characters

			r -= 0x10000

			hi := 0xD800 + (r>>10)&0x3FF

			lo := 0xDC00 + r&0x3FF

			fmt.Fprintf(&buf, "\\u%04x\\u%04x", hi, lo)

		}

		i += size

	}

	return []byte(buf.String()), nil

}

