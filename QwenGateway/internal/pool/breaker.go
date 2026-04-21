package pool

import (
	"sync"
	"time"
)

const (
	breakerThreshold = 3
	breakerCooldown  = 60 * time.Second
)

// CircuitBreaker tracks failures per account and opens (blocks) after threshold.
type CircuitBreaker struct {
	mu        sync.Mutex
	failCount int
	openUntil time.Time
}

// Allow returns true if the account should be tried.
func (cb *CircuitBreaker) Allow() bool {
	cb.mu.Lock()
	defer cb.mu.Unlock()
	if cb.failCount >= breakerThreshold && time.Now().Before(cb.openUntil) {
		return false // circuit open — skip this account
	}
	return true
}

// OnSuccess resets the breaker.
func (cb *CircuitBreaker) OnSuccess() {
	cb.mu.Lock()
	defer cb.mu.Unlock()
	cb.failCount = 0
	cb.openUntil = time.Time{}
}

// OnFail increments the failure counter and opens the circuit if threshold is reached.
func (cb *CircuitBreaker) OnFail() {
	cb.mu.Lock()
	defer cb.mu.Unlock()
	cb.failCount++
	if cb.failCount >= breakerThreshold {
		cb.openUntil = time.Now().Add(breakerCooldown)
	}
}

// IsOpen returns true when the circuit is currently open.
func (cb *CircuitBreaker) IsOpen() bool {
	cb.mu.Lock()
	defer cb.mu.Unlock()
	return cb.failCount >= breakerThreshold && time.Now().Before(cb.openUntil)
}
