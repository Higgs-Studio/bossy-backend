# Reviewer Agent Feature

## Overview

A reviewer agent has been added to the LangGraph workflow to act as a gatekeeper that reviews all output messages before they are sent to users. This ensures message quality and prevents confusing, contradictory, or low-quality responses from reaching users.

## How It Works

### Graph Flow

The updated graph flow is:

```
User Input → Agent → Tools (if needed) → Agent → Reviewer → Output
                ↑                           ↓          ↓
                └──────── Rework ───────────┘          └─→ Approve → END
```

1. **Agent Node**: Processes user input and calls tools as needed
2. **Tools Node**: Executes tool calls (e.g., database operations)
3. **Agent Node** (again): Generates final response after tool execution
4. **Reviewer Node**: Reviews the agent's response for quality
5. **Outcome**:
   - **APPROVE**: Response is sent to user
   - **REWORK**: Response is sent back to agent with specific feedback

### Reviewer Quality Checks

The reviewer evaluates responses based on:

1. **Clarity and Actionability**: Is the message clear and does it provide actionable guidance?
2. **Personality Match**: Does it match the expected tone (execution-focused, not overly friendly)?
3. **Consistency**: Are there any contradictions or confusing information?
4. **Context Appropriateness**: Does it reference actual data/context or make unfounded assumptions?
5. **WhatsApp Optimization**: Is it concise and appropriate for WhatsApp messaging?
6. **Relevance**: Does it actually address what the user asked?

### Safety Mechanisms

- **Max Iterations**: Limited to 2 review iterations to prevent infinite loops
- **Fallback Approval**: If the reviewer's response is unclear, the message is approved by default
- **State Tracking**: `review_count` tracks the number of review iterations

## State Changes

### Updated `AgentState`

```python
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    user_id: str
    reviewer_feedback: Optional[str]  # Feedback from reviewer for rework
    review_count: int  # Track number of review iterations
```

### New State Fields

- **`reviewer_feedback`**: Contains specific feedback from the reviewer when rework is needed
- **`review_count`**: Tracks how many times a message has been reviewed (prevents infinite loops)

## Code Changes

### 1. Updated Agent Node

The `call_model` function now:
- Retrieves `reviewer_feedback` from state
- Appends reviewer feedback to the system prompt when rework is needed
- Clears `reviewer_feedback` after incorporating it

### 2. New Reviewer Node

The `review_output` function:
- Extracts the agent's response
- Uses DeepSeek LLM to review quality
- Returns either APPROVE or REWORK with specific feedback
- Enforces max iteration limit

### 3. Updated Routing Logic

**`should_continue`** (from agent):
- Routes to `tools` if there are tool calls
- Routes to `reviewer` if no tool calls (previously went to END)

**`reviewer_decision`** (from reviewer):
- Routes back to `agent` if there's feedback (rework needed)
- Routes to `END` if approved

### 4. Updated Graph Structure

```python
# Add reviewer node
workflow.add_node("reviewer", review_output)

# Agent routes to tools or reviewer
workflow.add_conditional_edges(
    "agent",
    should_continue,
    {
        "tools": "tools",
        "reviewer": "reviewer"
    }
)

# Reviewer routes to agent (rework) or END (approve)
workflow.add_conditional_edges(
    "reviewer",
    reviewer_decision,
    {
        "agent": "agent",
        END: END
    }
)
```

## Example Scenarios

### Scenario 1: Approved Response

```
User: "What are my tasks for today?"
Agent: "Here are your tasks for today: 1. Complete project proposal (high priority) 2. Review team feedback..."
Reviewer: "APPROVE"
→ Message sent to user
```

### Scenario 2: Rework Needed

```
User: "Did I complete my workout task?"
Agent: "Yes, you completed your task successfully!"
Reviewer: "REWORK: The response references a completed task but no task data was retrieved. Verify with the database first."
Agent (rework): "Let me check your tasks..." [calls find_task_by_description tool] "I found your workout task..."
Reviewer: "APPROVE"
→ Message sent to user
```

### Scenario 3: Max Iterations Reached

```
Review iteration 1: REWORK
Review iteration 2: REWORK
→ Max iterations (2) reached, approve by default to prevent infinite loop
→ Message sent to user with warning logged
```

## Benefits

1. **Quality Assurance**: Catches low-quality, confusing, or contradictory responses
2. **Context Verification**: Ensures responses are based on actual data, not assumptions
3. **Personality Consistency**: Maintains the expected boss/accountability tone
4. **Error Prevention**: Reduces messages that reference non-existent data
5. **User Experience**: Improves overall message quality and clarity

## Configuration

### Reviewer Settings

- **Model**: `deepseek-reasoner` (same as main agent)
- **Temperature**: `0.3` (lower for more consistent reviews vs. 0.7 for main agent)
- **Max Iterations**: `2` (configurable via `MAX_REVIEW_ITERATIONS`)

### Logging

The reviewer logs its decisions:
```python
logger.info(f"Reviewer decision (iteration {review_count + 1}): {review_result}")
```

This helps with debugging and monitoring review patterns.

## Future Enhancements

Potential improvements:
1. **Metrics Tracking**: Track approval/rework rates
2. **User-Specific Review Criteria**: Adjust review criteria based on user preferences
3. **Review History**: Store review feedback for analysis
4. **Dynamic Max Iterations**: Adjust based on message complexity
5. **Multi-Stage Review**: Different reviewers for different aspects (tone, accuracy, etc.)

## Testing

To test the reviewer agent:

1. Send a message that would trigger a quality issue (e.g., vague response, contradictory info)
2. Check logs for reviewer decisions
3. Verify that reworked messages are improved
4. Test max iteration safety mechanism

Example test scenarios:
- Vague or generic responses
- Responses with contradictory information
- Responses referencing non-existent data
- Overly friendly or off-tone responses
- Very long responses (not WhatsApp-friendly)
