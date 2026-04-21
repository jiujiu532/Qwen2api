package pool

import (
	"encoding/json"
	"log/slog"
	"os"
	"strings"
	"sync"
	"time"
)

// fileAccount is the JSON shape of accounts in the existing qwen2api JSON files.
type fileAccount struct {
	Email     string `json:"email"`
	Token     string `json:"token"`
	Valid      bool   `json:"valid"`
	StatusCode string `json:"status_code"`
}

// FilePool is a Redis-free in-memory account pool backed by a JSON file.
// It re-reads the file every 60 seconds to pick up new accounts.
type FilePool struct {
	path     string
	mu       sync.RWMutex
	accounts map[string]*Account
}

// NewFilePool creates a FilePool and starts the background file-sync goroutine.
func NewFilePool(path string) *FilePool {
	fp := &FilePool{
		path:     path,
		accounts: make(map[string]*Account),
	}
	if err := fp.load(); err != nil {
		slog.Warn("[filepool] initial load failed", "error", err)
	}
	go fp.syncLoop()
	return fp
}

func (fp *FilePool) syncLoop() {
	tick := time.NewTicker(60 * time.Second)
	defer tick.Stop()
	for range tick.C {
		if err := fp.load(); err != nil {
			slog.Warn("[filepool] reload failed", "error", err)
		}
	}
}

func (fp *FilePool) load() error {
	data, err := os.ReadFile(fp.path)
	if err != nil {
		return err
	}

	var raw []fileAccount
	if err := json.Unmarshal(data, &raw); err != nil {
		return err
	}

	fp.mu.Lock()
	defer fp.mu.Unlock()

	for _, a := range raw {
		if a.Token == "" {
			continue
		}
		// Only load valid accounts (case-insensitive — Python uses "VALID", Go tests use "valid")
		if a.StatusCode != "" && strings.ToLower(a.StatusCode) != "valid" {
			continue
		}
		if _, ok := fp.accounts[a.Email]; !ok {
			fp.accounts[a.Email] = &Account{
				Email:        a.Email,
				Token:        a.Token,
				EMA:          5000,
				breaker:      &CircuitBreaker{},
				WarmSessions: make(chan string, warmDepth),
			}
		} else {
			fp.accounts[a.Email].Token = a.Token
		}
	}
	slog.Info("[filepool] loaded from file", "count", len(fp.accounts), "path", fp.path)
	return nil
}

// ToPool converts FilePool into a standard *Pool struct (for compatibility with warmer/probe).
// It returns a Pool whose in-memory accounts map is backed by the file accounts.
func (fp *FilePool) AsPool() *Pool {
	p := &Pool{
		rdb:      nil,
		accounts: fp.accounts,
	}
	return p
}

// FilePoolWrapper wraps FilePool to implement the same interface used by handlers.
type FilePoolWrapper struct {
	fp *FilePool
}

// NewFilePoolWrapper creates a pool wrapper usable without Redis.
func NewFilePoolWrapper(path string) *FilePoolWrapper {
	return &FilePoolWrapper{fp: NewFilePool(path)}
}

func (w *FilePoolWrapper) Size() int {
	w.fp.mu.RLock()
	defer w.fp.mu.RUnlock()
	return len(w.fp.accounts)
}

func (w *FilePoolWrapper) TopN(n int) []*Account {
	return w.fp.AsPool().TopN(n)
}

func (w *FilePoolWrapper) RecordSuccess(acc *Account, latencyMs int64) {
	acc.EMA = 0.2*float64(latencyMs) + 0.8*acc.EMA
	acc.breaker.OnSuccess()
}

func (w *FilePoolWrapper) RecordFailure(acc *Account, reason string) {
	acc.breaker.OnFail()
}

// All returns all accounts in the file pool (used by warmer).
func (w *FilePoolWrapper) All() []*Account {
	return w.fp.AsPool().All()
}
