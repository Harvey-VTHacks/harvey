#!/usr/bin/env python3

import os
import sys
import time
import subprocess
import math
import base64
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from agent.screenshot import capture_to_bytes
from agent.llm import get_gemini_client

# Optional TTS support for spoken rationales
_TTS_AVAILABLE = True
try:
    # Import the speak helper from TTS_STT
    from TTS_STT.speak import speak as tts_speak
except Exception:
    _TTS_AVAILABLE = False

try:
    from Quartz import CGEventCreateMouseEvent, CGEventPost, kCGHIDEventTap, kCGEventLeftMouseDown, kCGEventLeftMouseUp, CGEventCreateKeyboardEvent, kCGEventKeyDown, kCGEventKeyUp, CGEventSetFlags, kCGEventFlagMaskCommand, kCGEventMouseMoved
    from Quartz.CoreGraphics import CGMainDisplayID, CGDisplayBounds, CGEventCreate, CGEventGetLocation
    _QUARTZ_AVAILABLE = True
except ImportError:
    _QUARTZ_AVAILABLE = False

def get_screen_info():
    """Get screen size in points and pixels to determine the exact scaling factor."""
    if _QUARTZ_AVAILABLE:
        from Quartz.CoreGraphics import (
            CGMainDisplayID,
            CGDisplayBounds,
            CGDisplayCopyDisplayMode,
            CGDisplayModeGetPixelWidth,
            CGDisplayModeGetPixelHeight,
        )

        display_id = CGMainDisplayID()

        # Logical dimensions (points)
        bounds = CGDisplayBounds(display_id)
        logical_width = int(bounds.size.width)
        logical_height = int(bounds.size.height)

        # Physical dimensions (pixels)
        mode = CGDisplayCopyDisplayMode(display_id)
        pixel_width = int(CGDisplayModeGetPixelWidth(mode)) if mode else logical_width
        pixel_height = int(CGDisplayModeGetPixelHeight(mode)) if mode else logical_height

        # Precise scale factor (e.g., 2.0 on Retina)
        scale = (pixel_width / logical_width) if logical_width else 1.0

        # Return logical size for event coordinates, plus scale for diagnostics
        return logical_width, logical_height, scale
    # Fallback for non-macOS systems
    return 1920, 1080, 1.0

def get_screen_size():
    """Get screen size (for backward compatibility)."""
    width, height, _ = get_screen_info()
    return width, height

def _transform_coords(x_ratio, y_ratio):
    """Transform ratios (top-left origin) to Quartz screen coordinates (top-left origin)."""
    width, height, scale = get_screen_info()

    # Clamp ratios
    x_ratio = max(0.0, min(1.0, float(x_ratio)))
    y_ratio = max(0.0, min(1.0, float(y_ratio)))

    # Convert to points (no Y flip; CGEvent global coords use top-left origin)
    x = int(round(x_ratio * (width - 1)))
    y = int(round(y_ratio * (height - 1)))

    print(f"🎯 Ratio ({x_ratio:.3f}, {y_ratio:.3f}) -> Screen ({x}, {y}) [Points: {width}x{height}, Scale: {scale:.1f}x]")
    return x, y

def get_current_mouse_position():
    if _QUARTZ_AVAILABLE:
        event = CGEventCreate(None)
        pos = CGEventGetLocation(event)
        return int(pos.x), int(pos.y)
    return 100, 100

def smooth_move_mouse(start_x, start_y, end_x, end_y):
    if not _QUARTZ_AVAILABLE:
        return
    distance = math.sqrt((end_x - start_x)**2 + (end_y - start_y)**2)
    if distance < 5:
        return
    steps = max(10, int(distance / 15))
    
    for i in range(steps + 1):
        t = i / steps
        t_smooth = t * t * (3 - 2 * t)

        control_x = (start_x + end_x) / 2 + (end_y - start_y) * 0.1
        control_y = (start_y + end_y) / 2 - (end_x - start_x) * 0.1

        x = int((1 - t_smooth) ** 2 * start_x + 2 * (1 - t_smooth) * t_smooth * control_x + t_smooth ** 2 * end_x)
        y = int((1 - t_smooth) ** 2 * start_y + 2 * (1 - t_smooth) * t_smooth * control_y + t_smooth ** 2 * end_y)

        event = CGEventCreateMouseEvent(None, kCGEventMouseMoved, (x, y), 0)
        CGEventPost(kCGHIDEventTap, event)
        time.sleep(0.01)

def move_mouse(x_ratio, y_ratio):
    if not _QUARTZ_AVAILABLE:
        return
    x, y = _transform_coords(x_ratio, y_ratio)
    current_x, current_y = get_current_mouse_position()
    smooth_move_mouse(current_x, current_y, x, y)

def _is_spotlight_active():
    try:
        result = subprocess.run(['osascript', '-e', 'tell application "System Events" to get name of first process whose frontmost is true'], 
                              capture_output=True, text=True, check=True)
        frontmost = result.stdout.strip()
        return frontmost == "Spotlight" or "Spotlight" in frontmost
    except:
        return False

def _handle_spotlight_click(x_ratio, y_ratio):
    print("🔍 Spotlight: Using Enter to select first result (simplest path)")
    hotkey("return")

def calibrate_click_position(x, y):
    """Apply optional calibration offsets via HARVEY_X_OFFSET and HARVEY_Y_OFFSET (points)."""
    try:
        offset_x = float(os.getenv("HARVEY_X_OFFSET", "0"))
        offset_y = float(os.getenv("HARVEY_Y_OFFSET", "0"))
    except Exception:
        offset_x, offset_y = 0.0, 0.0
    return int(x + offset_x), int(y + offset_y)

def _write_env_offsets(offset_x: int, offset_y: int) -> bool:
    """Create or update .env with HARVEY_X_OFFSET/Y_OFFSET values."""
    try:
        env_path = Path(".env")
        lines = []
        if env_path.exists():
            lines = env_path.read_text().splitlines()

        def set_or_replace(lines, key, value):
            found = False
            for i, line in enumerate(lines):
                if line.strip().startswith(f"{key}="):
                    lines[i] = f"{key}={value}"
                    found = True
                    break
            if not found:
                lines.append(f"{key}={value}")
            return lines

        lines = set_or_replace(lines, "HARVEY_X_OFFSET", str(int(offset_x)))
        lines = set_or_replace(lines, "HARVEY_Y_OFFSET", str(int(offset_y)))

        # Ensure trailing newline
        env_path.write_text("\n".join(lines) + "\n")
        return True
    except Exception as e:
        print(f"❌ Could not write .env: {e}")
        return False

def calibrate_interactive():
    """Interactive calibration: align to visual center and record offsets."""
    if not _QUARTZ_AVAILABLE:
        print("❌ Calibration requires macOS Quartz events.")
        return

    print("🧭 Calibration mode\n- We'll move the cursor to the computed screen center.\n- If it's not visually centered, manually move the cursor to the true center, then press Enter.\n- We'll compute offsets and optionally save them to .env.")

    # Move to computed center
    expected_x, expected_y = _transform_coords(0.5, 0.5)
    cur_x, cur_y = get_current_mouse_position()
    smooth_move_mouse(cur_x, cur_y, expected_x, expected_y)
    print(f"🎯 Moved to computed center at ({expected_x}, {expected_y}).")

    resp = input("Is the cursor exactly at the screen center? [y/N]: ").strip().lower()
    if resp == "y":
        print("✅ No offsets needed. If you previously set HARVEY_X_OFFSET/Y_OFFSET, you may remove them from .env.")
        return

    input("👉 Manually move the cursor to the true visual center, then press Enter to capture...")
    final_x, final_y = get_current_mouse_position()
    off_x = int(final_x - expected_x)
    off_y = int(final_y - expected_y)

    print(f"📐 Computed offsets: HARVEY_X_OFFSET={off_x}, HARVEY_Y_OFFSET={off_y}")

    # Preview: apply offsets and re-center
    preview_x = expected_x + off_x
    preview_y = expected_y + off_y
    cur_x, cur_y = get_current_mouse_position()
    smooth_move_mouse(cur_x, cur_y, preview_x, preview_y)
    print(f"👀 Preview applied at ({preview_x}, {preview_y}).")
    confirm = input("Does this look perfectly centered now? Save to .env? [y/N]: ").strip().lower()
    if confirm == "y":
        if _write_env_offsets(off_x, off_y):
            print("💾 Saved to .env. These offsets will be applied on the next run (dotenv loads on startup).")
        else:
            print("⚠️ Failed to write .env. Set these manually or rerun calibration.")
    else:
        print("📝 Offsets not saved. Re-run calibration if needed.")

def ultra_precise_click(x_ratio, y_ratio):
    """Ultra-precise click with position verification and calibration."""
    if not _QUARTZ_AVAILABLE:
        x, y = _transform_coords(x_ratio, y_ratio)
        print(f"🖱️ Click at ({x}, {y}) (simulated)")
        return
    
    if _is_spotlight_active():
        print("🔍 Spotlight active - using Enter instead of clicking")
        hotkey("return")
        return
    
    # Transform and calibrate coordinates
    x, y = _transform_coords(x_ratio, y_ratio)
    x, y = calibrate_click_position(x, y)
    
    print(f"🎯 Ultra-precise clicking at ({x}, {y})")
    
    # Move to position with higher precision
    current_x, current_y = get_current_mouse_position()
    smooth_move_mouse(current_x, current_y, x, y)
    time.sleep(0.15)  # Slightly longer pause for precision
    
    # Verify we're at the right position and DON'T move again if close enough
    final_x, final_y = get_current_mouse_position()
    if abs(final_x - x) > 5 or abs(final_y - y) > 5:  # Increased tolerance
        print(f"⚠️  Position drift detected: expected ({x}, {y}), got ({final_x}, {final_y})")
        # Only correct if drift is significant
        smooth_move_mouse(final_x, final_y, x, y)
        time.sleep(0.05)  # Shorter wait
    
    # Get final position for click event
    click_x, click_y = get_current_mouse_position()
    
    # Perform the click with error handling
    try:
        down_event = CGEventCreateMouseEvent(None, kCGEventLeftMouseDown, (click_x, click_y), 0)
        up_event = CGEventCreateMouseEvent(None, kCGEventLeftMouseUp, (click_x, click_y), 0)
        
        CGEventPost(kCGHIDEventTap, down_event)
        time.sleep(0.05)
        CGEventPost(kCGHIDEventTap, up_event)
        
        print(f"✅ Ultra-precise click completed at ({click_x}, {click_y})")
    except Exception as e:
        print(f"❌ Click failed: {e}")

def precise_click(x_ratio, y_ratio):
    """Main precise click function - uses ultra-precise system."""
    ultra_precise_click(x_ratio, y_ratio)

def left_click(x_ratio, y_ratio):
    """Main click function - uses ultra-precise clicking system."""
    ultra_precise_click(x_ratio, y_ratio)

def double_click(x_ratio, y_ratio):
    """Perform an ultra-precise double-click."""
    if not _QUARTZ_AVAILABLE:
        x, y = _transform_coords(x_ratio, y_ratio)
        print(f"🖱️ Double-click at ({x}, {y}) (simulated)")
        return
    
    # Transform and calibrate coordinates
    x, y = _transform_coords(x_ratio, y_ratio)
    x, y = calibrate_click_position(x, y)
    
    print(f"⚡ Ultra-precise double-clicking at ({x}, {y})")
    
    # Move to position with precision
    current_x, current_y = get_current_mouse_position()
    smooth_move_mouse(current_x, current_y, x, y)
    time.sleep(0.2)
    
    # Verify position
    final_x, final_y = get_current_mouse_position()
    if abs(final_x - x) > 2 or abs(final_y - y) > 2:
        print(f"⚠️  Position correction for double-click")
        smooth_move_mouse(final_x, final_y, x, y)
        time.sleep(0.1)
    
    # Perform double-click
    try:
        for _ in range(2):
            down_event = CGEventCreateMouseEvent(None, kCGEventLeftMouseDown, (x, y), 0)
            up_event = CGEventCreateMouseEvent(None, kCGEventLeftMouseUp, (x, y), 0)
            CGEventPost(kCGHIDEventTap, down_event)
            time.sleep(0.05)
            CGEventPost(kCGHIDEventTap, up_event)
            time.sleep(0.1)  # Brief pause between clicks
        print(f"⚡ Ultra-precise double-click completed at ({x}, {y})")
    except Exception as e:
        print(f"❌ Double-click failed: {e}")

def hover(x_ratio, y_ratio):
    """Move mouse to position and hover (for tooltips, menus, etc.)."""
    if not _QUARTZ_AVAILABLE:
        x, y = _transform_coords(x_ratio, y_ratio)
        print(f"👆 Hover at ({x}, {y}) (simulated)")
        return
    
    x, y = _transform_coords(x_ratio, y_ratio)
    print(f"👆 Hovering at ({x}, {y})")
    
    current_x, current_y = get_current_mouse_position()
    smooth_move_mouse(current_x, current_y, x, y)
    time.sleep(0.5)  # Hold position for hover effects
    print(f"✅ Hover completed at ({x}, {y})")

def type_text(text):
    if not _QUARTZ_AVAILABLE:
        print(f"⌨️ Typed: {text} (simulated)")
        return
        
    print(f"⌨️ Typing: {text}")
    
    key_map = {
        ' ': 49, 'a': 0, 'b': 11, 'c': 8, 'd': 2, 'e': 14, 'f': 3, 'g': 5, 'h': 4, 'i': 34, 'j': 38,
        'k': 40, 'l': 37, 'm': 46, 'n': 45, 'o': 31, 'p': 35, 'q': 12, 'r': 15, 's': 1,
        't': 17, 'u': 32, 'v': 9, 'w': 13, 'x': 7, 'y': 16, 'z': 6,
        '1': 18, '2': 19, '3': 20, '4': 21, '5': 23, '6': 22, '7': 26, '8': 28, '9': 25, '0': 29,
        '.': 47, '/': 44, '-': 27, '=': 24
    }
    
    for char in text:
        char_lower = char.lower()
        if char_lower in key_map:
            key_code = key_map[char_lower]
            
            try:
                down = CGEventCreateKeyboardEvent(None, key_code, True)
                up = CGEventCreateKeyboardEvent(None, key_code, False)
                
                # Only apply shift for actual uppercase letters, not for typing in general
                if char.isupper() and char.isalpha():
                    CGEventSetFlags(down, 131072)  # shift flag only for caps
                    CGEventSetFlags(up, 0)  # clear flags on release
                else:
                    CGEventSetFlags(down, 0)  # no flags for lowercase
                    CGEventSetFlags(up, 0)
                    
                CGEventPost(kCGHIDEventTap, down)
                time.sleep(0.02)
                CGEventPost(kCGHIDEventTap, up)
                time.sleep(0.03)
            except Exception as e:
                print(f"⌨️ Error typing '{char}': {e}")
        else:
            print(f"⌨️ Character '{char}' not mapped")
        time.sleep(0.02)

def hotkey(key_combo):
    if not _QUARTZ_AVAILABLE:
        print(f"🔥 Hotkey: {key_combo} (simulated)")
        return
        
    key_codes = {
        'space': 49, 'return': 36, 'enter': 36, 'tab': 48,
        'a': 0, 'b': 11, 'c': 8, 'd': 2, 'e': 14, 'f': 3, 'g': 5, 'h': 4, 'i': 34, 'j': 38,
        'k': 40, 'l': 37, 'm': 46, 'n': 45, 'o': 31, 'p': 35, 'q': 12, 'r': 15, 's': 1,
        't': 17, 'u': 32, 'v': 9, 'w': 13, 'x': 7, 'y': 16, 'z': 6,
        '1': 18, '2': 19, '3': 20, '4': 21, '5': 23, '6': 22, '7': 26, '8': 28, '9': 25, '0': 29
    }
    
    try:
        if "+" in key_combo:
            parts = key_combo.split("+")
            modifiers = parts[:-1]
            key = parts[-1].lower()
            
            if key in key_codes:
                key_code = key_codes[key]
                
                down = CGEventCreateKeyboardEvent(None, key_code, True)
                up = CGEventCreateKeyboardEvent(None, key_code, False)
                
                flags = 0
                if "cmd" in modifiers or "command" in modifiers:
                    flags |= kCGEventFlagMaskCommand
                if "shift" in modifiers:
                    flags |= 131072  # shift flag
                if "alt" in modifiers or "option" in modifiers:
                    flags |= 524288  # option flag
                if "ctrl" in modifiers or "control" in modifiers:
                    flags |= 262144  # control flag
                
                if flags:
                    CGEventSetFlags(down, flags)
                    CGEventSetFlags(up, 0)  # Clear flags on key release
                
                CGEventPost(kCGHIDEventTap, down)
                time.sleep(0.02)
                CGEventPost(kCGHIDEventTap, up)
                print(f"🔥 Hotkey: {key_combo}")
            else:
                print(f"🔥 Hotkey: {key_combo} (key not mapped)")
        elif key_combo.lower() in key_codes:
            key_code = key_codes[key_combo.lower()]
            down = CGEventCreateKeyboardEvent(None, key_code, True)
            up = CGEventCreateKeyboardEvent(None, key_code, False)
            CGEventPost(kCGHIDEventTap, down)
            time.sleep(0.02)
            CGEventPost(kCGHIDEventTap, up)
            print(f"🔥 Hotkey: {key_combo}")
        else:
            print(f"🔥 Hotkey: {key_combo} (not implemented)")
    except Exception as e:
        print(f"❌ Hotkey failed: {e}")

class Harvey:
    def __init__(self):
        self.client = get_gemini_client()
        self.model = "gemini-flash-latest"
        self.last_see = ""
        
    def think(self, task, screenshot_data):
        prompt = f"""You are Harvey, a macOS automation assistant.

TASK: {task}

Look at the current screen carefully. First, briefly describe what you see in 2-3 words (like "Desktop visible", "Arc browser open", "Spotlight search active").

Then decide what to do next. 

Format your response as:
See: [brief description of what's on screen]
Action: [your action]

Actions available:
- move_mouse(ratio_x, ratio_y) - move cursor using screen ratios (0.00 to 1.00)
- left_click(ratio_x, ratio_y) - precise click using enhanced grid coordinates
- double_click(ratio_x, ratio_y) - double-click for opening items
- hover(ratio_x, ratio_y) - hover over element to reveal tooltips/menus
- type_text("hello") - type text
- hotkey("cmd+space") - press key combo
- focus_address_bar() - focus browser address bar with cmd+l
- wait(1000) - wait milliseconds
- done() - task complete

CRITICAL COMPLETION RULES:
- NEVER call done() unless you have ACTUALLY COMPLETED every single step
- For email tasks: done() ONLY after you have:
  1. Clicked the Compose button
  2. Clicked in the Subject field AND typed the subject text
  3. Clicked in the Message body field AND typed the message content
- If you see empty fields that need text, DO NOT call done()
- If the task asks for specific text to be typed, you must TYPE IT
- When in doubt, continue working - do not call done() prematurely

EMAIL WORKFLOW - FOLLOW EXACTLY:
- Step 1: Navigate to Gmail and click the Compose button
- Step 2: Click in the Subject field (usually near top of compose dialog)
- Step 3: Type the requested subject text with type_text()
- Step 4: Click in the Message body field (larger text area below subject)
- Step 5: Type the requested message content with type_text()
- Step 6: ONLY then call done()

CRITICAL SPOTLIGHT WORKFLOW:
- Step 1: If desktop is visible, use hotkey("cmd+space") to open Spotlight
- Step 2: If Spotlight is open (search bar visible), type the app name with type_text("App Name")
- Step 3: After typing, press hotkey("enter") to launch the app
- NEVER click on Spotlight results - always use enter key

CRITICAL BROWSER WORKFLOW:
- Step 1: If Safari/browser is open, use hotkey("cmd+t") to open a new tab
- Step 2: The new tab automatically focuses the address bar
- Step 3: Type your search term directly with type_text("search term")
- Step 4: Press hotkey("enter") to search
- NEVER use focus_address_bar() - use cmd+t instead

ULTRA-PRECISE GRID SYSTEM FOR CLICKING:
- The screenshot has a HIGH-RESOLUTION GRID OVERLAY (20x20 grid instead of 10x10)
- RED major grid lines every 5th line, lighter red minor lines in between
- GREEN crosshairs mark precise center points between grid lines
- Grid coordinates range from (0.00,0.00) to (1.00,1.00) with 2 decimal precision
- Look for coordinate labels like (0.25,0.35) for exact positioning

ENHANCED CLICKING ACCURACY RULES:
- Always aim for the VISUAL CENTER of the target element (button, icon, link).
- Use the GREEN crosshairs as primary target points (they mark centers between grid lines).
- If an element's center isn't on a crosshair, estimate position relative to lines using two decimals (e.g., left_click(0.47, 0.61)).
- Prefer precise center clicks over edge clicks to avoid misses.
- In your See: line, briefly name the target (e.g., "See: Subject field empty").

ELEMENT TARGETING STRATEGY:
- Small buttons: Use exact grid coordinates where the button center aligns
- Large buttons: Use center point with 2 decimal precision
- Links/text: Click on the text center using precise grid positioning
- Icons: Target the icon center using crosshair markers as guides

GRID COORDINATE SYSTEM:
- Top-left corner: (0.0, 0.0)
- Center: (0.5, 0.5) 
- Bottom-right: (1.0, 1.0)
- Use the visible grid labels for exact positioning

Example response:
See: Desktop with dock
Action: hotkey("cmd+space")"""

        try:
            from google.genai import types
            
            contents = [
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_text(text=prompt),
                        types.Part.from_bytes(
                            data=base64.b64decode(screenshot_data),
                            mime_type="image/jpeg"
                        ),
                    ],
                ),
            ]
            
            response = self.client.models.generate_content(
                model=self.model,
                contents=contents,
            )
            
            response_text = response.text.strip()
            
            # Parse the response to extract observation and action
            lines = response_text.split('\n')
            see_line = ""
            action = ""
            
            for line in lines:
                if line.startswith("See:"):
                    see_line = line[4:].strip()
                elif line.startswith("Action:"):
                    action = line[7:].strip()
                elif not see_line and not action and line.strip():
                    # Fallback if format isn't followed
                    action = line.strip()
            
            # Print what Harvey observes
            if see_line:
                print(f"👁️  Harvey sees: {see_line}")
            # Remember for rationale speech
            self.last_see = see_line
            
            return action if action else response_text.strip()
            
        except Exception as e:
            error_str = str(e)
            print(f"LLM Error: {e}")
            
            # Handle rate limiting
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                print("⏳ Rate limit hit - waiting before retry...")
                import re
                # Extract retry delay if available
                retry_match = re.search(r'Please retry in (\d+\.?\d*)s', error_str)
                if retry_match:
                    delay = float(retry_match.group(1))
                    print(f"⏳ Waiting {delay:.1f} seconds...")
                    time.sleep(delay + 1)  # Add 1 second buffer
                else:
                    time.sleep(10)  # Default 10 second wait
                
                # For browser workflows, provide smart fallback
                if "safari" in task.lower() or "browser" in task.lower():
                    if "search" in task.lower():
                        return 'hotkey("cmd+t")'  # Open new tab for search
                    
            return "done()"
    
    def execute(self, action_text):
        print(f"🤖 Harvey: {action_text}")
        
        # Add TTS before execution
        self._speak_rationale(action_text, getattr(self, "last_see", ""), "")
        
        try:
            if action_text.startswith("move_mouse"):
                coords = self._extract_coords(action_text)
                if coords:
                    print(f"   → Moving cursor to position")
                    move_mouse(coords[0], coords[1])
                    
            elif action_text.startswith("left_click"):
                coords = self._extract_coords(action_text)
                if coords:
                    print(f"   → Precise clicking to select/activate")
                    left_click(coords[0], coords[1])
                    
            elif action_text.startswith("double_click"):
                coords = self._extract_coords(action_text)
                if coords:
                    print(f"   → Double-clicking to open/activate")
                    double_click(coords[0], coords[1])
                    
            elif action_text.startswith("hover"):
                coords = self._extract_coords(action_text)
                if coords:
                    print(f"   → Hovering to reveal menu/tooltip")
                    hover(coords[0], coords[1])
                    
            elif action_text.startswith("type_text"):
                text = self._extract_text(action_text)
                if text:
                    print(f"   → Typing '{text}' to input text")
                    type_text(text)
                    
            elif action_text.startswith("hotkey"):
                key = self._extract_text(action_text)
                if key:
                    if key == "cmd+space":
                        print(f"   → Opening Spotlight search")
                    elif key == "cmd+t":
                        print(f"   → Opening new tab")
                    elif key == "cmd+l":
                        print(f"   → Focusing address bar")
                    elif key == "enter" or key == "return":
                        print(f"   → Confirming/executing action")
                    else:
                        print(f"   → Pressing {key} shortcut")
                    hotkey(key)
                    
            elif action_text.startswith("wait"):
                ms = self._extract_number(action_text)
                if ms:
                    print(f"   → Waiting {ms}ms for page/app to load")
                    time.sleep(ms / 1000)
                    
            elif action_text.startswith("focus_address_bar"):
                print("   → Focusing browser address bar")
                print("🔍 Focusing address bar with cmd+l")
                hotkey("cmd+l")
                time.sleep(0.3)
                    
            elif action_text.startswith("done"):
                print("   → Task completed successfully")
                return True
                
        except Exception as e:
            print(f"Action error: {e}")
            
        return False

    def _speak_rationale(self, action_text: str, see_line: str, task: str):
        """Speak what Harvey is going to do and what target it's aiming for."""
        try:
            if not _TTS_AVAILABLE:
                return
            if os.getenv("HARVEY_TTS", "1") in ("0", "false", "False"):
                return
            if not action_text:
                return

            action = action_text.strip()
            reason = None

            if action.startswith("hotkey"):
                key = self._extract_text(action) or "shortcut"
                if key == "cmd+space":
                    reason = "Opening Spotlight."
                elif key == "cmd+t":
                    reason = "Opening new tab."
                elif key in ("enter", "return"):
                    reason = "Pressing Enter."
                elif key == "cmd+l":
                    reason = "Focusing address bar."
                else:
                    reason = f"Pressing {key}."
            elif action.startswith("type_text"):
                txt = self._extract_text(action) or "text"
                if len(txt) > 20:
                    txt = txt[:17] + "..."
                reason = f"Typing {txt}."
            elif action.startswith("left_click"):
                coords = self._extract_coords(action)
                # Extract specific target from see_line for better narration
                if see_line:
                    target_lower = see_line.lower()
                    if "compose" in target_lower:
                        reason = "Clicking compose button."
                    elif "subject" in target_lower:
                        reason = "Clicking subject field."
                    elif "message" in target_lower or "body" in target_lower:
                        reason = "Clicking message body."
                    elif "button" in target_lower:
                        reason = "Clicking button."
                    elif "icon" in target_lower:
                        reason = "Clicking icon."
                    else:
                        reason = f"Clicking target."
                else:
                    reason = "Clicking target."
            elif action.startswith("double_click"):
                reason = "Double-clicking to open."
            elif action.startswith("hover"):
                reason = "Hovering over element."
            elif action.startswith("wait"):
                ms = self._extract_number(action) or 1000
                sec = ms / 1000
                reason = f"Waiting {sec:.1f} seconds."
            elif action.startswith("done"):
                reason = "Task complete."

            if reason:
                # Generate audio file then play it via macOS afplay
                audio_path = tts_speak(reason)
                try:
                    subprocess.run(["afplay", audio_path], check=False)
                except Exception:
                    pass
        except Exception:
            # Never let TTS errors break core automation
            pass
    
    def _extract_coords(self, text):
        """Extract and validate (ratio_x, ratio_y) from action text."""
        import re
        match = re.search(r'\(([0-9.]+),\s*([0-9.]+)\)', text)
        if match:
            ratio_x = float(match.group(1))
            ratio_y = float(match.group(2))
            
            # Validate coordinates are within bounds
            ratio_x = max(0.0, min(1.0, ratio_x))
            ratio_y = max(0.0, min(1.0, ratio_y))
            
            print(f"🎯 Using coordinates: ({ratio_x:.3f}, {ratio_y:.3f})")
            return ratio_x, ratio_y
        return None
    
    def _extract_text(self, text):
        import re
        match = re.search(r'"([^"]*)"', text)
        if match:
            return match.group(1)
        return None
    
    def _extract_number(self, text):
        import re
        match = re.search(r'\((\d+)\)', text)
        if match:
            return int(match.group(1))
        return None
    
    def run(self, task):
        print(f"🚀 Harvey starting: {task}")
        
        for step in range(20):
            print(f"📸 Taking screenshot to analyze current state...")
            screenshot_data = capture_to_bytes()
            
            # DEBUG: Save the first screenshot to see what Harvey is seeing
            if step == 0 and screenshot_data:
                print(f"💾 Screenshot data length: {len(screenshot_data)} characters")
                print("💾 Saving debug screenshot as 'harvey_debug.jpg'")
                with open("harvey_debug.jpg", "wb") as f:
                    f.write(base64.b64decode(screenshot_data))
                print("✅ Debug screenshot saved! Check harvey_debug.jpg to see what Harvey sees.")
                
                # Also check image dimensions
                try:
                    from PIL import Image
                    import io
                    img_bytes = base64.b64decode(screenshot_data)
                    img = Image.open(io.BytesIO(img_bytes))
                    print(f"🖼️  Image dimensions: {img.size[0]}x{img.size[1]} pixels")
                except Exception as e:
                    print(f"❌ Error reading image: {e}")
                # Also log screen points and scale for mapping verification
                try:
                    sw, sh, sc = get_screen_info()
                    print(f"🖥️  Screen points: {sw}x{sh}, scale: {sc:.1f}x")
                except Exception:
                    pass
                # Log screen info for diagnostics
                try:
                    sw, sh, sc = get_screen_info()
                    print(f"🖥️  Screen points: {sw}x{sh}, scale: {sc:.1f}x")
                except Exception:
                    pass
            
            if not screenshot_data:
                print("❌ Failed to capture screenshot")
                break
                
            action = self.think(task, screenshot_data)
            # Speak a short rationale before executing the action
            self._speak_rationale(action, getattr(self, "last_see", ""), task)
            done = self.execute(action)
            
            if done:
                print("✅ Task complete!")
                break
                
            time.sleep(1.0)
        
        print("🏁 Harvey finished")

def main():
    # Load environment variables first (needed for offsets, API key)
    from dotenv import load_dotenv
    load_dotenv()

    # Simple CLI: either calibration or a single task string
    if len(sys.argv) < 2:
        print("Usage:\n  python harvey.py \"your task here\"\n  python harvey.py --calibrate    # interactive pointer calibration\n  python harvey.py calibrate      # same as --calibrate")
        sys.exit(1)

    arg1 = sys.argv[1].strip()
    if arg1 in ("--calibrate", "calibrate"):
        calibrate_interactive()
        return

    if not os.getenv("GEMINI_API_KEY"):
        print("❌ Please set GEMINI_API_KEY in .env file")
        sys.exit(1)

    task = arg1
    harvey = Harvey()
    harvey.run(task)

if __name__ == "__main__":
    main()