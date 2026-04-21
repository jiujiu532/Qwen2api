package toolcall

import (
	"encoding/json"

	"github.com/google/uuid"
)

// OpenAIToolCall is the OpenAI-compatible tool call format.
type OpenAIToolCall struct {
	ID       string           `json:"id"`
	Type     string           `json:"type"`
	Function OpenAIFunctionCall `json:"function"`
}

// OpenAIFunctionCall holds the function name and JSON-encoded arguments.
type OpenAIFunctionCall struct {
	Name      string `json:"name"`
	Arguments string `json:"arguments"`
}

// FormatAsOpenAI converts parsed tool calls into the OpenAI tool_calls[] format.
func FormatAsOpenAI(calls []ParsedToolCall) []OpenAIToolCall {
	out := make([]OpenAIToolCall, 0, len(calls))
	for _, c := range calls {
		args, err := json.Marshal(c.Input)
		if err != nil {
			args = []byte("{}")
		}
		out = append(out, OpenAIToolCall{
			ID:   "call_" + uuid.New().String()[:8],
			Type: "function",
			Function: OpenAIFunctionCall{
				Name:      c.Name,
				Arguments: string(args),
			},
		})
	}
	return out
}
