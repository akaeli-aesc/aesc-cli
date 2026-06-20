# Design Doc: Approval UX Fix

**Status:** Draft
**Author:** Claude
**Date:** 2024-12-07

---

## 1. Problem Statement

Kullanıcı şikayeti: *"10dk oldu 2 tool approval geldi ne oluyor ne bitiyor hiçbir bok göremiyoruz"*

### Mevcut Sorunlar:
1. **Approval panel görünmüyor** - Panel ekleniyor ama fark edilmiyor
2. **y/n/a tuşları çalışmıyor** - Key handling düzgün değil
3. **Progress belirsiz** - Ne kadar süredir çalışıyor belli değil
4. **Subagent activity görünmüyor** - Task tool ne yapıyor belli değil

---

## 2. Proposed Solution

### 2.1 Key Handling Fix

**Problem:** `ChatInput` widget key event'leri yakalıyor ama approval handler'a düzgün iletmiyor.

**Çözüm:**
```python
# ChatInput.on_key()
if self.app._approval_handler:
    if event.key in ("y", "n", "a"):
        handled = self.app._approval_handler(event.key)
        if handled:
            event.prevent_default()
            event.stop()
            return  # Only return if handled
        # If not handled, let key pass to input
```

**Dosyalar:**
- `src/aesc/ui/shell/textual_chat_app.py` - ChatInput.on_key()

### 2.2 Approval Panel Visibility

**Problem:** Panel ekleniyor ama dikkat çekmiyor.

**Çözüm:**
1. Status bar'da `⚠ APPROVAL REQUIRED [y/n/a]` göster
2. Panel'e `>>> ACTION REQUIRED <<<` header ekle
3. Scroll to bottom when panel appears

**Dosyalar:**
- `src/aesc/ui/widgets/approval_panel.py` - Panel render
- `src/aesc/ui/widgets/status_bar.py` - Pending indicator
- `src/aesc/ui/shell/visualize_textual.py` - Status bar integration

### 2.3 Elapsed Time Display

**Problem:** Tool ne kadar süredir çalışıyor belli değil.

**Çözüm:**
```
⟳ Task (reconnaissance) running [45s]
⟳ Task (reconnaissance) running [2m 30s]
```

**Dosyalar:**
- `src/aesc/ui/widgets/tool_call_display.py` - _render_running()

### 2.4 Keyboard Hints

**Problem:** Kullanıcı hangi tuşlara basacağını bilmiyor.

**Çözüm:**
PENDING state'te inline hint göster:
```
? Task (recon) waiting for approval [45s]
  Press: [y]es  [n]o  [a]ll
```

**Dosyalar:**
- `src/aesc/ui/widgets/tool_call_display.py` - render_live() PENDING state

---

## 3. Files Affected

| File | Change |
|------|--------|
| `textual_chat_app.py` | ChatInput key handling fix |
| `approval_panel.py` | Add prominent header |
| `status_bar.py` | Add pending approval indicator |
| `tool_call_display.py` | Elapsed time + keyboard hints |
| `visualize_textual.py` | Status bar integration |

---

## 4. Testing Strategy

### Unit Tests:
```python
# test_approval_key_handling.py
def test_y_key_approves_when_panel_visible():
    ...

def test_y_key_types_when_no_panel():
    ...

def test_elapsed_time_format():
    assert format_elapsed(45) == "45s"
    assert format_elapsed(150) == "2m 30s"
    assert format_elapsed(3700) == "1h 1m"
```

### Integration Tests:
```python
# test_approval_flow.py
async def test_approval_panel_appears_on_risky_tool():
    ...

async def test_approval_panel_disappears_after_response():
    ...
```

### Manual Test Checklist:
- [ ] Run `aesc`, trigger approval (e.g., `rm` command)
- [ ] Verify panel appears and is visible
- [ ] Press `y` - should approve
- [ ] Press `n` - should reject
- [ ] Press `a` - should approve for session
- [ ] Verify elapsed time updates
- [ ] Verify status bar shows indicator

---

## 5. Risks

| Risk | Mitigation |
|------|------------|
| Key events intercepted by other widgets | Test with focus in different states |
| Race condition in panel lifecycle | Use captured reference pattern |
| Status bar not mounted | Check with hasattr before update |

---

## 6. Current Implementation Status

### Already Done:
- [x] Elapsed time added to `_render_running()`
- [x] Keyboard hints in PENDING state
- [x] `>>> ACTION REQUIRED <<<` header in panel
- [x] Status bar indicators (`set_pending_approval`, `set_running_tools`)
- [x] Type annotations fixed (4-tuple)
- [x] Missing methods added (`add_subagent_tab`, `is_system_message`)
- [x] ChatInput key handling fix (return only when handled)

### Not Tested:
- [ ] Live approval flow
- [ ] Status bar updates actually work
- [ ] Keys work in real usage

### Known Issues:
- `add_subagent_tab()` is a stub - not integrated
- `update_subagent_status()` is a stub - not integrated

---

## 7. Acceptance Criteria

1. **Key handling works:** y/n/a approve/reject when panel visible
2. **Panel visible:** User clearly sees approval request
3. **Progress visible:** Elapsed time shown
4. **Hints visible:** User knows which keys to press
5. **Status bar works:** Shows pending indicator
6. **Tests pass:** All existing + new tests green

---

## 8. Design Decisions (Approved)

1. **No sound/bell** - Keyboard only (y/n/a or arrows+enter)
2. **Auto-scroll** - Yes, panel should scroll into view
3. **No blink** - Keep it clean
4. **Panel lifecycle:** Appear → User responds → Disappear → Tool executes
