# Design Doc: Subagent Activity Visibility

**Status:** Draft
**Author:** Claude
**Date:** 2024-12-07

---

## 1. Problem Statement

Task tool (subagent) çalışırken ne yaptığı görünmüyor. Kullanıcı 10 dakika bekliyor, sadece "Task running..." görüyor.

### Mevcut Durum:
```
⟳ Task (reconnaissance) running [5m 23s]
```

### İstenen Durum:
```
⟳ Task (reconnaissance) running [5m 23s]
  ⟳ Bash: nmap -sS 192.168.1.1
      PORT   STATE SERVICE
      22/tcp open  ssh
      80/tcp open  http
  ✓ Bash: whatweb 192.168.1.1
  ⟳ Grep: searching vulns...
  [Ctrl+O to expand]
```

---

## 2. Current Architecture

### Data Flow:
```
MainAgent
    │
    └── Task tool call
            │
            └── Subagent runs (separate context)
                    │
                    ├── Tool calls (Bash, Grep, etc.)
                    ├── Tool results
                    └── Text output
```

### Wire Messages:
```python
# From ashsoul.py - SubagentEvent wraps subagent messages
SubagentEvent(
    task_tool_call_id="...",  # Parent Task tool ID
    event=ToolCallPart(...)   # Actual tool call from subagent
)
```

### Current Handling (visualize_textual.py):
```python
def _handle_subagent_event(self, event: SubagentEvent):
    parent_display = self._tool_displays.get(event.task_tool_call_id)
    if parent_display:
        # Forward to parent's subagent tracking
        if isinstance(event.event, ToolCallPart):
            parent_display.add_subagent_tool_call(...)
        elif isinstance(event.event, ToolResultPart):
            parent_display.finish_subagent_tool_call(...)
```

### Current ToolCallDisplay:
```python
class ToolCallDisplay:
    _subagent_tools: list[tuple[ToolCall, ToolReturnType | None]]
    _subagent_output: str
    _subagent_thinking: str
    _subagent_live_outputs: dict[str, str]
    _show_expanded_subagent: bool  # Toggle with Ctrl+O
```

---

## 3. What's Already Implemented

### In tool_call_display.py:
- [x] `_subagent_tools` tracking
- [x] `_render_subagent_activity()` method
- [x] Collapsed view (last 5 tools)
- [x] Expanded view (Ctrl+O toggle)
- [x] Live output streaming per tool
- [x] Thinking display

### In visualize_textual.py:
- [x] `_handle_subagent_event()` dispatches events
- [x] Tool calls forwarded to parent display
- [x] Results forwarded to parent display

---

## 4. What's NOT Working

### 4.1 SubagentEvent Not Being Sent

**Problem:** `ashsoul.py` may not be wrapping subagent events properly.

**Check:** Does the wire message queue receive SubagentEvent?

### 4.2 Parent Display Not Found

**Problem:** `event.task_tool_call_id` might not match `_tool_displays` keys.

**Check:** Are tool call IDs consistent?

### 4.3 Render Not Updating

**Problem:** Subagent activity tracked but not rendered.

**Check:** Does `_render_running()` call `_render_subagent_activity()`?

### 4.4 Stub Methods

**Problem:** `add_subagent_tab()` and `update_subagent_status()` are stubs.

**Decision:** Do we need these? Or is inline display enough?

---

## 5. Proposed Investigation

Before implementing, we need to verify the data flow:

### Step 1: Add Debug Logging
```python
# visualize_textual.py
def _handle_subagent_event(self, event: SubagentEvent):
    logger.debug(f"SubagentEvent: task_id={event.task_tool_call_id}, event={type(event.event)}")
    ...
```

### Step 2: Verify Event Types
```python
# Check which event types we receive
- ToolCallPart (new tool call)
- ToolResultPart (tool finished)
- ContentPart (text output)
- ThinkingPart (thinking)
```

### Step 3: Manual Test
```bash
aesc
> scan 192.168.1.1 with nmap  # Should trigger Task -> reconnaissance
# Watch for subagent activity display
```

---

## 6. Implementation Plan

### Phase 1: Verify Data Flow
1. Add debug logging to `_handle_subagent_event`
2. Run aesc and trigger a Task tool
3. Check logs to see what events arrive

### Phase 2: Fix Event Handling (if needed)
1. Ensure SubagentEvent is sent from ashsoul.py
2. Ensure tool_call_id matches
3. Ensure parent display is found

### Phase 3: Verify Rendering
1. Confirm `_render_subagent_activity()` is called
2. Confirm output is visible
3. Test Ctrl+O toggle

### Phase 4: Polish
1. Remove stub methods or implement properly
2. Add tests
3. Manual testing

---

## 7. Files to Check

| File | What to Check |
|------|---------------|
| `ashsoul.py` | SubagentEvent creation and sending |
| `visualize_textual.py` | Event dispatch and handling |
| `tool_call_display.py` | Subagent tracking and rendering |
| `wire/message.py` | SubagentEvent definition |

---

## 8. Testing Strategy

### Debug Test:
```python
# tests/test_subagent_visibility.py
async def test_subagent_event_forwarded_to_parent():
    """Verify SubagentEvent reaches parent ToolCallDisplay."""
    ...

async def test_subagent_tools_rendered():
    """Verify subagent tools appear in parent's render output."""
    ...
```

### Manual Test Checklist:
- [ ] Trigger Task tool (e.g., "do recon on X")
- [ ] Verify subagent tools appear under Task
- [ ] Verify live output streams
- [ ] Test Ctrl+O expand/collapse
- [ ] Verify elapsed time on subagent tools

---

## 9. Decision: SubagentTabs Widget

### Option A: Remove SubagentTabs
- Just use inline display in ToolCallDisplay
- Simpler, already partially working
- Remove stubs `add_subagent_tab()`, `update_subagent_status()`

### Option B: Implement SubagentTabs
- Separate tabs for each subagent
- More complex but better for multiple concurrent subagents
- Need to mount widget, manage state

**Recommendation:** Start with Option A (inline), move to B if needed.

---

## 10. Acceptance Criteria

1. **Subagent tools visible:** User sees what subagent is doing
2. **Live output:** Streaming output from subagent tools
3. **Toggle works:** Ctrl+O expands/collapses
4. **Performance:** No lag with many subagent tools
5. **Tests pass:** Existing + new tests

---

## 11. Design Decisions (Approved)

1. **Verify data flow first** - Add debug logging, test manually
2. **Inline display** - Option A, integrate nicely within Task tool display
3. **Multiple Tasks** - Each Task shows its own subagent activity inline
4. **Show thinking** - Yes, helps user understand what's happening
5. **Remove stubs** - If not needed, clean up; if needed, implement properly
