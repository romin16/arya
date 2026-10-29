"""
ARYA Desktop Agent V2 - Complete with All Methods
Enhanced desktop automation with safety features
"""

import pyautogui
import subprocess
import platform
import time
import json
import os
import webbrowser
from pathlib import Path
from typing import Dict, Optional, List
from datetime import datetime

class AppController:
    """Manages application launching and control"""
    
    def __init__(self):
        self.system = platform.system()
        self.app_paths = self._load_app_paths()
        self.action_history = []
        
    def _load_app_paths(self) -> Dict[str, str]:
        """Load app paths from config or use defaults"""
        config_path = Path("config/app_paths.json")
        
        if config_path.exists():
            with open(config_path) as f:
                return json.load(f)
        
        # Default paths by OS
        if self.system == "Windows":
            return {
                "chrome": "start chrome",
                "firefox": "start firefox",
                "edge": "start msedge",
                "spotify": "start spotify:",
                "vscode": "start code",
                "whatsapp": "start whatsapp:",
                "calculator": "calc",
                "notepad": "notepad",
                "explorer": "explorer",
                "discord": "start discord:",
                "telegram": "start telegram:",
            }
        elif self.system == "Darwin":  # macOS
            return {
                "chrome": "Google Chrome",
                "spotify": "Spotify",
                "vscode": "Visual Studio Code",
                "whatsapp": "WhatsApp",
                "calculator": "Calculator",
                "notes": "Notes",
                "finder": "Finder",
                "discord": "Discord",
            }
        else:  # Linux
            return {
                "chrome": "google-chrome",
                "spotify": "spotify",
                "vscode": "code",
                "calculator": "gnome-calculator",
                "files": "nautilus",
            }
    
    def open_app(self, app_name: str) -> Dict:
        """Open an application by name"""
        app_name = app_name.lower().strip()
        
        try:
            if self.system == "Darwin":
                full_name = self.app_paths.get(app_name, app_name)
                subprocess.Popen(['open', '-a', full_name])
            elif self.system == "Windows":
                cmd = self.app_paths.get(app_name, app_name)
                subprocess.Popen(cmd, shell=True)
            else:
                cmd = self.app_paths.get(app_name, app_name)
                subprocess.Popen([cmd])
            
            self._log_action("open_app", app_name)
            time.sleep(1)
            
            return {
                "success": True,
                "message": f"Opened {app_name}",
                "action": "open_app"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": f"Failed to open {app_name}"
            }
    
    def close_app(self, app_name: str) -> Dict:
        """Close a running application"""
        app_name = app_name.lower().strip()
        
        try:
            if self.system == "Darwin":
                subprocess.run(['osascript', '-e', f'quit app "{self.app_paths.get(app_name, app_name)}"'])
            elif self.system == "Windows":
                subprocess.run(['taskkill', '/F', '/IM', f'{app_name}.exe'])
            else:
                subprocess.run(['pkill', '-f', app_name])
            
            self._log_action("close_app", app_name)
            
            return {
                "success": True,
                "message": f"Closed {app_name}"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def _log_action(self, action_type: str, details: str):
        """Log action for history/undo"""
        self.action_history.append({
            "type": action_type,
            "details": details,
            "timestamp": time.time()
        })


class SpotifyController:
    """Controls Spotify with working search & play using Space bar"""
    
    def __init__(self):
        self.system = platform.system()
    
    def play_pause(self) -> Dict:
        """Toggle play/pause for CURRENT song only"""
        try:
            if self.system == "Darwin":
                subprocess.run(['osascript', '-e', 'tell application "Spotify" to playpause'])
            else:
                pyautogui.press('playpause')
            
            return {"success": True, "message": "Toggled play/pause"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def next_track(self) -> Dict:
        """Skip to next track"""
        try:
            if self.system == "Darwin":
                subprocess.run(['osascript', '-e', 'tell application "Spotify" to next track'])
            else:
                pyautogui.press('nexttrack')
            
            return {"success": True, "message": "Skipped to next track"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def previous_track(self) -> Dict:
        """Go to previous track"""
        try:
            if self.system == "Darwin":
                subprocess.run(['osascript', '-e', 'tell application "Spotify" to previous track'])
            else:
                pyautogui.press('prevtrack')
            
            return {"success": True, "message": "Previous track"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def search_and_play(self, query: str) -> Dict:
        """
        ✅ CORRECT METHOD: Ctrl+K for search, then Shift+Enter to play
        This is the proper Spotify keyboard shortcut!
        """
        try:
            print(f"\n{'='*70}")
            print(f"[Spotify] 🎵 SEARCHING AND PLAYING: {query}")
            print(f"{'='*70}")
            
            if self.system == "Windows":
                try:
                    import win32gui
                    import win32con
                    
                    # ═══════════════════════════════════════════════════
                    # STEP 1: Find and focus Spotify window
                    # ═══════════════════════════════════════════════════
                    def find_spotify_window():
                        def callback(hwnd, windows):
                            title = win32gui.GetWindowText(hwnd)
                            if "Spotify" in title and win32gui.IsWindowVisible(hwnd):
                                windows.append(hwnd)
                            return True
                        windows = []
                        win32gui.EnumWindows(callback, windows)
                        return windows[0] if windows else None
                    
                    spotify_hwnd = find_spotify_window()
                    
                    if not spotify_hwnd:
                        print("[Spotify] ⚠️  Window not found, opening Spotify...")
                        subprocess.Popen("start spotify:", shell=True)
                        time.sleep(4)
                        spotify_hwnd = find_spotify_window()
                    
                    if spotify_hwnd:
                        print("[Spotify] ✓ Focusing window...")
                        win32gui.ShowWindow(spotify_hwnd, win32con.SW_RESTORE)
                        win32gui.SetForegroundWindow(spotify_hwnd)
                        time.sleep(1.0)
                        print("[Spotify] ✓ Window focused")
                    
                    # ═══════════════════════════════════════════════════
                    # STEP 2: Open search bar (Ctrl+K) - CORRECT SHORTCUT!
                    # ═══════════════════════════════════════════════════
                    print("[Spotify] 🔍 Opening search bar (Ctrl+K)...")
                    pyautogui.hotkey('ctrl', 'k')
                    time.sleep(0.8)
                    print("[Spotify] ✓ Search bar opened")
                    
                    # ═══════════════════════════════════════════════════
                    # STEP 3: Clear search bar (if needed)
                    # ═══════════════════════════════════════════════════
                    print("[Spotify] 🧹 Clearing search bar...")
                    pyautogui.hotkey('ctrl', 'a')
                    time.sleep(0.2)
                    pyautogui.press('delete')
                    time.sleep(0.3)
                    print("[Spotify] ✓ Search bar cleared")
                    
                    # ═══════════════════════════════════════════════════
                    # STEP 4: Type search query
                    # ═══════════════════════════════════════════════════
                    print(f"[Spotify] ⌨️  Typing: '{query}'")
                    pyautogui.write(query, interval=0.05)
                    time.sleep(1.0)  # Wait for search suggestions
                    print("[Spotify] ✓ Query typed, waiting for results...")
                    
                    # ═══════════════════════════════════════════════════
                    # STEP 5: Press Shift+Enter to play first result
                    # This is the CORRECT way to play from search!
                    # ═══════════════════════════════════════════════════
                    print("[Spotify] ⏯️  Pressing Shift+Enter to play...")
                    pyautogui.hotkey('shift', 'enter')
                    time.sleep(0.8)
                    
                    print(f"[Spotify] {'='*70}")
                    print(f"[Spotify] ✅ SUCCESS - Now playing: {query}")
                    print(f"[Spotify] {'='*70}\n")
                    
                    return {
                        "success": True,
                        "message": f"Playing: {query}"
                    }
                    
                except ImportError as e:
                    print(f"[Spotify] ⚠️  win32gui not available: {e}")
                    
                    # Fallback without win32gui
                    print("[Spotify] Using fallback method...")
                    
                    # Just use keyboard shortcuts
                    pyautogui.hotkey('ctrl', 'l')
                    time.sleep(0.6)
                    pyautogui.hotkey('ctrl', 'a')
                    time.sleep(0.2)
                    pyautogui.press('delete')
                    time.sleep(0.3)
                    pyautogui.write(query, interval=0.05)
                    time.sleep(0.8)
                    pyautogui.press('enter')
                    time.sleep(1.5)
                    pyautogui.press('space')  # SPACE BAR!
                    
                    return {
                        "success": True,
                        "message": f"Playing: {query} (fallback method)"
                    }
                
            elif self.system == "Darwin":
                # macOS version with Space bar
                print("[Spotify] 🍎 macOS detected")
                subprocess.run(['osascript', '-e', 'tell application "Spotify" to activate'])
                time.sleep(1.0)
                
                pyautogui.hotkey('command', 'l')
                time.sleep(0.6)
                
                pyautogui.hotkey('command', 'a')
                time.sleep(0.2)
                pyautogui.press('delete')
                time.sleep(0.3)
                
                pyautogui.write(query, interval=0.05)
                time.sleep(0.8)
                
                pyautogui.press('enter')
                time.sleep(1.5)
                
                # SPACE BAR to play
                pyautogui.press('space')
                
                print(f"[Spotify] ✅ Playing: {query}")
                
                return {
                    "success": True,
                    "message": f"Playing: {query}"
                }
            
            else:
                return {
                    "success": False,
                    "error": "Linux not supported yet"
                }
                
        except Exception as e:
            print(f"[Spotify] ❌ ERROR: {e}")
            import traceback
            traceback.print_exc()
            
            return {
                "success": False,
                "error": str(e),
                "message": f"Failed to play: {query}"
            }



class BrowserController:
    """Advanced browser control"""
    
    @staticmethod
    def open_url(url: str) -> Dict:
        """Open URL in default browser"""
        try:
            if platform.system() == "Windows":
                try:
                    chrome_path = "C:/Program Files/Google/Chrome/Application/chrome.exe"
                    if os.path.exists(chrome_path):
                        webbrowser.register('chrome', None, webbrowser.BackgroundBrowser(chrome_path))
                        webbrowser.get('chrome').open(url)
                    else:
                        webbrowser.open(url)
                except:
                    webbrowser.open(url)
            else:
                webbrowser.open(url)
            
            return {
                "success": True,
                "message": f"Opened {url}"
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def search_google(query: str) -> Dict:
        """Google search in browser"""
        try:
            search_url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
            webbrowser.open(search_url)
            return {
                "success": True,
                "message": f"Searching: {query}"
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def open_youtube(query: str) -> Dict:
        """Search and open YouTube"""
        try:
            search_url = f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}"
            webbrowser.open(search_url)
            return {
                "success": True,
                "message": f"YouTube search: {query}"
            }
        except Exception as e:
            return {"success": False, "error": str(e)}


class FileExplorerController:
    """File system navigation"""
    
    @staticmethod
    def open_folder(path: str) -> Dict:
        """Open a folder in file explorer"""
        try:
            if platform.system() == "Windows":
                os.startfile(path)
            elif platform.system() == "Darwin":
                subprocess.Popen(['open', path])
            else:
                subprocess.Popen(['xdg-open', path])
            
            return {
                "success": True,
                "message": f"Opened folder: {path}"
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def open_downloads() -> Dict:
        """Open Downloads folder"""
        downloads = str(Path.home() / "Downloads")
        return FileExplorerController.open_folder(downloads)
    
    @staticmethod
    def open_documents() -> Dict:
        """Open Documents folder"""
        documents = str(Path.home() / "Documents")
        return FileExplorerController.open_folder(documents)


class InputController:
    """Keyboard and mouse input control"""
    
    @staticmethod
    def type_text(text: str) -> Dict:
        """Type text at current cursor position"""
        try:
            pyautogui.write(text, interval=0.05)
            return {
                "success": True,
                "message": f"Typed: {text[:50]}..." if len(text) > 50 else f"Typed: {text}"
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def press_key(key: str) -> Dict:
        """Press a single key"""
        try:
            pyautogui.press(key)
            return {
                "success": True,
                "message": f"Pressed: {key}"
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def hotkey(*keys) -> Dict:
        """Press a key combination"""
        try:
            pyautogui.hotkey(*keys)
            return {
                "success": True,
                "message": f"Pressed: {'+'.join(keys)}"
            }
        except Exception as e:
            return {"success": False, "error": str(e)}


class ScreenController:
    """Screen capture and management"""
    
    @staticmethod
    def take_screenshot(filename: Optional[str] = None) -> Dict:
        """Take a screenshot"""
        try:
            if filename is None:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"screenshot_{timestamp}.png"
            
            # Ensure screenshots directory exists
            screenshots_dir = Path.home() / "Pictures" / "Screenshots"
            screenshots_dir.mkdir(parents=True, exist_ok=True)
            
            filepath = screenshots_dir / filename
            screenshot = pyautogui.screenshot()
            screenshot.save(str(filepath))
            
            return {
                "success": True,
                "message": "Screenshot saved",
                "filepath": str(filepath)
            }
        except Exception as e:
            return {"success": False, "error": str(e)}


class SystemController:
    """System-level controls"""
    
    @staticmethod
    def set_volume(level: int) -> Dict:
        """Set system volume (0-100)"""
        try:
            level = max(0, min(100, level))
            
            if platform.system() == "Darwin":
                subprocess.run(['osascript', '-e', f'set volume output volume {level}'])
            elif platform.system() == "Windows":
                # Try pycaw first
                try:
                    from ctypes import cast, POINTER
                    from comtypes import CLSCTX_ALL
                    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
                    
                    devices = AudioUtilities.GetSpeakers()
                    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                    volume = cast(interface, POINTER(IAudioEndpointVolume))
                    volume.SetMasterVolumeLevelScalar(level / 100, None)
                    
                    return {"success": True, "message": f"Volume set to {level}%"}
                except Exception as pycaw_error:
                    print(f"pycaw failed: {pycaw_error}")
                    
                    # Fallback to keyboard method
                    pyautogui.press('volumemute')
                    time.sleep(0.2)
                    pyautogui.press('volumemute')
                    time.sleep(0.2)
                    
                    for _ in range(50):
                        pyautogui.press('volumedown')
                        time.sleep(0.01)
                    
                    time.sleep(0.2)
                    steps = level // 2
                    for _ in range(steps):
                        pyautogui.press('volumeup')
                        time.sleep(0.02)
                    
                    return {"success": True, "message": f"Volume set to ~{level}%"}
            
            return {"success": True, "message": f"Volume set to {level}%"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def lock_screen() -> Dict:
        """Lock the computer"""
        try:
            if platform.system() == "Darwin":
                subprocess.run(['pmset', 'displaysleepnow'])
            elif platform.system() == "Windows":
                subprocess.run(['rundll32.exe', 'user32.dll,LockWorkStation'])
            else:
                subprocess.run(['gnome-screensaver-command', '-l'])
            
            return {"success": True, "message": "Screen locked"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def close_window() -> Dict:
        """Close active window"""
        try:
            pyautogui.hotkey('alt', 'f4')
            return {"success": True, "message": "Window closed"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def minimize_window() -> Dict:
        """Minimize active window"""
        try:
            if platform.system() == "Windows":
                pyautogui.hotkey('win', 'down')
            else:
                pyautogui.hotkey('command', 'm')
            return {"success": True, "message": "Window minimized"}
        except Exception as e:
            return {"success": False, "error": str(e)}


# Main Desktop Agent Class
class DesktopAgent:
    """
    Complete desktop automation agent
    Compatible with Flask server endpoints
    """
    
    def __init__(self):
        self.app_controller = AppController()
        self.spotify = SpotifyController()
        self.browser = BrowserController()
        self.files = FileExplorerController()
        self.input = InputController()
        self.screen = ScreenController()
        self.system = SystemController()
    
    # ==================== APP METHODS ====================
    
    def open_app(self, app_name: str) -> Dict:
        """Open an application"""
        return self.app_controller.open_app(app_name)
    
    def close_app(self, app_name: str) -> Dict:
        """Close an application"""
        return self.app_controller.close_app(app_name)
    
    # ==================== SPOTIFY METHODS ====================
    
    def spotify_search(self, query: str) -> Dict:
        """Search and play music on Spotify"""
        return self.spotify.search_and_play(query)
    
    def spotify_play_pause(self) -> Dict:
        """Toggle Spotify play/pause"""
        return self.spotify.play_pause()
    
    def spotify_next(self) -> Dict:
        """Next track on Spotify"""
        return self.spotify.next_track()
    
    def spotify_previous(self) -> Dict:
        """Previous track on Spotify"""
        return self.spotify.previous_track()
    
    # ==================== BROWSER METHODS ====================
    
    def search_google(self, query: str) -> Dict:
        """Google search"""
        return self.browser.search_google(query)
    
    def youtube_search(self, query: str) -> Dict:
        """YouTube search"""
        return self.browser.open_youtube(query)
    
    def open_url(self, url: str) -> Dict:
        """Open URL"""
        return self.browser.open_url(url)
    
    # ==================== FILE METHODS ====================
    
    def open_downloads(self) -> Dict:
        """Open Downloads folder"""
        return self.files.open_downloads()
    
    def open_documents(self) -> Dict:
        """Open Documents folder"""
        return self.files.open_documents()
    
    # ==================== INPUT METHODS ====================
    
    def type_text(self, text: str) -> Dict:
        """Type text"""
        return self.input.type_text(text)
    
    def press_key(self, key: str) -> Dict:
        """Press a key"""
        return self.input.press_key(key)
    
    def hotkey(self, *keys) -> Dict:
        """Press hotkey combination"""
        return self.input.hotkey(*keys)
    
    # ==================== SCREEN METHODS ====================
    
    def take_screenshot(self, filename: Optional[str] = None) -> Dict:
        """Take screenshot"""
        return self.screen.take_screenshot(filename)
    
    # ==================== SYSTEM METHODS ====================
    
    def set_volume(self, level: int) -> Dict:
        """Set volume"""
        return self.system.set_volume(level)
    
    def lock_screen(self) -> Dict:
        """Lock screen"""
        return self.system.lock_screen()
    
    def close_window(self) -> Dict:
        """Close active window"""
        return self.system.close_window()
    
    def minimize_window(self) -> Dict:
        """Minimize active window"""
        return self.system.minimize_window()
    
    def volume_up(self) -> Dict:
        """Increase volume"""
        try:
            for _ in range(2):
                pyautogui.press('volumeup')
            return {"success": True, "message": "Volume increased"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def volume_down(self) -> Dict:
        """Decrease volume"""
        try:
            for _ in range(2):
                pyautogui.press('volumedown')
            return {"success": True, "message": "Volume decreased"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def play_pause(self) -> Dict:
        """Play/pause media"""
        try:
            pyautogui.press('playpause')
            return {"success": True, "message": "Toggled play/pause"}
        except Exception as e:
            return {"success": False, "error": str(e)}


# Example usage
if __name__ == "__main__":
    agent = DesktopAgent()
    
    print("🤖 ARYA Desktop Agent V2 - Testing")
    print("=" * 50)
    
    # Test Spotify search
    print("\n1. Testing Spotify search...")
    result = agent.spotify_search("lofi hip hop")
    print(f"   Result: {result}")
    
    time.sleep(2)
    
    # Test type text
    print("\n2. Testing type text (open notepad first)...")
    agent.open_app("notepad")
    time.sleep(2)
    result = agent.type_text("Hello from ARYA!")
    print(f"   Result: {result}")
    
    time.sleep(1)
    
    # Test YouTube
    print("\n3. Testing YouTube search...")
    result = agent.youtube_search("cooking videos")
    print(f"   Result: {result}")
    
    print("\n" + "=" * 50)
    print("✅ Testing complete!")