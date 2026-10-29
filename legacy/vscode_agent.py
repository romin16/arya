"""
VS Code Automation Agent for ARYA
Controls VS Code via keyboard shortcuts and file operations
"""

import pyautogui
import subprocess
import platform
import time
import os
from typing import Dict, Optional, List
from pathlib import Path

class VSCodeAgent:
    """
    Advanced VS Code controller
    Uses native shortcuts and file system operations
    """
    
    def __init__(self):
        self.system = platform.system()
        self.cmd_key = 'command' if self.system == "Darwin" else 'ctrl'
        
        # Import win32gui for Windows
        if self.system == "Windows":
            try:
                import win32gui
                import win32con
                self.win32gui = win32gui
                self.win32con = win32con
            except ImportError:
                print("⚠️ Warning: pywin32 not installed. Window focusing may not work.")
                print("   Install with: pip install pywin32")
                self.win32gui = None
                self.win32con = None
        
    def focus_vscode(self):
        """Ensure VS Code window has focus"""
        try:
            if self.system == "Darwin":
                subprocess.Popen(['open', '-a', 'Visual Studio Code'])
            elif self.system == "Windows" and self.win32gui:
                def find_vscode():
                    def callback(hwnd, windows):
                        title = self.win32gui.GetWindowText(hwnd)
                        if "Visual Studio Code" in title:
                            windows.append(hwnd)
                        return True
                    windows = []
                    self.win32gui.EnumWindows(callback, windows)
                    return windows[0] if windows else None
                
                vscode_hwnd = find_vscode()
                if vscode_hwnd:
                    self.win32gui.ShowWindow(vscode_hwnd, self.win32con.SW_RESTORE)
                    self.win32gui.SetForegroundWindow(vscode_hwnd)
                else:
                    subprocess.Popen(['code'], shell=True)
            else:
                subprocess.Popen(['code'])
            
            time.sleep(1)
            return True
        except Exception as e:
            print(f"⚠️ Focus error: {e}")
            return False
        
    def open_vscode(self, folder_path: Optional[str] = None) -> Dict:
        """Open VS Code, optionally with a specific folder"""
        try:
            if folder_path:
                if self.system == "Darwin":
                    subprocess.Popen(['open', '-a', 'Visual Studio Code', folder_path])
                elif self.system == "Windows":
                    subprocess.Popen(['code', folder_path], shell=True)
                else:
                    subprocess.Popen(['code', folder_path])
            else:
                if self.system == "Darwin":
                    subprocess.Popen(['open', '-a', 'Visual Studio Code'])
                elif self.system == "Windows":
                    subprocess.Popen(['code'], shell=True)
                else:
                    subprocess.Popen(['code'])
            
            time.sleep(2)
            return {
                "success": True,
                "message": f"VS Code opened{' with ' + folder_path if folder_path else ''}"
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def open_file(self, file_path: str) -> Dict:
        """Open a specific file in VS Code"""
        try:
            # Ensure VS Code is focused
            self.focus_vscode()
            
            # Quick Open (Cmd/Ctrl + P)
            pyautogui.hotkey(self.cmd_key, 'p')
            time.sleep(0.8)
            
            # Type filename
            filename = os.path.basename(file_path)
            pyautogui.write(filename, interval=0.08)
            time.sleep(0.8)
            
            # Press Enter
            pyautogui.press('enter')
            time.sleep(0.5)
            
            return {
                "success": True,
                "message": f"Opened file: {filename}"
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def search_in_files(self, search_term: str) -> Dict:
        """Search across all files in workspace"""
        try:
            # Ensure VS Code is focused
            self.focus_vscode()
            
            # Open search (Cmd/Ctrl + Shift + F)
            if self.system == "Darwin":
                pyautogui.hotkey('command', 'shift', 'f')
            else:
                pyautogui.hotkey('ctrl', 'shift', 'f')
            
            time.sleep(1)
            
            # Clear any existing search
            pyautogui.hotkey('ctrl', 'a')
            time.sleep(0.2)
            
            # Type search term
            pyautogui.write(search_term, interval=0.1)
            time.sleep(0.5)
            
            # Press Enter
            pyautogui.press('enter')
            
            return {
                "success": True,
                "message": f"Searching for: {search_term}"
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def run_terminal_command(self, command: str) -> Dict:
        """Open integrated terminal and run a command"""
        try:
            # Ensure focus
            self.focus_vscode()
            
            # Open terminal (Cmd/Ctrl + `)
            pyautogui.hotkey(self.cmd_key, '`')
            time.sleep(0.5)
            
            # Type command
            pyautogui.write(command, interval=0.05)
            time.sleep(0.3)
            
            # Execute
            pyautogui.press('enter')
            
            return {
                "success": True,
                "message": f"Executed command: {command}"
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def format_document(self) -> Dict:
        """Format current document (Shift + Alt + F)"""
        try:
            pyautogui.hotkey('shift', 'alt', 'f')
            time.sleep(0.5)
            
            return {"success": True, "message": "Document formatted"}
        except Exception as e:
            return {"success": False, "error": str(e)}


# Example Usage
if __name__ == "__main__":
    agent = VSCodeAgent()
    
    print("💻 Testing VS Code Agent...")
    
    # Test 1: Open VS Code
    print("\n1. Opening VS Code...")
    result = agent.open_vscode()
    print(f"   Result: {result}")
    
    time.sleep(2)
    
    # Test 2: Open file
    print("\n2. Opening test.py...")
    result = agent.open_file("test.py")
    print(f"   Result: {result}")
    
    time.sleep(2)
    
    # Test 3: Search
    print("\n3. Searching for 'function main'...")
    result = agent.search_in_files("function main")
    print(f"   Result: {result}")