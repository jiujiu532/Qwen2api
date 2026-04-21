package toolcall

import (
	"encoding/json"
	"fmt"
	"strings"
)

// Tool represents one OpenAI-compatible tool definition.
type Tool struct {
	Type     string   `json:"type"`
	Function ToolFunc `json:"function"`
}

// ToolFunc is the function descriptor inside a Tool.
type ToolFunc struct {
	Name        string         `json:"name"`
	Description string         `json:"description"`
	Parameters  map[string]any `json:"parameters"`
}

// BuildSystemPrompt constructs the tool-calling system prompt.
func BuildSystemPrompt(tools []Tool) string {
	if len(tools) == 0 {
		return ""
	}
	toolsJSON, _ := json.MarshalIndent(tools, "", "  ")
	var names []string
	for _, t := range tools {
		names = append(names, t.Function.Name)
	}
	nameList := strings.Join(names, ", ")

	lines := []string{
		"You are a helpful assistant with access to the following tools:",
		string(toolsJSON),
		"",
		"## Rules for Tool Calling",
		"",
		fmt.Sprintf("You MUST use this EXACT format: [TOOL_CALL]{\"name\": \"tool_name\", \"parameters\": {\"key\": \"value\"}}[/TOOL_CALL]"),
		fmt.Sprintf("Available tools: %s", nameList),
		"",
		"## Critical Rules",
		"1. Use ONLY JSON with double-quoted keys inside [TOOL_CALL]...[/TOOL_CALL]",
		"2. Do NOT wrap tool calls in markdown code fences (triple backticks)",
		"3. You MAY call multiple tools; place each on its own line",
		"4. Parameters must exactly match the tool schema",
		"",
		"## Wrong Examples (DO NOT DO THIS)",
		"",
		"Wrong 1 - XML: <tool_call><name>fn</name><parameters>{\"k\":\"v\"}</parameters></tool_call>",
		"Wrong 2 - Unquoted keys: [TOOL_CALL]{name: \"fn\", parameters: {k: \"v\"}}[/TOOL_CALL]",
		"Wrong 3 - Code fence: ```json\\n[TOOL_CALL]...[/TOOL_CALL]\\n```",
		"",
		"## Correct Examples",
		"",
		"Single: [TOOL_CALL]{\"name\": \"search\", \"parameters\": {\"query\": \"Go async\"}}[/TOOL_CALL]",
		"",
		"Parallel:",
		"[TOOL_CALL]{\"name\": \"weather\", \"parameters\": {\"city\": \"Beijing\"}}[/TOOL_CALL]",
		"[TOOL_CALL]{\"name\": \"weather\", \"parameters\": {\"city\": \"Shanghai\"}}[/TOOL_CALL]",
		"",
		"## Anchor",
		"Always follow these rules exactly.",
	}
	return strings.Join(lines, "\n")
}
