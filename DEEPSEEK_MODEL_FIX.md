# DeepSeek Model Fix

## Issue

**Error**: `Error code: 400 - {'error': {'message': 'Missing 'reasoning_content' field in the assistant message at message index 50.`

## Root Cause

The `deepseek-reasoner` model requires a special `reasoning_content` field in all assistant messages. When using LangGraph with:
- Tool calls
- Conversation history/persistence
- Multiple message exchanges

The framework generates messages that don't include this field, causing the API to reject requests.

## Solution

Switch from `deepseek-reasoner` to `deepseek-chat` for agents that:
1. Use tools (function calling)
2. Maintain conversation history
3. Have multi-turn dialogues

### Changes Made

#### 1. Main Agent (line ~1233)
```python
# Before
llm = ChatOpenAI(
    model="deepseek-reasoner",
    ...
)

# After
llm = ChatOpenAI(
    model="deepseek-chat",  # Better for tool-calling workflows
    ...
)
```

#### 2. Reviewer Agent (line ~1442)
```python
# Before
reviewer_llm = ChatOpenAI(
    model="deepseek-reasoner",
    ...
)

# After
reviewer_llm = ChatOpenAI(
    model="deepseek-chat",  # Simpler and more reliable
    ...
)
```

### Models Kept as `deepseek-reasoner`

The following functions still use `deepseek-reasoner` because they are single-shot tasks without conversation history:

1. **`break_goal_into_tasks`** (line ~313)
   - One-shot task breakdown
   - No tool calls in conversation
   - No message history

2. **`confirm_and_create_goal`** (line ~716)
   - One-shot task breakdown
   - No conversation history

3. **`generate_checkin_message_with_context`** (line ~1807)
   - One-shot message generation
   - No tool calls
   - No conversation history

## When to Use Each Model

### Use `deepseek-chat`:
- ✅ LangGraph agents with tools
- ✅ Conversation history/persistence
- ✅ Multi-turn dialogues
- ✅ Standard chat applications

### Use `deepseek-reasoner`:
- ✅ Single-shot complex reasoning tasks
- ✅ Tasks requiring step-by-step thinking
- ✅ No conversation history needed
- ✅ No tool calls involved

## Testing the Fix

After making these changes:

1. **Test basic conversation**:
   ```bash
   python test_agent.py
   ```
   Try: "Show me my tasks" or "Create a goal to learn Python"

2. **Test with tool calls**:
   - Create a goal (triggers tool calls)
   - Ask about tasks (triggers database queries)
   - Update task status

3. **Test conversation persistence**:
   - Send multiple messages in sequence
   - Verify no 400 errors occur
   - Check that context is maintained

4. **Monitor logs**:
   Look for successful LLM calls without reasoning_content errors

## Expected Results

- ✅ No more `Missing 'reasoning_content' field` errors
- ✅ Smooth tool calling
- ✅ Proper conversation history handling
- ✅ Reviewer agent works correctly
- ✅ All features functional

## Performance Impact

**None.** The `deepseek-chat` model is:
- Just as capable for chat/tool-calling tasks
- More reliable in LangGraph workflows
- Same pricing as deepseek-reasoner
- Better suited for the use case

## Additional Notes

### LangGraph Message Format

LangGraph stores messages in this format:
```python
{
    "messages": [
        HumanMessage(content="..."),
        AIMessage(content="...", tool_calls=[...]),
        ToolMessage(content="...", tool_call_id="..."),
        AIMessage(content="...")
    ]
}
```

The `deepseek-reasoner` model expects:
```python
AIMessage(
    content="...",
    reasoning_content="...",  # This field is required!
    tool_calls=[...]
)
```

LangGraph doesn't automatically add `reasoning_content`, causing the error.

### Alternative Solutions (Not Recommended)

1. **Message preprocessing**: Add `reasoning_content` to all messages before sending
   - Complex
   - Error-prone
   - Maintenance burden

2. **Disable conversation history**: Use only single-shot interactions
   - Loses context
   - Poor user experience
   - Defeats purpose of persistence

3. **Custom message handler**: Intercept and modify messages
   - Hacky
   - Hard to maintain
   - May break with updates

**Conclusion**: Switching to `deepseek-chat` is the cleanest and most maintainable solution.

## References

- [DeepSeek API Documentation](https://platform.deepseek.com/api-docs/)
- [LangChain ChatOpenAI](https://python.langchain.com/docs/integrations/chat/openai)
- [LangGraph Tool Calling](https://langchain-ai.github.io/langgraph/how-tos/tool-calling/)
