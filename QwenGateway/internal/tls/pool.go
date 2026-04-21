package tls

import (
	"crypto/tls"
	"net"
	"net/http"
	"sync"
	"time"

	tls_client "github.com/bogdanfinn/tls-client"
	"github.com/bogdanfinn/tls-client/profiles"
)

// ── Standard fallback client (no fingerprinting) ────────────────────────────

var (
	fallbackOnce   sync.Once
	fallbackClient *http.Client
)

// FallbackClient returns a shared standard net/http client.
// Used when the TLS-fingerprint client fails — avoids losing the request entirely.
func FallbackClient() *http.Client {
	fallbackOnce.Do(func() {
		transport := &http.Transport{
			ForceAttemptHTTP2:   false,
			MaxIdleConns:        200,
			MaxIdleConnsPerHost: 100,
			IdleConnTimeout:     90 * time.Second,
			DialContext: (&net.Dialer{
				Timeout:   15 * time.Second,
				KeepAlive: 30 * time.Second,
			}).DialContext,
			TLSClientConfig: &tls.Config{MinVersion: tls.VersionTLS12},
		}
		fallbackClient = &http.Client{
			Transport: transport,
			Timeout:   1800 * time.Second,
		}
	})
	return fallbackClient
}



// clientPool is pre-built tls-client instances, one per fingerprint profile.
// These are reused across requests to avoid the expensive NewHttpClient() call (~20ms each).
var (
	once        sync.Once
	clientPools []*sync.Pool
)

func initPools() {
	once.Do(func() {
		clientPools = make([]*sync.Pool, len(profilePool))
		for i, profile := range profilePool {
			p := profile // capture
			clientPools[i] = &sync.Pool{
				New: func() any {
					jar := tls_client.NewCookieJar()
					c, _ := tls_client.NewHttpClient(tls_client.NewNoopLogger(),
						tls_client.WithClientProfile(p),
						tls_client.WithCookieJar(jar),
						tls_client.WithTimeoutSeconds(1800),
						tls_client.WithNotFollowRedirects(),
					)
					return c
				},
			}
		}
	})
}

// AcquireClient grabs a pooled tls-client (fast, no allocation on hot path).
func AcquireClient() (tls_client.HttpClient, func()) {
	initPools()
	n := requestCounter.Add(1)
	pool := clientPools[n%int64(len(clientPools))]
	c := pool.Get().(tls_client.HttpClient)
	return c, func() { pool.Put(c) }
}

// WarmPool pre-populates each pool with 2 clients so the first requests have
// zero allocation cost. Call once at startup.
func WarmPool() {
	initPools()
	for _, pool := range clientPools {
		for i := 0; i < 2; i++ {
			pool.Put(pool.New())
		}
	}
}

// profileOf returns the profile name for a given profile.
func profileOf(p profiles.ClientProfile) string {
	return p.GetClientHelloStr()
}
