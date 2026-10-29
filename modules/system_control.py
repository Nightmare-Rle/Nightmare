import os
import shutil
import subprocess
import platform
import datetime
import json
import sys

def list_files(path=None):
    if not path:
        path = os.path.expanduser("~\\Desktop")
    try:
        files = os.listdir(path)
        result = []
        for f in files:
            full = os.path.join(path, f)
            is_dir = os.path.isdir(full)
            size = os.path.getsize(full) if not is_dir else 0
            result.append({"name": f, "type": "folder" if is_dir else "file", "size": size})
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error listing {path}: {e}"

def read_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError:
        return f"Cannot read {path} - it's a binary file"
    except Exception as e:
        return f"Error reading {path}: {e}"

def write_file(path, content):
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully wrote {len(content)} characters to {path}"
    except Exception as e:
        return f"Error writing to {path}: {e}"

def delete_file(path):
    try:
        if os.path.isfile(path):
            os.remove(path)
            return f"Deleted file: {path}"
        elif os.path.isdir(path):
            shutil.rmtree(path)
            return f"Deleted folder: {path}"
        return f"Not found: {path}"
    except Exception as e:
        return f"Error deleting {path}: {e}"

def create_folder(path):
    try:
        os.makedirs(path, exist_ok=True)
        return f"Created folder: {path}"
    except Exception as e:
        return f"Error creating folder {path}: {e}"

def run_command(command):
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=60
        )
        output = result.stdout.strip()
        error = result.stderr.strip()
        if error and not output:
            return f"Error: {error}"
        return output if output else f"Command executed successfully (no output)"
    except subprocess.TimeoutExpired:
        return "Command timed out after 60 seconds"
    except Exception as e:
        return f"Error running command: {e}"

def get_system_info():
    info = {
        "os": platform.system(),
        "os_version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "username": os.getlogin(),
        "computer_name": platform.node(),
        "cpu_count": os.cpu_count(),
        "home_directory": os.path.expanduser("~"),
        "current_directory": os.getcwd(),
        "python_version": platform.python_version()
    }
    return json.dumps(info, indent=2)

def get_processes():
    try:
        result = subprocess.run("tasklist /FO CSV", shell=True, capture_output=True, text=True)
        lines = result.stdout.strip().split("\n")[1:]
        procs = []
        for line in lines[:30]:
            parts = line.split(",")
            if len(parts) >= 2:
                procs.append({"name": parts[0].strip('"'), "pid": parts[1].strip('"')})
        return json.dumps(procs, indent=2)
    except Exception as e:
        return f"Error getting processes: {e}"

def kill_process(name_or_pid):
    try:
        result = subprocess.run(f"taskkill /F /IM {name_or_pid} 2>NUL || taskkill /F /PID {name_or_pid} 2>NUL", shell=True, capture_output=True, text=True)
        if result.returncode == 0:
            return f"Killed process: {name_or_pid}"
        return f"Could not kill {name_or_pid}"
    except Exception as e:
        return f"Error killing process: {e}"

def get_drives():
    try:
        drives = []
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            if os.path.exists(f"{letter}:\\"):
                drives.append(f"{letter}:\\")
        return json.dumps(drives, indent=2)
    except Exception as e:
        return f"Error getting drives: {e}"

def get_wifi_password(name):
    try:
        result = subprocess.run(
            f"netsh wlan show profile name=\"{name}\" key=clear",
            shell=True, capture_output=True, text=True
        )
        if "Key Content" in result.stdout:
            for line in result.stdout.split("\n"):
                if "Key Content" in line:
                    return line.split(":")[1].strip()
        return f"Could not find password for: {name}"
    except Exception as e:
        return f"Error: {e}"

def list_wifi_profiles():
    try:
        result = subprocess.run("netsh wlan show profiles", shell=True, capture_output=True, text=True)
        profiles = []
        for line in result.stdout.split("\n"):
            if ":" in line and "All User Profile" in line:
                profiles.append(line.split(":")[1].strip())
        return json.dumps(profiles, indent=2) if profiles else "No WiFi profiles found"
    except Exception as e:
        return f"Error: {e}"

def shutdown():
    subprocess.run("shutdown /s /t 10", shell=True)
    return "Shutting down in 10 seconds..."

def restart():
    subprocess.run("shutdown /r /t 10", shell=True)
    return "Restarting in 10 seconds..."

def cancel_shutdown():
    subprocess.run("shutdown /a", shell=True)
    return "Shutdown cancelled."

def lock_screen():
    subprocess.run("rundll32.exe user32.dll,LockWorkStation", shell=True)
    return "Screen locked."
def add_to_startup():
    try:
        import winreg
        if getattr(sys, 'frozen', False):
            exe_path = sys.executable
        else:
            exe_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'nai_protocol.pyw'))
        key_path = r"Software\\Microsoft\\Windows\\CurrentVersion\\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "Nightmare", 0, winreg.REG_SZ, exe_path)
        return f"Added to startup: {exe_path}"
    except Exception as e:
        return f"Error adding to startup: {e}"

def remove_from_startup():
    try:
        import winreg
        key_path = r"Software\\Microsoft\\Windows\\CurrentVersion\\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            try:
                winreg.DeleteValue(key, "Nightmare")
            except FileNotFoundError:
                pass
        return "Removed from startup"
    except Exception as e:
        return f"Error removing from startup: {e}"

def is_in_startup():
    try:
        import winreg
        key_path = r"Software\\Microsoft\\Windows\\CurrentVersion\\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as key:
            try:
                winreg.QueryValueEx(key, "Nightmare")
                return True
            except FileNotFoundError:
                return False
    except Exception:
        return False
