import zipfile

from build_plugin import add_readme_to_archive


def test_guide_is_packaged_at_plugin_root(tmp_path):
    readme_path = tmp_path / "README.md"
    readme_path.write_text("# User guide", encoding="utf-8")
    archive_path = tmp_path / "plugin.zip"

    with zipfile.ZipFile(archive_path, "w") as archive:
        add_readme_to_archive(archive, str(readme_path))

    with zipfile.ZipFile(archive_path) as archive:
        assert archive.read("Delft3DFileManager/README.md") == b"# User guide"