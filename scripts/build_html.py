import json
import re
import os


def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    package_json_path = os.path.join(base_dir, "package.json")
    template_path = os.path.join(base_dir, "web", "index.template.html")
    output_path = os.path.join(base_dir, "web", "index.html")

    with open(package_json_path, "r") as f:
        pkg = json.load(f)

    deps = pkg.get("devDependencies", {})

    with open(template_path, "r") as f:
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
