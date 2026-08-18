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
import re


def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    package_json_path = os.path.join(base_dir, "package.json")
    template_path = os.path.join(base_dir, "web", "index.template.html")
    output_path = os.path.join(base_dir, "web", "index.html")

    with open(package_json_path) as f:
        pkg = json.load(f)

    deps = pkg.get("devDependencies", {})

    with open(template_path) as f:
        html = f.read()

    for dep, version in deps.items():
        # Remove any leading ^ or ~
        clean_version = re.sub(r"^[^\d]+", "", version)
        html = html.replace(f"{{{{{dep}}}}}", clean_version)

    with open(output_path, "w") as f:
        f.write(html)

    print("Generated web/index.html with frontend dependencies from package.json")


if __name__ == "__main__":
    main()
