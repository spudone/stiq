"""
Stiq - Stock Ticker
Copyright (C) 2026 spudone

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

import json
import os
import platform
import re
import shutil
import ssl
import stat
import subprocess
import sys
import urllib.request

# Read target version from package.json (managed by Dependabot)
package_json_path = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "package.json"
)
with open(package_json_path) as f:
    package_data = json.load(f)
    # Remove any prefix like ^ or ~
    raw_version = re.sub(r"^[^\d]+", "", package_data["devDependencies"]["tailwindcss"])
    TAILWIND_VERSION = f"v{raw_version}"


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
    if machine == "amd64" and system != "windows":
        machine = "x86_64"

    key = (system, machine)
    if key not in binary_map:
        print(f"Unsupported platform/architecture: {system}/{machine}")
        sys.exit(1)

    binary_name = binary_map[key]
    url = f"https://github.com/tailwindlabs/tailwindcss/releases/download/{TAILWIND_VERSION}/{binary_name}"

    target_name = "tailwindcss.exe" if system == "windows" else "tailwindcss"

    if os.path.exists(target_name):
        print(f"Tailwind CSS binary already exists: {target_name}. Skipping download.")
        return

    print(f"Downloading Tailwind CSS binary for {system}/{machine}...")
    print(f"URL: {url}")

    success = False
    tmp_target = f"{target_name}.tmp"

    def cleanup_tmp():
        if os.path.exists(tmp_target):
            try:
                os.remove(tmp_target)
            except OSError:
                pass

    cleanup_tmp()

    def download_via_curl() -> bool:
        """Download using curl (bundled CA store, works on most platforms)."""
        try:
            subprocess.run(
                ["curl", "-fSL", "-o", tmp_target, url],
                capture_output=True,
                check=True,
                timeout=60,
            )
            os.replace(tmp_target, target_name)
            return True
        except Exception:
            cleanup_tmp()
            return False

    def download_via_truststore() -> bool:
        """Download using truststore (native OS certificate store on macOS/Windows/Linux)."""
        try:
            import truststore

            ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            with urllib.request.urlopen(url, context=ctx, timeout=60) as response:
                with open(tmp_target, "wb") as out_file:
                    shutil.copyfileobj(response, out_file, length=128 * 1024)
            os.replace(tmp_target, target_name)
            return True
        except Exception:
            cleanup_tmp()
            return False

    for downloader in [download_via_curl, download_via_truststore]:
        if downloader():
            success = True
            break

    if not success:
        print("Error downloading binary after exhausting all download methods.")
        sys.exit(1)

    if success:
        # Make executable on non-Windows
        if system != "windows":
            st = os.stat(target_name)
            os.chmod(target_name, st.st_mode | stat.S_IEXEC)
        print(f"Successfully downloaded and configured {target_name}")


if __name__ == "__main__":
    get_tailwind()
