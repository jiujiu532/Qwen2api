package pool

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"time"

	fhttp "github.com/bogdanfinn/fhttp"
	tlsclient "github.com/jiujiu532/qwengateway/internal/tls"
)

const warmReplenishInterval = 5 * time.Second

// Warmer keeps WarmSessions channels filled with pre-created chat IDs.
type Warmer struct {
	pool *Pool
}

// NewWarmer creates a Warmer and starts the background replenishment goroutine.
func NewWarmer(pool *Pool) *Warmer {
	w := &Warmer{pool: pool}
	go w.run(context.Background())
	return w
}

// NewWarmerFromWrapper creates a warmer for a FilePoolWrapper (no-Redis mode).
func NewWarmerFromWrapper(fw *FilePoolWrapper) {
	warmAll := func() {
		for _, acc := range fw.All() {
			if acc.breaker.IsOpen() {
				continue
			}
			for len(acc.WarmSessions) < warmDepth {
				chatID, err := createChat(context.Background(), acc)
				if err != nil {
					break
				}
				select {
				case acc.WarmSessions <- chatID:
				default:
				}
			}
		}
	}
	go func() {
		warmAll() // warm immediately on start
		tick := time.NewTicker(warmReplenishInterval)
		defer tick.Stop()
		for range tick.C {
			warmAll()
		}
	}()
}


func (w *Warmer) run(ctx context.Context) {
	// Warm immediately — don't wait 5s for first tick
	w.replenish(ctx)

	tick := time.NewTicker(warmReplenishInterval)
	defer tick.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-tick.C:
			w.replenish(ctx)
		}
	}
}

func (w *Warmer) replenish(ctx context.Context) {
	for _, acc := range w.pool.All() {
		if acc.breaker.IsOpen() {
			continue
		}
		for len(acc.WarmSessions) < warmDepth {
			chatID, err := createChat(ctx, acc)
			if err != nil {
				slog.Debug("[warmer] create_chat failed", "email", acc.Email, "error", err)
				break
			}
			select {
			case acc.WarmSessions <- chatID:
				slog.Debug("[warmer] pre-warmed session", "email", acc.Email, "chat_id", chatID)
			default:
				// Channel full, discard
			}
		}
	}
}

// AcquireSession returns a pre-warmed chat ID if available, otherwise creates one on-demand.
func AcquireSession(ctx context.Context, acc *Account) (string, error) {
	select {
	case id := <-acc.WarmSessions:
		return id, nil
	default:
		slog.Debug("[warmer] no warm session, creating on-demand", "email", acc.Email)
		return createChat(ctx, acc)
	}
}

// createChat calls Qwen's /api/v2/chats/new to create a new chat session.
func createChat(ctx context.Context, acc *Account) (string, error) {
	ts := time.Now().Unix()
	body := map[string]any{
		"title":     fmt.Sprintf("api_%d", ts),
		"models":    []string{"qwen-plus"},
		"chat_mode": "normal",
		"chat_type": "t2t",
		"timestamp": ts,
	}
	bodyBytes, _ := json.Marshal(body)

	client, err := tlsclient.NewClient()
	if err != nil {
		return "", err
	}

	headers := tlsclient.BaseHeaders(acc.Token)
	headers["Content-Type"] = "application/json"

	req, err := fhttp.NewRequestWithContext(ctx, "POST",
		tlsclient.BaseURL+"/api/v2/chats/new",
		bytes.NewReader(bodyBytes))
	if err != nil {
		return "", err
	}
	for k, v := range headers {
		req.Header.Set(k, v)
	}

	resp, err := client.Do(req)
	if err != nil {
		return "", fmt.Errorf("create_chat request: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		return "", fmt.Errorf("create_chat HTTP %d", resp.StatusCode)
	}

	b, _ := io.ReadAll(resp.Body)
	var result struct {
		Success bool `json:"success"`
		Data    struct {
			ID string `json:"id"`
		} `json:"data"`
	}
	if err := json.Unmarshal(b, &result); err != nil || !result.Success || result.Data.ID == "" {
		preview := string(b)
		if len(preview) > 200 {
			preview = preview[:200]
		}
		return "", fmt.Errorf("create_chat parse error: %s", preview)
	}
	return result.Data.ID, nil
}
