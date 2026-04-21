// Package tls provides a Chrome-fingerprinted HTTP client via tls-client.
package tls

import (
	"fmt"
	"sync/atomic"

	tls_client "github.com/bogdanfinn/tls-client"
	"github.com/bogdanfinn/tls-client/profiles"
)

// profilePool is the list of Chrome/Firefox fingerprints to rotate through.
var profilePool = []profiles.ClientProfile{
	profiles.Chrome_124,
	profiles.Chrome_120,
	profiles.Chrome_117,
	profiles.Firefox_117,
}

var requestCounter atomic.Int64

const (
	BaseURL = "https://chat.qwen.ai"
)

// BaseHeaders returns the default browser-like headers for a given token.
func BaseHeaders(token string) map[string]string {
	return map[string]string{
		"Authorization":   "Bearer " + token,
		"User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
		"Accept":          "application/json, text/plain, */*",
		"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
		"Referer":         "https://chat.qwen.ai/",
		"Origin":          "https://chat.qwen.ai",
		"sec-ch-ua":       `"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"`,
		"sec-ch-ua-mobile":   "?0",
		"sec-ch-ua-platform": `"Windows"`,
		"sec-fetch-dest":     "empty",
		"sec-fetch-mode":     "cors",
		"sec-fetch-site":     "same-origin",
	}
}

// NewClient returns a new tls-client with a rotated Chrome fingerprint.
// Fingerprints rotate per-request to reduce pattern detection.
func NewClient() (tls_client.HttpClient, error) {
	n := requestCounter.Add(1)
	profile := profilePool[n%int64(len(profilePool))]

	jar := tls_client.NewCookieJar()
	opts := []tls_client.HttpClientOption{
		tls_client.WithClientProfile(profile),
		tls_client.WithCookieJar(jar),
		tls_client.WithTimeoutSeconds(30),
		tls_client.WithNotFollowRedirects(),
	}
	c, err := tls_client.NewHttpClient(tls_client.NewNoopLogger(), opts...)
	if err != nil {
		return nil, fmt.Errorf("tls-client init: %w", err)
	}
	return c, nil
}

// NewStreamClient returns a client configured for long-lived SSE streams.
func NewStreamClient() (tls_client.HttpClient, error) {
	n := requestCounter.Add(1)
	profile := profilePool[n%int64(len(profilePool))]

	jar := tls_client.NewCookieJar()
	opts := []tls_client.HttpClientOption{
		tls_client.WithClientProfile(profile),
		tls_client.WithCookieJar(jar),
		tls_client.WithTimeoutSeconds(1800), // 30 minutes for long completions
		tls_client.WithNotFollowRedirects(),
	}
	c, err := tls_client.NewHttpClient(tls_client.NewNoopLogger(), opts...)
	if err != nil {
		return nil, fmt.Errorf("tls-client stream init: %w", err)
	}
	return c, nil
}
