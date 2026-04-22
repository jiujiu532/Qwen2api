package toolcall

import (
	"encoding/json"
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
// Uses XML <tool_calls> format consistent with the XML parser (Layer 1).
func BuildSystemPrompt(tools []Tool) string {
	if len(tools) == 0 {
		return ""
	}
	toolsJSON, _ := json.MarshalIndent(tools, "", "  ")

	// Pick representative tool names for examples.
	ex1, ex2 := "read_file", "write_to_file"
	for _, t := range tools {
		n := t.Function.Name
		if ex1 == "read_file" && (strings.Contains(n, "read") || strings.Contains(n, "list") || strings.Contains(n, "search")) {
			ex1 = n
		}
		if ex2 == "write_to_file" && (strings.Contains(n, "write") || strings.Contains(n, "exec") || strings.Contains(n, "run") || strings.Contains(n, "bash")) {
			ex2 = n
		}
	}
	// If only one tool available, use it for both examples.
	if len(tools) == 1 {
		ex1 = tools[0].Function.Name
		ex2 = ex1
	}

	return `You are a helpful assistant with access to the following tools:

` + string(toolsJSON) + `

## Tool Call Format — Follow Exactly

<tool_calls>
  <tool_call>
    <tool_name>TOOL_NAME_HERE</tool_name>
    <parameters>
      <PARAMETER_NAME><![CDATA[PARAMETER_VALUE]]></PARAMETER_NAME>
    </parameters>
  </tool_call>
</tool_calls>

## Rules
1. Use ONLY the <tool_calls> XML format. Never emit JSON, function-call syntax, or [TOOL_CALL] brackets.
2. Put one or more <tool_call> entries under a single <tool_calls> root.
3. All string values MUST use <![CDATA[...]]>, including short values, paths, queries, and code.
4. Numbers, booleans, and null stay as plain text (no CDATA).
5. Nested objects use nested XML elements. Arrays repeat the same tag.
6. Do NOT wrap XML in triple-backtick markdown code fences.
7. Use only parameter names from the tool schema.

## Wrong Examples (DO NOT DO THIS)
Wrong 1 — JSON format: {"name": "` + ex1 + `", "parameters": {"path": "x"}}
Wrong 2 — [TOOL_CALL] brackets: [TOOL_CALL]{"name": "` + ex1 + `"}[/TOOL_CALL]
Wrong 3 — Markdown fences: wrap XML in backticks

## Correct Examples

Single tool:
<tool_calls>
  <tool_call>
    <tool_name>` + ex1 + `</tool_name>
    <parameters>
      <path><![CDATA[src/main.go]]></path>
    </parameters>
  </tool_call>
</tool_calls>

Two tools in parallel:
<tool_calls>
  <tool_call>
    <tool_name>` + ex1 + `</tool_name>
    <parameters>
      <path><![CDATA[README.md]]></path>
    </parameters>
  </tool_call>
  <tool_call>
    <tool_name>` + ex2 + `</tool_name>
    <parameters>
      <path><![CDATA[output.txt]]></path>
      <content><![CDATA[Hello world]]></content>
    </parameters>
  </tool_call>
</tool_calls>

Always place the <tool_calls> block at the END of your response.
`
}
