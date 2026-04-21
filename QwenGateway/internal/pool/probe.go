package pool

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"time"

	fhttp "github.com/bogdanfinn/fhttp"
	tlsclient "github.com/jiujiu532/qwengateway/internal/tls"
)

const probeInterval = 60 * time.Second

// Probe periodically sends a lightweight ping to every account to detect stale tokens.
type Probe struct {
	pool           *Pool
	notifyEndpoint string // Python internal API: POST /internal/accounts/mark
}

// NewProbe creates and starts the health probe goroutine.
func NewProbe(pool *Pool, notifyEndpoint string) *Probe {
	p := &Probe{pool: pool, notifyEndpoint: notifyEndpoint}
	go p.run(context.Background())
	return p
}

func (p *Probe) run(ctx context.Context) {
	tick := time.NewTicker(probeInterval)
	defer tick.Stop()
	for range tick.C {
		for _, acc := range p.pool.All() {
			go p.ping(ctx, acc)
		}
	}
}

func (p *Probe) ping(ctx context.Context, acc *Account) {
	pingCtx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()

	client, err := tlsclient.NewClient()
	if err != nil {
		return
	}

	headers := tlsclient.BaseHeaders(acc.Token)
	req, err := fhttp.NewRequestWithContext(pingCtx, "GET",
		tlsclient.BaseURL+"/api/v1/auths/",
		nil)
	if err != nil {
		return
	}
	for k, v := range headers {
		req.Header.Set(k, v)
	}

	resp, err := client.Do(req)
	if err != nil || resp.StatusCode != 200 {
		statusCode := 0
		if resp != nil {
			statusCode = resp.StatusCode
		}
		slog.Warn("[probe] token invalid", "email", acc.Email, "status", statusCode)
		p.pool.MarkInvalid(context.Background(), acc, "auth")
		p.notify(acc, "auth")
	}
}

// notify tells Python to attempt auto-healing (token refresh) for this account.
func (p *Probe) notify(acc *Account, reason string) {
	if p.notifyEndpoint == "" {
		return
	}
	body, _ := json.Marshal(map[string]string{
		"email":  acc.Email,
		"reason": reason,
	})
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	req, _ := http.NewRequestWithContext(ctx, "POST", p.notifyEndpoint, bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	// Notify uses standard net/http (calling Python localhost, no WAF bypass needed)
	client := &http.Client{Timeout: 5 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		slog.Warn("[probe] notify Python failed", "error", err)
		return
	}
	defer resp.Body.Close()
	slog.Info("[probe] notified Python", "email", acc.Email, "reason", reason,
		"status", fmt.Sprintf("HTTP %d", resp.StatusCode))
}
