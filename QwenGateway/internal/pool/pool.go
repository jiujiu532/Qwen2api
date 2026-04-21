// Package pool manages the Qwen account pool backed by Redis.
// It maintains an in-memory cache of valid accounts for fast selection,
// refreshes from Redis every 30 seconds, and tracks EMA latency per account.
package pool

import (
	"context"
	"log/slog"
	"math"
	"sort"
	"sync"
	"time"

	"github.com/redis/go-redis/v9"
)

const (
	redisKeyValid    = "qwen:accounts:valid"
	redisKeyTokenPfx = "qwen:accounts:token:"
	redisKeyMetaPfx  = "qwen:accounts:meta:"
	syncInterval     = 30 * time.Second
	emaAlpha         = 0.2 // EMA smoothing factor
	warmDepth        = 2   // pre-warm session slots per account
)

// Account represents one Qwen account in the pool.
type Account struct {
	Email   string
	Token   string
	EMA     float64 // exponential moving average response time (ms)
	breaker *CircuitBreaker
	// WarmSessions is a buffered channel of pre-created chat IDs.
	WarmSessions chan string
}

// GetBreaker exposes the circuit breaker for use by external packages.
func (a *Account) GetBreaker() *CircuitBreaker { return a.breaker }


// Pool is the in-memory account pool backed by Redis.
type Pool struct {
	rdb      *redis.Client
	mu       sync.RWMutex
	accounts map[string]*Account // email → Account
}

// New creates a Pool, starts the background sync goroutine, and returns.
func New(rdb *redis.Client) *Pool {
	p := &Pool{
		rdb:      rdb,
		accounts: make(map[string]*Account),
	}
	go p.syncLoop()
	return p
}

// syncLoop periodically refreshes the in-memory map from Redis.
func (p *Pool) syncLoop() {
	tick := time.NewTicker(syncInterval)
	defer tick.Stop()
	// Sync immediately on startup.
	if err := p.sync(context.Background()); err != nil {
		slog.Warn("[pool] initial sync failed", "error", err)
	}
	for range tick.C {
		if err := p.sync(context.Background()); err != nil {
			slog.Warn("[pool] sync failed", "error", err)
		}
	}
}

// sync pulls valid accounts from Redis and updates the in-memory map.
func (p *Pool) sync(ctx context.Context) error {
	emails, err := p.rdb.SMembers(ctx, redisKeyValid).Result()
	if err != nil {
		return err
	}

	fresh := make(map[string]*Account, len(emails))
	for _, email := range emails {
		token, err := p.rdb.Get(ctx, redisKeyTokenPfx+email).Result()
		if err != nil || token == "" {
			continue
		}

		p.mu.RLock()
		existing, ok := p.accounts[email]
		p.mu.RUnlock()

		if ok {
			existing.Token = token // token may have been refreshed
			fresh[email] = existing
		} else {
			fresh[email] = &Account{
				Email:        email,
				Token:        token,
				EMA:          5000, // assume 5s initially
				breaker:      &CircuitBreaker{},
				WarmSessions: make(chan string, warmDepth),
			}
		}
	}

	p.mu.Lock()
	p.accounts = fresh
	p.mu.Unlock()

	slog.Info("[pool] synced from Redis", "count", len(fresh))
	return nil
}

// All returns a snapshot of all accounts (including those with open breakers).
func (p *Pool) All() []*Account {
	p.mu.RLock()
	defer p.mu.RUnlock()
	out := make([]*Account, 0, len(p.accounts))
	for _, acc := range p.accounts {
		out = append(out, acc)
	}
	return out
}

// TopN returns the N accounts with the lowest EMA latency (excluding open breakers).
func (p *Pool) TopN(n int) []*Account {
	p.mu.RLock()
	all := make([]*Account, 0, len(p.accounts))
	for _, acc := range p.accounts {
		if acc.breaker.Allow() {
			all = append(all, acc)
		}
	}
	p.mu.RUnlock()

	sort.Slice(all, func(i, j int) bool {
		return all[i].EMA < all[j].EMA
	})
	if n > len(all) {
		n = len(all)
	}
	return all[:n]
}

// RecordSuccess updates EMA and resets the circuit breaker for an account.
func (p *Pool) RecordSuccess(acc *Account, latencyMs int64) {
	acc.EMA = emaAlpha*float64(latencyMs) + (1-emaAlpha)*acc.EMA
	acc.breaker.OnSuccess()
	// Persist avg_ms to Redis (fire-and-forget)
	go func() {
		ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		defer cancel()
		p.rdb.HSet(ctx, redisKeyMetaPfx+acc.Email, "avg_ms", math.Round(acc.EMA))
	}()
}

// RecordFailure bumps the circuit breaker.
func (p *Pool) RecordFailure(acc *Account, reason string) {
	acc.breaker.OnFail()
	slog.Warn("[pool] account failure", "email", acc.Email, "reason", reason,
		"breaker_open", acc.breaker.IsOpen())
}

// MarkInvalid immediately removes an account from the in-memory pool
// and moves it to the rate-limited or banned set in Redis.
func (p *Pool) MarkInvalid(ctx context.Context, acc *Account, kind string) {
	p.mu.Lock()
	delete(p.accounts, acc.Email)
	p.mu.Unlock()

	pipe := p.rdb.Pipeline()
	pipe.SRem(ctx, redisKeyValid, acc.Email)
	if kind == "banned" {
		pipe.SAdd(ctx, "qwen:accounts:banned", acc.Email)
	} else {
		// rate_limited — auto-expire after 30 minutes
		pipe.SAdd(ctx, "qwen:accounts:ratelimit", acc.Email)
		pipe.Expire(ctx, "qwen:accounts:ratelimit", 30*time.Minute)
	}
	pipe.HSet(ctx, redisKeyMetaPfx+acc.Email, "status", kind)
	if _, err := pipe.Exec(ctx); err != nil {
		slog.Warn("[pool] MarkInvalid Redis error", "email", acc.Email, "error", err)
	}
}

// Size returns the current number of in-memory accounts.
func (p *Pool) Size() int {
	p.mu.RLock()
	defer p.mu.RUnlock()
	return len(p.accounts)
}
