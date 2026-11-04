"""
WhatsApp Desktop Automation Agent for ARYA
Handles messaging, contact search, and chat reading
FIXED VERSION - Uses win32gui for proper Windows focus
"""

import pyautogui
import time
import subprocess
import platform
from typing import Dict, Optional
import pyperclip

# Windows-specific imports
try:
    import win32gui
    import win32con
    WINDOWS_FOCUS = True
except ImportError:
    WINDOWS_FOCUS = False

try:
    import pytesseract
    from PIL import Image
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

class WhatsAppAgent:
    """
    Controls WhatsApp Desktop application
    Requirements: WhatsApp Desktop installed and logged in
    """
    
    def __init__(self):
        self.system = platform.system()
        self.app_name = "WhatsApp" if self.system == "Darwin" else "WhatsApp"
        # Safety feature: add small delay between actions
        pyautogui.PAUSE = 0.2  # Reduced for speed
        
    def find_whatsapp_window(self):
        """Find WhatsApp window handle (Windows only)"""
        if not WINDOWS_FOCUS:
            return None
        
        def callback(hwnd, windows):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if "WhatsApp" in title:
                    windows.append(hwnd)
            return True
        
        windows = []
        win32gui.EnumWindows(callback, windows)
        return windows[0] if windows else None
    
    def focus_whatsapp(self) -> Dict:
        """
        Find and focus WhatsApp window using Windows API
        CRITICAL: Must be called before any automation
        """
        try:
            if not WINDOWS_FOCUS:
                return {
                    "success": False,
                    "error": "Install pywin32: pip install pywin32"
                }
            
            # Find WhatsApp window
            hwnd = self.find_whatsapp_window()
            
            if not hwnd:
                return {
                    "success": False, 
                    "error": "WhatsApp window not found. Please open WhatsApp Desktop first."
                }
            
            # Restore if minimized
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                time.sleep(0.5)
            
            # Bring to foreground
            win32gui.SetForegroundWindow(hwnd)
            time.sleep(0.5)  # Reduced wait time
            
            # Click on WhatsApp window to ensure it's active
            rect = win32gui.GetWindowRect(hwnd)
            x = rect[0] + 100
            y = rect[1] + 100
            pyautogui.click(x, y)
            time.sleep(0.3)  # Reduced wait time
            
            return {"success": True, "message": "WhatsApp window focused"}
            
        except Exception as e:
            return {"success": False, "error": f"Failed to focus WhatsApp: {str(e)}"}
    
    def open_whatsapp(self) -> Dict:
        """Open WhatsApp Desktop application"""
        try:
            if self.system == "Darwin":
                subprocess.Popen(['open', '-a', 'WhatsApp'])
            elif self.system == "Windows":
                subprocess.Popen(['start', 'whatsapp:'], shell=True)
            else:
                subprocess.Popen(['whatsapp'])
            
            time.sleep(5)  # Wait for app to open
            
            # Try to focus the window
            focus_result = self.focus_whatsapp()
            if not focus_result["success"]:
                return {
                    "success": True, 
                    "message": "WhatsApp opened but couldn't auto-focus. Please click on WhatsApp window.",
                    "warning": focus_result["error"]
                }
            
            return {"success": True, "message": "WhatsApp opened and focused"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def search_contact(self, contact_name: str) -> Dict:
        """
        Search for a contact in WhatsApp
        Uses keyboard shortcut and typing
        """
        try:
            # CRITICAL: Focus WhatsApp first
            focus_result = self.focus_whatsapp()
            if not focus_result["success"]:
                return focus_result
            
            time.sleep(0.5)  # Reduced wait
            
            # Click search box (Ctrl+F for Windows)
            if self.system == "Darwin":
                pyautogui.hotkey('command', 'f')
            else:
                pyautogui.hotkey('ctrl', 'f')
            
            time.sleep(0.6)  # Reduced wait
            
            # Clear previous search
            pyautogui.hotkey('ctrl', 'a')
            time.sleep(0.2)  # Reduced wait
            
            # Use clipboard for better reliability
            pyperclip.copy(contact_name)
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(1)  # Reduced wait for search results
            
            # Press Down arrow then Enter (more reliable)
            pyautogui.press('down')
            time.sleep(0.3)  # Reduced wait
            pyautogui.press('enter')
            time.sleep(1)  # Reduced wait for chat to open
            
            return {
                "success": True,
                "message": f"Opened chat with {contact_name}"
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def send_message(self, contact_name: str, message: str) -> Dict:
        """
        Send a message to a contact
        First searches for contact, then types and sends message
        """
        try:
            print(f"[DEBUG] Starting send_message to {contact_name}")
            
            # CRITICAL: Focus WhatsApp first
            focus_result = self.focus_whatsapp()
            print(f"[DEBUG] Focus result: {focus_result}")
            if not focus_result["success"]:
                return focus_result
            
            # Search and open chat
            search_result = self.search_contact(contact_name)
            print(f"[DEBUG] Search result: {search_result}")
            if not search_result["success"]:
                return search_result
            
            # Wait for chat to fully load
            time.sleep(0.8)  # Reduced wait
            
            # Focus WhatsApp again (in case focus was lost)
            print("[DEBUG] Re-focusing WhatsApp")
            self.focus_whatsapp()
            time.sleep(0.5)  # Reduced wait
            
            # Click in message input area
            hwnd = self.find_whatsapp_window()
            if hwnd:
                rect = win32gui.GetWindowRect(hwnd)
                # Click at bottom center of WhatsApp window
                click_x = rect[0] + (rect[2] - rect[0]) // 2
                click_y = rect[3] - 100  # 100 pixels from bottom
                print(f"[DEBUG] Clicking at ({click_x}, {click_y})")
                pyautogui.click(click_x, click_y)
                time.sleep(0.4)  # Reduced wait
            
            # Use clipboard to paste message
            print(f"[DEBUG] Pasting message: {message}")
            pyperclip.copy(message)
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(0.5)  # Reduced wait
            
            # Send (Enter key)
            print("[DEBUG] Pressing Enter to send")
            pyautogui.press('enter')
            time.sleep(0.5)
            
            return {
                "success": True,
                "message": f"Message sent to {contact_name}: '{message}'"
            }
        except Exception as e:
            print(f"[DEBUG] Error: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def read_last_messages(self, num_messages: int = 5) -> Dict:
        """Read recent messages from current chat"""
        if not OCR_AVAILABLE:
            return {
                "success": False,
                "error": "pytesseract not installed"
            }
        
        try:
            # Focus WhatsApp
            focus_result = self.focus_whatsapp()
            if not focus_result["success"]:
                return focus_result
            
            time.sleep(0.5)
            
            # Take screenshot of chat area
            screen_width, screen_height = pyautogui.size()
            screenshot = pyautogui.screenshot(
                region=(int(screen_width * 0.25), 
                       int(screen_height * 0.15), 
                       int(screen_width * 0.5), 
                       int(screen_height * 0.6))
            )
            
            screenshot.save("temp_chat.png")
            text = pytesseract.image_to_string(Image.open("temp_chat.png"))
            
            messages = [m for m in text.strip().split('\n') if m.strip()]
            recent = messages[-num_messages:] if len(messages) > num_messages else messages
            
            return {
                "success": True,
                "messages": recent,
                "raw_text": text
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def click_voice_call(self) -> Dict:
        """Initiate voice call in current chat"""
        try:
            self.focus_whatsapp()
            time.sleep(0.5)
            
            screen_width, screen_height = pyautogui.size()
            pyautogui.click(int(screen_width * 0.85), 80)
            
            return {"success": True, "message": "Voice call initiated"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def click_video_call(self) -> Dict:
        """Initiate video call in current chat"""
        try:
            self.focus_whatsapp()
            time.sleep(0.5)
            
            screen_width, screen_height = pyautogui.size()
            pyautogui.click(int(screen_width * 0.88), 80)
            
            return {"success": True, "message": "Video call initiated"}
        except Exception as e:
            return {"success": False, "error": str(e)}


# Example Usage
if __name__ == "__main__":
    agent = WhatsAppAgent()
    
    print("🟢 Opening WhatsApp...")
    result = agent.open_whatsapp()
    print(f"   Result: {result}")
    
    time.sleep(2)
    
    print("\n📤 Sending test message...")
    result = agent.send_message("Alex", "Hello from ARYA - Windows Focus Fixed!")
    print(f"   Result: {result}")