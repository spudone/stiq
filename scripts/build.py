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

import os
import platform
import subprocess
import sys

# ELF Program Header Constants
# PT_GNU_STACK signature (0x6474e551 little-endian)
ELF_PT_GNU_STACK = b"\x51\xe5\x74\x64"
# Offset from p_type to p_flags in the Program Header
ELF_P_FLAGS_OFFSET = 4
# Permission flags: Read (4) + Write (2) = 6 (0x06000000 little-endian)
ELF_P_FLAGS_RW = b"\x06\x00\x00\x00"


# appears to be no longer needed due to fixes in python 3.13.13 but kept in case of regression
def clear_execstack(filepath):
    """
    Scans the entire file for PT_GNU_STACK headers and removes the executable bit.
    """
    try:
        with open(filepath, "r+b") as f:
            d = f.read()
            i = d.find(ELF_PT_GNU_STACK)
            count = 0
            while i != -1:
                f.seek(i + ELF_P_FLAGS_OFFSET)
                f.write(ELF_P_FLAGS_RW)
                count += 1
                i = d.find(ELF_PT_GNU_STACK, i + ELF_P_FLAGS_OFFSET)

            print(f"Cleared execstack at {count} locations in {filepath}")
    except Exception as e:
        print(f"Error checking execstack for {filepath}: {e}")


def run_command(cmd):
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"Error: Command failed with exit code {result.returncode}")
        sys.exit(result.returncode)


def build():
    system = platform.system().lower()
    sep = ";" if system == "windows" else ":"

    cmd = [
        "pyinstaller",
        "src/stiq/main.py",
        "--onefile",
        "--noconsole",
        "--name",
        "stiq",
        "--add-data",
        f"web{sep}web",
        "--paths",
        "src",
        "-m",
        "stiq.main",
        "--clean",
    ]

    provider_type = os.environ.get("STIQ_PROVIDER", "yahoo").lower()

    # Create a runtime hook to enforce the provider type at runtime
    hook_file = "stiq_runtime_hook.py"
    with open(hook_file, "w") as f:
        f.write(f"import os\nos.environ['STIQ_PROVIDER'] = '{provider_type}'\n")

    cmd.extend(["--runtime-hook", hook_file])

    if provider_type == "yfinance":
        cmd.extend(["--hidden-import", "stiq.yfinance_provider"])
    elif provider_type == "tiingo":
        cmd.extend(
            ["--hidden-import", "stiq.tiingo_provider", "--hidden-import", "websockets"]
        )
    else:
        cmd.extend(["--hidden-import", "stiq.yahoo_provider"])

    print("Starting PyInstaller build...")
    run_command(cmd)

    # Cleanup the temporary hook file
    if os.path.exists(hook_file):
        os.remove(hook_file)

    print("\nBuild complete! Your executable is in the 'dist' folder.")


if __name__ == "__main__":
    build()
