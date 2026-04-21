// Package racing implements parallel request racing: N goroutines compete,
// the first valid SSE response wins; the rest are cancelled.
package racing

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"strings"
	"time"


	fhttp "github.com/bogdanfinn/fhttp"
	"github.com/jiujiu532/qwengateway/internal/pool"
	tlsclient "github.com/jiujiu532/qwengateway/internal/tls"
)

// Winner holds the winning account, its response, and the chat session ID.
type Winner struct {
	Account   *pool.Account
	Resp      *fhttp.Response
	SessionID string
	LatencyMs int64
	Cancel    context.CancelFunc // must be called by the caller after streaming is done
}

// Race sends the same payload to N accounts simultaneously via tls-client.
// The first account to return a valid 200 SSE stream wins.
// All losers are context-cancelled immediately.
func Race(
	ctx context.Context,
	accounts []*pool.Account,
	model string,
	payload map[string]any,
	sessionFn func(context.Context, *pool.Account) (string, error),
) (*Winner, error) {
	if len(accounts) == 0 {
		return nil, fmt.Errorf("no accounts available for racing")
	}

	ch := make(chan *Winner, 1)
	cancelCtx, cancel := context.WithCancel(ctx)
	// NOTE: do NOT defer cancel() here — the Winner carries the cancel func
	// so the caller can cancel AFTER streaming is complete.
	// cancel() is only called on race failure to prevent goroutine leaks.

	for _, acc := range accounts {
		go func(a *pool.Account) {
			start := time.Now()

			sessionID, err := sessionFn(cancelCtx, a)
			if err != nil {
				slog.Debug("[race] acquire session failed", "email", a.Email, "error", err)
				return
			}

			p := clonePayload(payload)
			p["chat_id"] = sessionID

			bodyBytes, _ := json.Marshal(p)

			// Reuse pooled TLS client — zero-alloc on hot path
			client, release := tlsclient.AcquireClient()
			defer release()

			headers := tlsclient.BaseHeaders(a.Token)
			headers["Content-Type"] = "application/json"
			headers["Accept"] = "text/event-stream"

			url := fmt.Sprintf("%s/api/v2/chat/completions?chat_id=%s", tlsclient.BaseURL, sessionID)
			req, err := fhttp.NewRequestWithContext(cancelCtx, "POST", url, bytes.NewReader(bodyBytes))
			if err != nil {
				return
			}
			for k, v := range headers {
				req.Header.Set(k, v)
			}

			resp, err := client.Do(req)
			if err != nil {
				if cancelCtx.Err() != nil {
					return // lost the race
				}
				// ── Fallback to standard http.Client ──────────────────────────
				slog.Debug("[race] fingerprint client failed, trying fallback", "email", a.Email, "error", err)
				req2, _ := http.NewRequestWithContext(cancelCtx, "POST", url, bytes.NewReader(bodyBytes))
				if req2 != nil {
					for k, v := range headers {
						req2.Header.Set(k, v)
					}
					resp2, err2 := tlsclient.FallbackClient().Do(req2)
					if err2 == nil {
						resp = (*fhttp.Response)(nil)
						// convert net/http.Response to fhttp.Response via body pipe
						pr, pw := io.Pipe()
						go func() { defer pw.Close(); _, _ = io.Copy(pw, resp2.Body); resp2.Body.Close() }()
						fakeresp := &fhttp.Response{
							StatusCode: resp2.StatusCode,
							Body:       io.NopCloser(pr),
						}
						resp = fakeresp
						err = nil
					}
				}
				if err != nil {
					a.GetBreaker().OnFail()
					slog.Debug("[race] request error (both transports failed)", "email", a.Email, "error", err)
					return
				}
			}

			if resp.StatusCode != 200 {
				resp.Body.Close()
				a.GetBreaker().OnFail()
				slog.Debug("[race] bad status", "email", a.Email, "status", resp.StatusCode)
				return
			}

			// Peek at the SSE stream to confirm data is flowing.
			// Qwen sometimes sends blank lines or ": keepalive" comment lines
			// before the first real data event. Skip those rather than rejecting
			// the candidate, which was causing spurious 0-token race failures.
			peek := bufio.NewReader(resp.Body)
			var firstDataLine string
			const maxSkip = 8 // cap how many non-data lines we'll skip
			found := false
			for i := 0; i < maxSkip; i++ {
				line, _, peekErr := peek.ReadLine()
				if peekErr != nil {
					break
				}
				trimmed := strings.TrimSpace(string(line))
				if trimmed == "" || strings.HasPrefix(trimmed, ":") {
					// blank line or SSE comment — keep reading
					continue
				}
				if strings.HasPrefix(trimmed, "data:") {
					firstDataLine = string(line)
					found = true
					break
				}
				// unexpected non-data content — reject
				break
			}
			if !found {
				resp.Body.Close()
				return
			}
			// Reconstruct the body: prepend the buffered first line back so
			// downstream processing sees a complete SSE stream.
			combined := io.MultiReader(
				strings.NewReader(firstDataLine+"\n"),
				peek,
			)
			resp.Body = io.NopCloser(combined)

			elapsed := time.Since(start).Milliseconds()
			select {
			case ch <- &Winner{Account: a, Resp: resp, SessionID: sessionID, LatencyMs: elapsed}:
				// Do NOT call cancel() here — that kills our own response body.
				// winner.Cancel() is called by handleChatRequest after streaming.
			default:
				resp.Body.Close() // lost the race but request already out
			}
		}(acc)
	}

	select {
	case w := <-ch:
		w.Cancel = cancel // hand off cancel to the caller
		return w, nil
	case <-ctx.Done():
		cancel() // clean up racing goroutines on failure
		return nil, fmt.Errorf("race: all attempts failed or context cancelled")
	}
}

func clonePayload(src map[string]any) map[string]any {
	out := make(map[string]any, len(src))
	for k, v := range src {
		out[k] = v
	}
	return out
}
