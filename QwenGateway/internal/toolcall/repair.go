package toolcall

import (
	"regexp"
	"strings"
	"unicode"
)

// RepairJSON attempts to fix common LLM JSON output errors:
// 1. Unquoted keys: {name: "foo"} → {"name": "foo"}
// 2. Single quotes: {'key': 'val'} → {"key": "val"}
// 3. Trailing commas: {"a": 1,} → {"a": 1}
// 4. Illegal backslashes: \q → \\q
func RepairJSON(s string) string {
	if s == "" {
		return s
	}
	s = singleToDouble(s)
	s = reUnquotedKey.ReplaceAllString(s, `"$1":`)
	s = reTrailingComma.ReplaceAllString(s, "$1")
	s = repairInvalidJSONBackslashes(s)
	return s
}

// RepairLooseJSON fixes additional LLM JSON quirks ported from ds2api:
// 1. Unquoted object keys: {key: → {"key":
// 2. Missing array brackets for list of objects: "key": {a}, {b} → "key": [{a}, {b}]
func RepairLooseJSON(s string) string {
	s = strings.TrimSpace(s)
	if s == "" {
		return s
	}
	s = unquotedKeyPattern.ReplaceAllString(s, `$1"$2":`)
	s = missingArrayBracketsPattern.ReplaceAllString(s, `$1[$2]`)
	return s
}

// repairInvalidJSONBackslashes fixes backslash sequences that are invalid in JSON.
// Valid sequences: \" \\ \/ \b \f \n \r \t \uXXXX — everything else gets doubled.
func repairInvalidJSONBackslashes(s string) string {
	if !strings.Contains(s, `\`) {
		return s
	}
	var out strings.Builder
	out.Grow(len(s) + 10)
	runes := []rune(s)
	for i := 0; i < len(runes); i++ {
		if runes[i] != '\\' {
			out.WriteRune(runes[i])
			continue
		}
		if i+1 >= len(runes) {
			out.WriteString(`\\`)
			continue
		}
		next := runes[i+1]
		switch next {
		case '"', '\\', '/', 'b', 'f', 'n', 'r', 't':
			out.WriteRune('\\')
			out.WriteRune(next)
			i++
		case 'u':
			if i+5 < len(runes) && isHexRunes(runes[i+2:i+6]) {
				out.WriteRune('\\')
				out.WriteRune('u')
				for j := 1; j <= 4; j++ {
					out.WriteRune(runes[i+1+j])
				}
				i += 5
			} else {
				out.WriteString(`\\`)
			}
		default:
			out.WriteString(`\\`)
		}
	}
	return out.String()
}

func isHexRunes(runes []rune) bool {
	for _, r := range runes {
		if !((r >= '0' && r <= '9') || (r >= 'a' && r <= 'f') || (r >= 'A' && r <= 'F')) {
			return false
		}
	}
	return true
}

// repairPathLikeControlChars escapes control characters in path/file string values.
func repairPathLikeControlChars(m map[string]any) {
	for k, v := range m {
		switch vv := v.(type) {
		case map[string]any:
			repairPathLikeControlChars(vv)
		case []any:
			for _, item := range vv {
				if child, ok := item.(map[string]any); ok {
					repairPathLikeControlChars(child)
				}
			}
		case string:
			if isPathLikeKey(k) && containsControlRune(vv) {
				m[k] = escapeControlRunes(vv)
			}
		}
	}
}

func isPathLikeKey(key string) bool {
	k := strings.ToLower(strings.TrimSpace(key))
	return strings.Contains(k, "path") || strings.Contains(k, "file")
}

func containsControlRune(s string) bool {
	for _, r := range s {
		if unicode.IsControl(r) {
			return true
		}
	}
	return false
}

func escapeControlRunes(s string) string {
	var b strings.Builder
	b.Grow(len(s) + 8)
	for _, r := range s {
		switch r {
		case '\b':
			b.WriteString(`\b`)
		case '\f':
			b.WriteString(`\f`)
		case '\n':
			b.WriteString(`\n`)
		case '\r':
			b.WriteString(`\r`)
		case '\t':
			b.WriteString(`\t`)
		default:
			b.WriteRune(r)
		}
	}
	return b.String()
}

var (
	reUnquotedKey    = regexp.MustCompile(`([{,]\s*)(\w+)\s*:`)
	reTrailingComma  = regexp.MustCompile(`,(\s*[}\]])`)

	// unquotedKeyPattern: stricter version from ds2api that only matches identifier-like keys
	unquotedKeyPattern = regexp.MustCompile(`([{,]\s*)([a-zA-Z_][a-zA-Z0-9_]*)\s*:`)
	// missingArrayBracketsPattern: wraps multiple adjacent objects in array brackets
	missingArrayBracketsPattern = regexp.MustCompile(`(:\s*)(\{(?:[^{}]|\{[^{}]*\})*\}(?:\s*,\s*\{(?:[^{}]|\{[^{}]*\})*\})+)`)
)

// singleToDouble naively replaces single-quote delimiters with double quotes.
func singleToDouble(s string) string {
	if !strings.Contains(s, "'") {
		return s
	}
	var b strings.Builder
	b.Grow(len(s))
	inSingle := false
	inDouble := false
	for i := 0; i < len(s); i++ {
		ch := s[i]
		switch {
		case ch == '\\' && i+1 < len(s):
			b.WriteByte(ch)
			i++
			b.WriteByte(s[i])
		case ch == '"' && !inSingle:
			inDouble = !inDouble
			b.WriteByte(ch)
		case ch == '\'' && !inDouble:
			inSingle = !inSingle
			b.WriteByte('"')
		default:
			b.WriteByte(ch)
		}
	}
	return b.String()
}
