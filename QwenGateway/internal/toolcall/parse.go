// Package toolcall implements tool call detection and parsing,
// modeled after ds2api's internal/toolcall package.
// Strategy: strip code fences → try XML DOM parse → fallback to markup parse (attributes, KV, JSON).
package toolcall

import (
	"encoding/json"
	"html"
	"regexp"
	"strings"
)

// ParsedToolCall is a single detected tool invocation.
type ParsedToolCall struct {
	Name  string         `json:"name"`
	Input map[string]any `json:"input"`
}

// ParseResult is the full result of parsing a model output.
type ParseResult struct {
	Calls             []ParsedToolCall
	SawToolCallSyntax bool
}

// Parse attempts to extract tool calls from the model's raw text output.
func Parse(text string) ParseResult {
	result := ParseResult{}
	trimmed := strings.TrimSpace(text)
	if trimmed == "" {
		return result
	}
	result.SawToolCallSyntax = looksLikeToolCall(trimmed)

	trimmed = stripFencedCodeBlocks(trimmed)
	trimmed = strings.TrimSpace(trimmed)
	if trimmed == "" {
		return result
	}

	// Layer 1: Proper recursive XML parser
	calls := parseXMLToolCalls(trimmed)
	// Layer 2: Comprehensive markup parser (attributes, KV, JSON body)
	if len(calls) == 0 {
		calls = parseMarkupToolCalls(trimmed)
	}
	// Layer 3: [TOOL_CALL] bracket format and generic JSON call format
	if len(calls) == 0 {
		calls = parseBracketAndJSONFormat(trimmed)
	}
	if len(calls) == 0 {
		return result
	}

	result.SawToolCallSyntax = true
	result.Calls = filterValid(calls)
	return result
}

// looksLikeToolCall detects if the text contains any tool-call-like syntax.
func looksLikeToolCall(text string) bool {
	lower := strings.ToLower(text)
	markers := []string{
		"<tool_calls", "<tool_call", "<function_calls", "<function_call",
		"<invoke", "<tool_use", "[tool_call]", "function_call",
		"<attempt_completion", "<ask_followup_question",
	}
	for _, m := range markers {
		if strings.Contains(lower, m) {
			return true
		}
	}
	return false
}

// stripFencedCodeBlocks removes ``` or ~~~ fenced blocks from text.
func stripFencedCodeBlocks(text string) string {
	var b strings.Builder
	b.Grow(len(text))
	lines := strings.SplitAfter(text, "\n")
	inFence := false
	fenceMarker := ""
	for _, line := range lines {
		trimmed := strings.TrimLeft(line, " \t")
		if !inFence {
			if marker, ok := parseFenceOpen(trimmed); ok {
				inFence = true
				fenceMarker = marker
				continue
			}
			b.WriteString(line)
			continue
		}
		if isFenceClose(trimmed, fenceMarker) {
			inFence = false
			fenceMarker = ""
		}
	}
	if inFence {
		return "" // unclosed fence — discard everything
	}
	return b.String()
}

func parseFenceOpen(line string) (string, bool) {
	if len(line) < 3 {
		return "", false
	}
	ch := line[0]
	if ch != '`' && ch != '~' {
		return "", false
	}
	count := 0
	for count < len(line) && line[count] == ch {
		count++
	}
	if count < 3 {
		return "", false
	}
	return strings.Repeat(string(ch), count), true
}

func isFenceClose(line, marker string) bool {
	if marker == "" || line == "" || line[0] != marker[0] {
		return false
	}
	count := 0
	for count < len(line) && line[count] == marker[0] {
		count++
	}
	if count < len(marker) {
		return false
	}
	return strings.TrimSpace(line[count:]) == ""
}

// ── Comprehensive Markup Parser (ported from ds2api) ──────────────────────────

var (
	toolCallMarkupTagNames = []string{"tool_call", "function_call", "invoke"}

	toolCallMarkupTagPatterns = map[string]*regexp.Regexp{
		"tool_call":     regexp.MustCompile(`(?is)<(?:[a-z0-9_:-]+:)?tool_call\b([^>]*)>(.*?)</(?:[a-z0-9_:-]+:)?tool_call>`),
		"function_call": regexp.MustCompile(`(?is)<(?:[a-z0-9_:-]+:)?function_call\b([^>]*)>(.*?)</(?:[a-z0-9_:-]+:)?function_call>`),
		"invoke":        regexp.MustCompile(`(?is)<(?:[a-z0-9_:-]+:)?invoke\b([^>]*)>(.*?)</(?:[a-z0-9_:-]+:)?invoke>`),
	}
	toolCallMarkupSelfClosingRe = regexp.MustCompile(`(?is)<(?:[a-z0-9_:-]+:)?invoke\b([^>]*)/?>`)
	toolCallMarkupAttrRe        = regexp.MustCompile(`(?is)(name|function|tool)\s*=\s*"([^"]+)"`)
	toolCallMarkupKVRe          = regexp.MustCompile(`(?is)<(?:[a-z0-9_:-]+:)?([a-z0-9_\-.]+)\b[^>]*>(.*?)</(?:[a-z0-9_:-]+:)?([a-z0-9_\-.]+)>`)
	anyTagRe                    = regexp.MustCompile(`(?is)<[^>]+>`)
	cdataRe                     = regexp.MustCompile(`(?is)^<!\[CDATA\[(.*?)]>$`)

	toolCallMarkupNameTags = []string{"name", "function"}
	toolCallMarkupNameREs  = map[string]*regexp.Regexp{
		"name":     regexp.MustCompile(`(?is)<(?:[a-z0-9_:-]+:)?name\b[^>]*>(.*?)</(?:[a-z0-9_:-]+:)?name>`),
		"function": regexp.MustCompile(`(?is)<(?:[a-z0-9_:-]+:)?function\b[^>]*>(.*?)</(?:[a-z0-9_:-]+:)?function>`),
	}

	toolCallMarkupArgsTags = []string{"input", "arguments", "argument", "parameters", "parameter", "args", "params"}
	toolCallMarkupArgsREs  = map[string]*regexp.Regexp{
		"input":      regexp.MustCompile(`(?is)<(?:[a-z0-9_:-]+:)?input\b[^>]*>(.*?)</(?:[a-z0-9_:-]+:)?input>`),
		"arguments":  regexp.MustCompile(`(?is)<(?:[a-z0-9_:-]+:)?arguments\b[^>]*>(.*?)</(?:[a-z0-9_:-]+:)?arguments>`),
		"argument":   regexp.MustCompile(`(?is)<(?:[a-z0-9_:-]+:)?argument\b[^>]*>(.*?)</(?:[a-z0-9_:-]+:)?argument>`),
		"parameters": regexp.MustCompile(`(?is)<(?:[a-z0-9_:-]+:)?parameters\b[^>]*>(.*?)</(?:[a-z0-9_:-]+:)?parameters>`),
		"parameter":  regexp.MustCompile(`(?is)<(?:[a-z0-9_:-]+:)?parameter\b[^>]*>(.*?)</(?:[a-z0-9_:-]+:)?parameter>`),
		"args":       regexp.MustCompile(`(?is)<(?:[a-z0-9_:-]+:)?args\b[^>]*>(.*?)</(?:[a-z0-9_:-]+:)?args>`),
		"params":     regexp.MustCompile(`(?is)<(?:[a-z0-9_:-]+:)?params\b[^>]*>(.*?)</(?:[a-z0-9_:-]+:)?params>`),
	}
)

func parseMarkupToolCalls(text string) []ParsedToolCall {
	trimmed := strings.TrimSpace(text)
	if trimmed == "" {
		return nil
	}
	var out []ParsedToolCall
	for _, tagName := range toolCallMarkupTagNames {
		pat := toolCallMarkupTagPatterns[tagName]
		for _, m := range pat.FindAllStringSubmatch(trimmed, -1) {
			if len(m) < 3 {
				continue
			}
			if parsed := parseMarkupSingleToolCall(strings.TrimSpace(m[1]), strings.TrimSpace(m[2])); parsed.Name != "" {
				out = append(out, parsed)
			}
		}
	}
	// Self-closing <invoke ... />
	for _, m := range toolCallMarkupSelfClosingRe.FindAllStringSubmatch(trimmed, -1) {
		if len(m) < 2 {
			continue
		}
		if parsed := parseMarkupSingleToolCall(strings.TrimSpace(m[1]), ""); parsed.Name != "" {
			out = append(out, parsed)
		}
	}
	return out
}

func parseMarkupSingleToolCall(attrs, inner string) ParsedToolCall {
	// Try inner as JSON tool call object
	if raw := strings.TrimSpace(inner); raw != "" && strings.HasPrefix(raw, "{") {
		var obj map[string]any
		if err := json.Unmarshal([]byte(raw), &obj); err == nil {
			if tc := extractFromJSONObj(obj); tc.Name != "" {
				return tc
			}
		}
		// Try with repairs
		repaired := RepairJSON(raw)
		if repaired != raw {
			var obj2 map[string]any
			if err := json.Unmarshal([]byte(repaired), &obj2); err == nil {
				if tc := extractFromJSONObj(obj2); tc.Name != "" {
					return tc
				}
			}
		}
	}

	// Extract name from attributes first, then inner tags
	name := ""
	if m := toolCallMarkupAttrRe.FindStringSubmatch(attrs); len(m) >= 3 {
		name = strings.TrimSpace(m[2])
	}
	if name == "" {
		name = findMarkupTagValue(inner, toolCallMarkupNameTags, toolCallMarkupNameREs)
	}
	if name == "" {
		return ParsedToolCall{}
	}

	// Extract args
	input := map[string]any{}
	if argsRaw := findMarkupTagValue(inner, toolCallMarkupArgsTags, toolCallMarkupArgsREs); argsRaw != "" {
		input = parseMarkupInput(argsRaw)
	} else if kv := parseMarkupKVObject(inner); len(kv) > 0 {
		input = kv
	}
	return ParsedToolCall{Name: name, Input: input}
}

func extractFromJSONObj(obj map[string]any) ParsedToolCall {
	name, _ := obj["name"].(string)
	if name == "" {
		if fn, ok := obj["function"].(map[string]any); ok {
			name, _ = fn["name"].(string)
		}
	}
	if name == "" {
		if fc, ok := obj["functionCall"].(map[string]any); ok {
			name, _ = fc["name"].(string)
		}
	}
	if strings.TrimSpace(name) == "" {
		return ParsedToolCall{}
	}
	input := map[string]any{}
	for _, key := range []string{"input", "arguments", "parameters", "args", "params"} {
		if v, ok := obj[key]; ok {
			if m, mok := v.(map[string]any); mok && len(m) > 0 {
				input = m
				break
			} else if s, sok := v.(string); sok {
				if parsed := parseToolCallInputStr(s); len(parsed) > 0 {
					input = parsed
					break
				}
			}
		}
	}
	return ParsedToolCall{Name: strings.TrimSpace(name), Input: input}
}

func parseMarkupInput(raw string) map[string]any {
	trimmed := strings.TrimSpace(raw)
	if trimmed == "" {
		return map[string]any{}
	}
	// Try JSON first
	if strings.HasPrefix(trimmed, "{") {
		if parsed := parseToolCallInputStr(trimmed); len(parsed) > 0 {
			return parsed
		}
	}
	// Try XML fragment
	if strings.HasPrefix(trimmed, "<") {
		if kv := parseMarkupKVObject(trimmed); len(kv) > 0 {
			return kv
		}
	}
	return map[string]any{"_raw": html.UnescapeString(trimmed)}
}

func parseMarkupKVObject(text string) map[string]any {
	matches := toolCallMarkupKVRe.FindAllStringSubmatch(strings.TrimSpace(text), -1)
	if len(matches) == 0 {
		return nil
	}
	out := map[string]any{}
	for _, m := range matches {
		if len(m) < 4 {
			continue
		}
		key := strings.TrimSpace(m[1])
		endKey := strings.TrimSpace(m[3])
		if key == "" || !strings.EqualFold(key, endKey) {
			continue
		}
		value := parseMarkupValue(m[2])
		if value == nil {
			continue
		}
		appendMarkupValue(out, key, value)
	}
	if len(out) == 0 {
		return nil
	}
	return out
}

func parseMarkupValue(inner string) any {
	value := strings.TrimSpace(extractRawTagValue(inner))
	if value == "" {
		return ""
	}
	if strings.Contains(value, "<") && strings.Contains(value, ">") {
		if parsed := parseMarkupInput(value); len(parsed) > 0 {
			if len(parsed) == 1 {
				if raw, ok := parsed["_raw"].(string); ok {
					return raw
				}
			}
			return parsed
		}
	}
	var jsonValue any
	if json.Unmarshal([]byte(value), &jsonValue) == nil {
		return jsonValue
	}
	return value
}

func appendMarkupValue(out map[string]any, key string, value any) {
	if existing, ok := out[key]; ok {
		switch current := existing.(type) {
		case []any:
			out[key] = append(current, value)
		default:
			out[key] = []any{current, value}
		}
		return
	}
	out[key] = value
}

func extractRawTagValue(inner string) string {
	trimmed := strings.TrimSpace(inner)
	if trimmed == "" {
		return ""
	}
	if m := cdataRe.FindStringSubmatch(trimmed); len(m) >= 2 {
		return m[1]
	}
	return html.UnescapeString(inner)
}

func findMarkupTagValue(text string, tagNames []string, patterns map[string]*regexp.Regexp) string {
	for _, tag := range tagNames {
		pat := patterns[tag]
		if pat == nil {
			continue
		}
		if m := pat.FindStringSubmatch(text); len(m) >= 2 {
			value := extractRawTagValue(m[1])
			if value != "" {
				return value
			}
		}
	}
	return ""
}

// ── [TOOL_CALL] bracket and generic JSON formats ──────────────────────────────

var (
	toolCallBracketRe = regexp.MustCompile(`(?si)\[TOOL_CALL\](.*?)\[/TOOL_CALL\]`)
	jsonCallRe        = regexp.MustCompile(`(?si)\{[^{}]*"name"\s*:\s*"([^"]+)"[^{}]*"(?:parameters|arguments|input)"\s*:\s*(\{[^{}]*\})[^{}]*\}`)
)

func parseBracketAndJSONFormat(text string) []ParsedToolCall {
	var calls []ParsedToolCall

	// [TOOL_CALL]{...}[/TOOL_CALL]
	for _, m := range toolCallBracketRe.FindAllStringSubmatch(text, -1) {
		raw := strings.TrimSpace(m[1])
		repaired := RepairJSON(raw)
		var obj map[string]any
		if err := json.Unmarshal([]byte(repaired), &obj); err != nil {
			continue
		}
		name, _ := obj["name"].(string)
		if name == "" {
			continue
		}
		input := extractParamsFromObj(obj)
		calls = append(calls, ParsedToolCall{Name: name, Input: input})
	}
	if len(calls) > 0 {
		return calls
	}

	// Generic {"name": "...", "parameters": {...}}
	for _, m := range jsonCallRe.FindAllStringSubmatch(text, -1) {
		name := m[1]
		raw := RepairJSON(m[2])
		var params map[string]any
		if err := json.Unmarshal([]byte(raw), &params); err != nil {
			params = map[string]any{}
		}
		calls = append(calls, ParsedToolCall{Name: name, Input: params})
	}
	return calls
}

func extractParamsFromObj(obj map[string]any) map[string]any {
	for _, key := range []string{"parameters", "arguments", "input", "params"} {
		if v, ok := obj[key]; ok {
			if m, ok := v.(map[string]any); ok {
				return m
			}
		}
	}
	return map[string]any{}
}

// repairAndParse tries to parse value as JSON, otherwise returns it as a string.
func repairAndParse(s string) any {
	if s == "" {
		return s
	}
	repaired := RepairJSON(s)
	var v any
	if err := json.Unmarshal([]byte(repaired), &v); err == nil {
		return v
	}
	return s
}

func filterValid(calls []ParsedToolCall) []ParsedToolCall {
	out := make([]ParsedToolCall, 0, len(calls))
	for _, c := range calls {
		if c.Name == "" {
			continue
		}
		if c.Input == nil {
			c.Input = map[string]any{}
		}
		out = append(out, c)
	}
	return out
}

// json2Unmarshal is a helper to avoid import cycle — same as json.Unmarshal.
func json2Unmarshal(s string, v any) error {
	return json.Unmarshal([]byte(s), v)
}
