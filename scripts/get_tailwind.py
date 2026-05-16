import os
import sys
import platform
import urllib.request
import stat

TAILWIND_VERSION = "v4.0.0" # Target version

def get_tailwind():
    system = platform.system().lower()
    machine = platform.machine().lower()
    
    # Map platform/arch to Tailwind binary names
    binary_map = {
        ("linux", "x86_64"): "tailwindcss-linux-x64",
        ("linux", "aarch64"): "tailwindcss-linux-arm64",
        ("darwin", "x86_64"): "tailwindcss-macos-x64",
        ("darwin", "arm64"): "tailwindcss-macos-arm64",
        ("windows", "amd64"): "tailwindcss-windows-x64.exe",
    }
    
    # Handle some common machine name aliases
    if machine == "amd64" and system != "windows": machine = "x86_64"
    
    key = (system, machine)
    if key not in binary_map:
        print(f"Unsupported platform/architecture: {system}/{machine}")
        sys.exit(1)
        
    binary_name = binary_map[key]
    url = f"https://github.com/tailwindlabs/tailwindcss/releases/latest/download/{binary_name}"
    
    target_name = "tailwindcss.exe" if system == "windows" else "tailwindcss"
    
    if os.path.exists(target_name):
        print(f"Tailwind CSS binary already exists: {target_name}. Skipping download.")
        return

    print(f"Downloading Tailwind CSS binary for {system}/{machine}...")
    print(f"URL: {url}")
    
    try:
        urllib.request.urlretrieve(url, target_name)
        
        # Make executable on non-Windows
        if system != "windows":
            st = os.stat(target_name)
            os.chmod(target_name, st.st_mode | stat.S_IEXEC)
            
        print(f"Successfully downloaded and configured {target_name}")
    except Exception as e:
        print(f"Error downloading binary: {e}")
        sys.exit(1)

if __name__ == "__main__":
    get_tailwind()
