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

try:
    from Quartz import CGEventCreateMouseEvent, CGEventPost, kCGHIDEventTap, kCGEventLeftMouseDown, kCGEventLeftMouseUp, CGEventCreateKeyboardEvent, kCGEventKeyDown, kCGEventKeyUp, CGEventSetFlags, kCGEventFlagMaskCommand
    from Quartz.CoreGraphics import CGMainDisplayID, CGDisplayBounds, CGEventCreate, CGEventGetLocation
    _QUARTZ_AVAILABLE = True
except ImportError:
    _QUARTZ_AVAILABLE = False

def get_screen_size():
    if _QUARTZ_AVAILABLE:
        display = CGMainDisplayID()
        bounds = CGDisplayBounds(display)
        return int(bounds.size.width), int(bounds.size.height)
    return 1920, 1080

def _transform_coords(x_ratio, y_ratio):
    width, height = get_screen_size()
    # Use round() instead of int() for better precision
    x = round(x_ratio * width)
    y = round(y_ratio * height)
    print(f"📍 Ratio ({x_ratio:.3f}, {y_ratio:.3f}) -> Screen ({x}, {y}) [Screen: {width}x{height}]")
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
        
        x = int((1-t_smooth)**2 * start_x + 2*(1-t_smooth)*t_smooth * control_x + t_smooth**2 * end_x)
        y = int((1-t_smooth)**2 * start_y + 2*(1-t_smooth)*t_smooth * control_y + t_smooth**2 * end_y)
        
        event = CGEventCreateMouseEvent(None, 5, (x, y), 0)
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

def left_click(x_ratio, y_ratio):
    if not _QUARTZ_AVAILABLE:
        x, y = _transform_coords(x_ratio, y_ratio)
        print(f"🖱️ Click at ({x}, {y}) (shown to user)")
        return
    
    if _is_spotlight_active():
        print("🔍 Spotlight active - using Enter instead of clicking")
        hotkey("return")
        return
    
    x, y = _transform_coords(x_ratio, y_ratio)
    current_x, current_y = get_current_mouse_position()
    smooth_move_mouse(current_x, current_y, x, y)
    time.sleep(0.2)
    
    try:
        down_event = CGEventCreateMouseEvent(None, kCGEventLeftMouseDown, (x, y), 0)
        up_event = CGEventCreateMouseEvent(None, kCGEventLeftMouseUp, (x, y), 0)
        CGEventPost(kCGHIDEventTap, down_event)
        time.sleep(0.05)
        CGEventPost(kCGHIDEventTap, up_event)
        print(f"✅ Clicked at ({x}, {y})")
    except Exception as e:
        print(f"🖱️ Click at ({x}, {y}) (shown to user)")

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
        
    def think(self, task, screenshot_data):
        prompt = f"""You are Harvey, a macOS automation assistant.

TASK: {task}

Look at the current screen carefully. First, briefly describe what you see in 2-3 words (like "Desktop visible", "Arc browser open", "Spotlight search active").

Then decide what to do next. If you can see that the task is already completed (e.g., Calculator app is open, Safari is running, etc.), respond with done().

Format your response as:
See: [brief description of what's on screen]
Action: [your action]

Actions available:
- move_mouse(ratio_x, ratio_y) - move cursor using screen ratios (0.0 to 1.0)
- left_click(ratio_x, ratio_y) - click using screen ratios (0.0 to 1.0)  
- type_text("hello") - type text
- hotkey("cmd+space") - press key combo
- focus_address_bar() - focus browser address bar with cmd+l
- wait(1000) - wait milliseconds
- done() - task complete

CRITICAL SPOTLIGHT WORKFLOW:
- Step 1: If desktop is visible, use hotkey("cmd+space") to open Spotlight
- Step 2: If Spotlight is open (search bar visible), type the app name with type_text("App Name")
- Step 3: After typing, press hotkey("enter") to launch the app
- NEVER click on Spotlight results - always use enter key
- Example for opening Calculator: hotkey("cmd+space") → type_text("Calculator") → hotkey("enter")

CLICKING ACCURACY RULES:
- Be extremely precise with click coordinates 
- Look carefully at button/icon centers in the screenshot
- Use exact center positions like 0.52, 0.34 instead of round numbers
- For small buttons, aim for the visual center, not edges
- Double-check coordinate positions against what you see

CRITICAL: Check the screenshot first:
- If Calculator app is visible → done()
- If Safari is open → done() 
- If the requested app/action is already complete → done()
- Only continue if the task is NOT finished yet

IMPORTANT: Use ratios from 0.0 to 1.0 for positions:
- Top-left corner: (0.0, 0.0)
- Center: (0.5, 0.5) 
- Bottom-right: (1.0, 1.0)
- Be precise: left_click(0.523, 0.347) not left_click(0.5, 0.3)

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
            
            return action if action else response_text.strip()
            
        except Exception as e:
            print(f"LLM Error: {e}")
            return "done()"
    
    def execute(self, action_text):
        print(f"🤖 Harvey: {action_text}")
        
        try:
            if action_text.startswith("move_mouse"):
                coords = self._extract_coords(action_text)
                if coords:
                    print(f"   → Moving cursor to position")
                    move_mouse(coords[0], coords[1])
                    
            elif action_text.startswith("left_click"):
                coords = self._extract_coords(action_text)
                if coords:
                    print(f"   → Clicking to select/activate")
                    left_click(coords[0], coords[1])
                    
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
    
    def _extract_coords(self, text):
        """Extract (ratio_x, ratio_y) from action text"""
        import re
        match = re.search(r'\(([0-9.]+),\s*([0-9.]+)\)', text)
        if match:
            ratio_x = float(match.group(1))
            ratio_y = float(match.group(2))
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
            
            if not screenshot_data:
                print("❌ Failed to capture screenshot")
                break
                
            action = self.think(task, screenshot_data)
            done = self.execute(action)
            
            if done:
                print("✅ Task complete!")
                break
                
            time.sleep(1.0)
        
        print("🏁 Harvey finished")

def main():
    if len(sys.argv) != 2:
        print("Usage: python harvey.py \"your task here\"")
        sys.exit(1)
    
    # Load environment variables first
    from dotenv import load_dotenv
    load_dotenv()
    
    if not os.getenv("GEMINI_API_KEY"):
        print("❌ Please set GEMINI_API_KEY in .env file")
        sys.exit(1)
    
    task = sys.argv[1]
    harvey = Harvey()
    harvey.run(task)

if __name__ == "__main__":
    main()