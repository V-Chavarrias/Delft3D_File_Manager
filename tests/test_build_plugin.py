import runpy
import zipfile
from pathlib import Path

from build_plugin import PACKAGE_NAME, add_readme_to_archive, get_version


def test_guide_is_packaged_at_plugin_root(tmp_path):
    readme_path = tmp_path / "README.md"
    readme_path.write_text("# User guide", encoding="utf-8")
    archive_path = tmp_path / "plugin.zip"

    with zipfile.ZipFile(archive_path, "w") as archive:
        add_readme_to_archive(archive, str(readme_path))

    with zipfile.ZipFile(archive_path) as archive:
        assert archive.read("Delft3DFileManager/README.md") == b"# User guide"


def test_build_archive_packages_repository_readme_metadata_and_version(
    tmp_path, monkeypatch
):
    repo_root = Path(__file__).resolve().parents[1]
    readme_bytes = (repo_root / "README.md").read_bytes()
    metadata_bytes = (
        repo_root / "Delft3DFileManager" / "metadata.txt"
    ).read_bytes()
    plugin_folder = tmp_path / "Delft3DFileManager"
    plugin_folder.mkdir()
    (plugin_folder / "metadata.txt").write_bytes(metadata_bytes)
    (tmp_path / "README.md").write_bytes(readme_bytes)
    (tmp_path / "LICENSE").write_bytes((repo_root / "LICENSE").read_bytes())

    monkeypatch.chdir(tmp_path)
    metadata_path = plugin_folder / "metadata.txt"
    version = get_version(str(metadata_path))
    runpy.run_path(str(repo_root / "build_plugin.py"), run_name="__main__")

    archive_path = tmp_path / f"{PACKAGE_NAME}_v{version}.zip"
    assert archive_path.is_file()
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        assert "Delft3DFileManager/README.md" in names
        assert "Delft3DFileManager/metadata.txt" in names
        assert archive.read("Delft3DFileManager/README.md") == readme_bytes

        packaged_metadata = archive.read("Delft3DFileManager/metadata.txt")
        assert packaged_metadata == metadata_bytes
        packaged_metadata_path = tmp_path / "packaged-metadata.txt"
        packaged_metadata_path.write_bytes(packaged_metadata)
        packaged_version = get_version(str(packaged_metadata_path))
        assert archive_path.name == f"{PACKAGE_NAME}_v{packaged_version}.zip"