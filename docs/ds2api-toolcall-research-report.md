# ds2api 工具调用实现深度调研报告

> 调研对象：[CJackHwang/ds2api](https://github.com/CJackHwang/ds2api) (commit 8316cf8)
> 调研目的：学习其工具调用处理的优秀实践，为 QwenRegister 项目提供改进参考

---

## 一、项目概述

ds2api 是一个将 DeepSeek 网页版 API 转换为 OpenAI 兼容格式的网关，使用 Go + Node.js 双链路实现。其工具调用处理是整个项目最复杂也最精巧的部分。

**核心挑战**：DeepSeek 网页版不支持原生 function calling，模型只能输出纯文本。ds2api 需要：
1. 通过 prompt 注入教模型输出特定格式的工具调用
2. 在流式输出中实时检测、缓冲、提取工具调用块
3. 防止原始 XML 标记泄漏给下游客户端
4. 将提取的工具调用转为标准 OpenAI `tool_calls` 格式

---

## 二、架构总览

```
请求进入 → Prompt 注入工具指令 → 发送到 DeepSeek → SSE 流式响应
                                                        ↓
                                              Tool Sieve (流式筛分)
                                                        ↓
                                         ┌──────────────┴──────────────┐
                                         ↓                             ↓
                                   普通文本 → 实时透传            工具调用块 → 解析
                                                                       ↓
                                                              ParsedToolCall[]
                                                                       ↓
                                                         格式化为 OpenAI tool_calls
```

**关键模块分工**：

| 模块 | 路径 | 职责 |
|------|------|------|
| Prompt 注入 | `internal/promptcompat/tool_prompt.go` | 将工具 schema 转为文本指令注入 system prompt |
| 工具指令生成 | `internal/toolcall/tool_prompt.go` | 生成 DSML 格式规范 + 示例 |
| 流式筛分 (Go) | `internal/toolstream/` | 实时从 SSE 流中检测/缓冲/提取工具调用 |
| 流式筛分 (JS) | `internal/js/helpers/stream-tool-sieve/` | Node 运行时的镜像实现 |
| XML 解析 | `internal/toolcall/toolcalls_parse_markup.go` | 将 XML/DSML 块解析为结构化数据 |
| 格式化输出 | `internal/format/openai/render_chat.go` | 转为 OpenAI 兼容 JSON |

---

## 三、Prompt 注入策略（核心亮点）

### 3.1 DSML 格式设计

ds2api 设计了一种叫 **DSML** (DeepSeek Markup Language) 的自定义标记格式：

```xml
<|DSML|tool_calls>
  <|DSML|invoke name="read_file">
    <|DSML|parameter name="path"><![CDATA[README.md]]></|DSML|parameter>
  </|DSML|invoke>
</|DSML|tool_calls>
```

**为什么不用普通 XML？**
- `<|DSML|` 前缀让模型有意识地输出"协议标识"，与普通 XML 语义隔离
- 减少模型在讨论 XML 时误触发工具调用的概率
- 同时兼容旧式 `<tool_calls>` 格式作为 fallback

### 3.2 指令结构（注意力优化）

`tool_prompt.go` 中的指令采用"规则 → 错误示例 → 正确示例 → 锚点"结构：

1. **15 条明确规则**：包括 CDATA 包裹、参数命名、禁止 Markdown 围栏等
2. **4 个错误示例**（Wrong 1-4）：明确告诉模型不要做什么
3. **4 个正确示例**（Example A-D）：根据实际可用工具名动态生成
4. **锚点句**：`"The ONLY valid way to use tools is the <|DSML|tool_calls>...</|DSML|tool_calls> block"`

### 3.3 动态示例生成

根据请求中实际传入的工具名，自动选择最相关的示例：
- `Read` / `read_file` → 文件读取示例
- `Bash` / `execute_command` → 脚本执行示例（含 CDATA 长文本）
- `MultiEdit` → 嵌套 XML 参数示例
- 多工具 → 并行调用示例

### 3.4 Read 工具缓存防护

如果检测到工具列表中有 `Read` / `read_file` 类工具，自动追加：
> "If a Read/read_file-style tool result says the file is unchanged... Do not repeatedly call the same read request."

---

## 四、流式 Tool Sieve（防泄漏机制）

这是 ds2api 最精巧的部分——在流式输出中实时检测工具调用，同时防止原始 XML 泄漏。

### 4.1 状态机设计

```go
type State struct {
    pending                strings.Builder  // 待处理缓冲
    capture                strings.Builder  // 正在捕获的工具块
    capturing              bool             // 是否处于捕获模式
    codeFenceStack         []int            // Markdown 围栏嵌套栈
    codeFencePendingTicks  int              // 待处理的反引号计数
    markdownCodeSpanTicks  int              // 行内代码 span 状态
    pendingToolCalls       []ParsedToolCall // 已解析的工具调用
    // ... 增量 delta 相关状态
}
```

### 4.2 处理流程

```
每个 SSE chunk 到达
    ↓
ProcessChunk(state, chunk, toolNames)
    ↓
┌─ 检查是否有已解析的 pendingToolCalls → 输出 Event{ToolCalls}
│
├─ 如果 capturing=true:
│   ├─ 追加到 capture 缓冲
│   ├─ consumeToolCapture() 尝试提取完整工具调用
│   │   ├─ 成功 → 输出 Event{ToolCalls}，释放 prefix/suffix
│   │   ├─ 未完成（有 open tag 无 close tag）→ 继续缓冲
│   │   └─ 失败（不是工具调用）→ 释放为 Event{Content}
│   └─ 未 ready → break，等待更多数据
│
└─ 如果 capturing=false:
    ├─ findToolSegmentStart() 扫描工具标签起始位置
    │   ├─ 跳过代码围栏内的标签
    │   ├─ 跳过 Markdown 行内 code span 内的标签
    │   └─ 找到 → 输出前缀文本，进入 capturing 模式
    │
    └─ splitSafeContentForToolDetection()
        ├─ 如果末尾有部分 XML 标签 → hold 住不输出
        └─ 否则 → 安全输出为 Event{Content}
```

### 4.3 关键防泄漏机制

1. **代码围栏保护**：维护一个围栏嵌套栈，支持 `` ``` `` 和 `~~~`，支持嵌套（4 反引号嵌套 3 反引号）
2. **行内 code span 保护**：追踪反引号对，`` `<tool_calls>` `` 内的标签不触发
3. **部分标签 hold**：如果 chunk 末尾有 `<|DSM` 这样的不完整标签，hold 住等下一个 chunk
4. **失败释放**：如果捕获的内容最终不是有效工具调用，作为普通文本释放，不吞掉内容
5. **CDATA 内围栏保护**：参数值中的 Markdown 示例不会误触发外层结束标签检测

### 4.4 增量 Delta 发送

流式模式下支持两种工具调用输出方式：
- **Early emit**：检测到工具名后立即发送 `tool_calls` delta（名称 + 参数增量）
- **Final emit**：流结束时通过 `finalize()` 做最终检测并一次性发送

---

## 五、XML 解析的鲁棒性

### 5.1 多层容错

1. **DSML 归一化**：各种 DSML 变体统一归一化为标准 XML
   - `<|DSML|tool_calls>` → `<tool_calls>`
   - `<DSML|tool_calls>` → `<tool_calls>`
   - `<<|DSML|tool_calls>` → `<tool_calls>`
   - `<DSMLtool_calls>` → `<tool_calls>`

2. **Unicode confusable 折叠**：
   - 全角 `＜` → `<`
   - CJK 尖括号 `〈` → `<`
   - 弯引号 → 直引号

3. **缺失 opening wrapper 修复**：
   ```xml
   <!-- 模型输出 -->
   <invoke name="read_file">...</invoke>
   </tool_calls>
   
   <!-- 自动修复为 -->
   <tool_calls>
   <invoke name="read_file">...</invoke>
   </tool_calls>
   ```

4. **Loose CDATA 恢复**：未闭合的 CDATA 在 flush 时尝试修复

### 5.2 参数值解析

- **CDATA 优先**：`<![CDATA[value]]>` 中的内容作为原始字符串
- **JSON 字面量还原**：`123` → number, `true` → boolean, `[1,2]` → array
- **结构化 XML 还原**：`<item>` 列表 → JSON 数组
- **保护长文本参数**：`content`/`command`/`code` 等参数不做结构化解析
- **Schema 归一化**：根据工具 schema 强制转换参数类型

---

## 六、与 QwenRegister 的对比

| 维度 | ds2api | QwenRegister (修复前) |
|------|--------|----------------------|
| 工具调用方式 | 纯 prompt 注入 + XML 解析 | 混合：native FC + XML fallback |
| 流式处理 | 实时筛分，文本立即透传 | 先缓冲完整响应再解析 |
| 防泄漏 | 完整状态机，代码围栏/code span 保护 | 无防泄漏机制 |
| 格式容错 | 多层归一化 + 修复 | 简单正则匹配 |
| 首字时间 | 极低（文本立即透传） | 高（等待完整响应） |
| 工具触发率 | 高（精心设计的 prompt + 示例） | 低（XML 模式下模型不积极） |

---

## 七、可借鉴的改进方向

### 7.1 短期（直接可用）

1. **改进 prompt 注入**：参考 ds2api 的 DSML 指令结构，为 QwenRegister 的 XML 模式设计更好的 prompt
2. **动态示例生成**：根据实际工具名生成针对性示例
3. **Read 工具防循环**：已实现，但可参考 ds2api 的 prompt 级防护

### 7.2 中期（需要重构）

1. **流式 Tool Sieve**：实现类似 ds2api 的状态机，在流式输出中实时检测工具调用
2. **代码围栏保护**：防止模型在代码示例中的 XML 被误识别为工具调用
3. **增量 delta 发送**：检测到工具名后立即开始发送，不等完整参数

### 7.3 长期（架构级）

1. **Go/Node 双链路对齐**：如果 QwenGateway 继续维护，应保持语义一致
2. **Schema 归一化**：根据工具 schema 自动修正参数类型
3. **CDATA 容错**：处理模型输出的各种 CDATA 变体

---

## 八、Qwen 官网 API 行为观察

### 8.1 API 端点

- 创建会话：`POST /api/v2/chats/new`
- 发送消息：`POST /api/chat/completions`（SSE 流式）
- 删除会话：`DELETE /api/v2/chats/{id}`

### 8.2 feature_config 中的 function_calling 字段

Qwen 网页版支持通过 `feature_config.function_calling: true` 开启原生工具调用。开启后：
- 模型会在 SSE 事件中输出 `phase: "tool_call"` 类型的 delta
- 每个 tool_call delta 包含 `extra.tool_call_id`、`content`（JSON 格式的 name/arguments）
- 平台可能拦截某些工具名（返回 "Tool XXX does not exists"）

### 8.3 与 ds2api 的区别

- **Qwen 有原生 FC**：可以直接开启 `function_calling: true`，模型会输出结构化的 tool_call 事件
- **DeepSeek 无原生 FC**：只能通过 prompt 注入 + 文本解析实现
- **QwenRegister 的优势**：可以利用 Qwen 的原生 FC，不需要像 ds2api 那样完全依赖文本解析

### 8.4 建议策略

对于 QwenRegister，最优策略是：
1. **Native-first**：优先使用 Qwen 原生 `function_calling: true`
2. **XML fallback**：被平台拦截时切换到 XML prompt 注入模式
3. **借鉴 ds2api 的 prompt 设计**：XML fallback 模式下使用更好的指令格式

---

## 九、总结

ds2api 的工具调用处理之所以"好"，核心在于：

1. **精心设计的 prompt**：DSML 格式 + 注意力优化结构 + 动态示例
2. **完整的流式防泄漏**：状态机 + 代码围栏保护 + 部分标签 hold
3. **多层容错解析**：Unicode 归一化 + 缺失标签修复 + CDATA 恢复
4. **Schema 感知的输出格式化**：根据工具定义自动修正参数类型

对于 QwenRegister 来说，由于 Qwen 本身支持原生 function calling，不需要完全复制 ds2api 的方案。但其 prompt 设计思路、流式防泄漏机制、和容错解析策略都值得借鉴。
