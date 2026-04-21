package toolcall

import (
	"encoding/xml"
	"html"
	"strings"
)

// parseXMLToolCalls is the primary XML-based tool call extractor.
// It handles <tool_calls>, <function_calls>, and bare <invoke> wrappers.
func parseXMLToolCalls(text string) []ParsedToolCall {
	lower := strings.ToLower(text)

	// Try <tool_calls> or <function_calls> outer wrapper first
	for _, outer := range []string{"tool_calls", "function_calls"} {
		open := "<" + outer + ">"
		close := "</" + outer + ">"
		if idx := strings.Index(lower, open); idx >= 0 {
			endIdx := strings.LastIndex(lower, close)
			if endIdx > idx {
				inner := text[idx+len(open) : endIdx]
				if calls := extractInvokeBlocks(inner); len(calls) > 0 {
					return calls
				}
			}
		}
	}

	// Try bare <invoke> blocks
	if calls := extractInvokeBlocks(text); len(calls) > 0 {
		return calls
	}

	// Try <tool_call> blocks (some models use this directly)
	if calls := extractToolCallBlocks(text); len(calls) > 0 {
		return calls
	}

	return nil
}

// extractInvokeBlocks extracts <invoke> or <tool_call> blocks from text using proper XML parsing.
func extractInvokeBlocks(text string) []ParsedToolCall {
	var calls []ParsedToolCall
	remaining := text
	for {
		start := findTagStart(remaining, []string{"invoke", "tool_call"})
		if start < 0 {
			break
		}
		tagName := getTagName(remaining[start:])
		if tagName == "" {
			break
		}
		closeTag := "</" + tagName + ">"
		end := strings.Index(strings.ToLower(remaining[start:]), strings.ToLower(closeTag))
		if end < 0 {
			break
		}
		block := remaining[start : start+end+len(closeTag)]
		if call, ok := parseInvokeBlock(block, tagName); ok {
			calls = append(calls, call)
		}
		remaining = remaining[start+end+len(closeTag):]
	}
	return calls
}

// extractToolCallBlocks handles formats like <tool_call>{"name": ..., "arguments": ...}</tool_call>
func extractToolCallBlocks(text string) []ParsedToolCall {
	return parseMarkupToolCalls(text)
}

func findTagStart(text string, tags []string) int {
	lower := strings.ToLower(text)
	best := -1
	for _, tag := range tags {
		idx := strings.Index(lower, "<"+tag)
		if idx >= 0 && (best < 0 || idx < best) {
			best = idx
		}
	}
	return best
}

func getTagName(text string) string {
	if len(text) == 0 || text[0] != '<' {
		return ""
	}
	end := strings.IndexAny(text[1:], " \t\n\r/>")
	if end < 0 {
		return ""
	}
	return strings.ToLower(text[1 : end+1])
}

// parseInvokeBlock parses a single <invoke>...</invoke> or <tool_call>...</tool_call> block.
func parseInvokeBlock(block, tagName string) (ParsedToolCall, bool) {
	wrapped := "<root>" + block + "</root>"
	dec := xml.NewDecoder(strings.NewReader(wrapped))

	// Skip to <root>
	if _, err := dec.Token(); err != nil {
		return ParsedToolCall{}, false
	}

	// Find the invoke/tool_call element
	children, err := parseXMLChildren(dec, "root")
	if err != nil || len(children) == 0 {
		return ParsedToolCall{}, false
	}

	// Get the invoke/tool_call child
	var invokeData map[string]any
	for _, child := range children {
		if strings.EqualFold(child.name, tagName) {
			invokeData = child.children
			break
		}
	}
	if invokeData == nil {
		return ParsedToolCall{}, false
	}

	// Extract tool name
	name := ""
	for _, key := range []string{"tool_name", "name", "function"} {
		if v, ok := invokeData[key]; ok {
			if s, ok := v.(string); ok && strings.TrimSpace(s) != "" {
				name = strings.TrimSpace(s)
				break
			}
		}
	}
	if name == "" {
		return ParsedToolCall{}, false
	}

	// Extract parameters
	input := map[string]any{}
	for _, key := range []string{"parameters", "arguments", "input", "args", "params"} {
		if v, ok := invokeData[key]; ok {
			switch typed := v.(type) {
			case map[string]any:
				if len(typed) > 0 {
					input = typed
				}
			case string:
				if parsed := parseToolCallInputStr(typed); len(parsed) > 0 {
					input = parsed
				}
			}
			if len(input) > 0 {
				break
			}
		}
	}

	return ParsedToolCall{Name: name, Input: input}, true
}

type xmlNode struct {
	name     string
	text     string
	children map[string]any
}

func parseXMLChildren(dec *xml.Decoder, parentTag string) ([]xmlNode, error) {
	var nodes []xmlNode
	for {
		tok, err := dec.Token()
		if err != nil {
			return nodes, err
		}
		switch t := tok.(type) {
		case xml.StartElement:
			node := xmlNode{name: t.Name.Local}
			childNodes, err := parseXMLChildrenInner(dec, t)
			if err != nil {
				return nodes, err
			}
			node.children = childNodes
			nodes = append(nodes, node)
		case xml.EndElement:
			if strings.EqualFold(t.Name.Local, parentTag) {
				return nodes, nil
			}
		}
	}
}

func parseXMLChildrenInner(dec *xml.Decoder, start xml.StartElement) (map[string]any, error) {
	result := map[string]any{}
	var textParts []string
	hasChildren := false

	for {
		tok, err := dec.Token()
		if err != nil {
			return result, err
		}
		switch t := tok.(type) {
		case xml.CharData:
			s := string([]byte(t))
			if hasChildren && strings.TrimSpace(s) == "" {
				continue
			}
			textParts = append(textParts, s)
		case xml.StartElement:
			if !hasChildren && len(textParts) > 0 && strings.TrimSpace(strings.Join(textParts, "")) == "" {
				textParts = nil
			}
			hasChildren = true
			childMap, err := parseXMLChildrenInner(dec, t)
			if err != nil {
				return result, err
			}
			// Determine value: if childMap has only the text sentinel, unwrap it
			if len(childMap) == 0 {
				// leaf with no children: already consumed as text
			}
			var childVal any
			if len(childMap) == 1 {
				if txt, ok := childMap["__text__"].(string); ok {
					childVal = txt
				}
			}
			if childVal == nil && len(childMap) > 0 {
				// Remove __text__ if redundant
				delete(childMap, "__text__")
				if len(childMap) > 0 {
					childVal = childMap
				}
			}
			key := t.Name.Local
			if existing, ok := result[key]; ok {
				switch ev := existing.(type) {
				case []any:
					result[key] = append(ev, childVal)
				default:
					result[key] = []any{ev, childVal}
				}
			} else {
				result[key] = childVal
			}
		case xml.EndElement:
			if !strings.EqualFold(t.Name.Local, start.Name.Local) {
				// mismatched tag, ignore
				continue
			}
			if !hasChildren {
				txt := strings.Join(textParts, "")
				result["__text__"] = html.UnescapeString(txt)
			} else if len(textParts) > 0 {
				txt := strings.TrimSpace(strings.Join(textParts, ""))
				if txt != "" {
					result["__text__"] = txt
				}
			}
			return result, nil
		}
	}
}

// parseToolCallInputStr parses a string value as JSON tool input,
// applying multiple repair strategies.
func parseToolCallInputStr(raw string) map[string]any {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return nil
	}
	var parsed map[string]any
	if err := json2Unmarshal(raw, &parsed); err == nil && parsed != nil {
		repairPathLikeControlChars(parsed)
		return parsed
	}
	// Try backslash repair
	repaired := repairInvalidJSONBackslashes(raw)
	if repaired != raw {
		if err := json2Unmarshal(repaired, &parsed); err == nil && parsed != nil {
			repairPathLikeControlChars(parsed)
			return parsed
		}
	}
	// Try loose JSON repair
	loose := RepairLooseJSON(raw)
	if loose != raw {
		if err := json2Unmarshal(loose, &parsed); err == nil && parsed != nil {
			repairPathLikeControlChars(parsed)
			return parsed
		}
	}
	return nil
}
