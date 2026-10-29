import webbrowser
import subprocess
import platform
import os

try:
    import psutil
except ImportError:
    psutil = None


def _track(proc, name=""):
    """Remember a process we launched so it can be closed with us."""
    try:
        from modules import child_processes
        child_processes.track_popen(proc, name)
    except Exception:
        pass

COMMON_APPS = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "settings": "ms-settings:",
    "explorer": "explorer.exe",
}

def open_app(app_name):
    app_name = app_name.lower().strip()
    if app_name in COMMON_APPS:
        proc = subprocess.Popen(COMMON_APPS[app_name], shell=True)
        _track(proc, app_name)
        return f"Opening {app_name}"
    try:
        proc = subprocess.Popen(app_name, shell=True)
        _track(proc, app_name)
        return f"Opening {app_name}"
    except Exception as e:
        return f"Could not open {app_name}"

def open_url(url):
    if not url.startswith(("http://", "https://")):
        url = "https://www.google.com/search?q=" + url.replace(" ", "+")
    webbrowser.open(url)
    return f"Opening {url}"

def open_website(url):
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    if "." not in url:
        url = "https://www." + url + ".com"
    webbrowser.open(url)
    return f"Opening {url}"

# Master access functions
def run_shell_command(command):
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
        return f"Output: {result.stdout}\nError: {result.stderr}\nReturn Code: {result.returncode}"
    except Exception as e:
        return f"Error: {str(e)}"

def read_file(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {str(e)}"

def write_file(path, content):
    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"Successfully wrote to {path}"
    except Exception as e:
        return f"Error writing file: {str(e)}"

def list_directory(path="."):
    try:
        return "\n".join(os.listdir(path))
    except Exception as e:
        return f"Error listing directory: {str(e)}"

def kill_process(pid):
    try:
        subprocess.run(f"taskkill /PID {pid} /F", shell=True, check=True)
        return f"Killed process {pid}"
    except Exception as e:
        return f"Error killing process: {str(e)}"

def get_system_info():
    try:
        info = f"OS: {platform.system()} {platform.release()}\nCPU: {platform.processor()}"
        if psutil:
            info += f"\nRAM: {psutil.virtual_memory().total // 1024**3}GB\nDisk: {psutil.disk_usage('/').total // 1024**3}GB"
        return info
    except Exception as e:
        return f"Error: {str(e)}"
