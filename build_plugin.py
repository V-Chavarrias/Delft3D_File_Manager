import os
import zipfile
import re

PLUGIN_FOLDER = "WeirImporter"   # plugin folder
METADATA_FILE = os.path.join(PLUGIN_FOLDER, "metadata.txt")

def get_version(metadata_path):
    """Read version from metadata.txt"""
    version = "0.0"
    with open(metadata_path, "r", encoding="utf-8") as f:
        for line in f:
            match = re.match(r"version\s*=\s*(.*)", line.strip(), re.IGNORECASE)
            if match:
                version = match.group(1).strip()
                break
    return version

def zipdir(path, ziph):
    """Recursively zip a folder."""
    for root, dirs, files in os.walk(path):
        for file in files:
            if file.endswith(".pyc") or file.startswith(".") or "__pycache__" in root:
                continue
            file_path = os.path.join(root, file)
            arcname = os.path.relpath(file_path, os.path.dirname(PLUGIN_FOLDER))
            ziph.write(file_path, arcname)

if __name__ == "__main__":
    version = get_version(METADATA_FILE)
    output_zip = f"{PLUGIN_FOLDER}_v{version}.zip"

    if os.path.exists(output_zip):
        os.remove(output_zip)

    with zipfile.ZipFile(output_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
        zipdir(PLUGIN_FOLDER, zipf)

    print(f"✅ Plugin ZIP created: {output_zip}")
