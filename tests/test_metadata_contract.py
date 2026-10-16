from pathlib import Path

from tests.readme_helpers import README_PATH, extract_h1_title


METADATA_PATH = (
    Path(__file__).resolve().parents[1]
    / "Delft3DFileManager"
    / "metadata.txt"
)
REQUIRED_METADATA_FIELDS = {
    "name",
    "version",
    "description",
    "author",
    "repository",
    "about",
    "changelog",
}


def _parse_general_metadata(text):
    fields = {}
    section = None
    current_field = None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1].strip().lower()
            current_field = None
            continue
        if section != "general":
            continue
        if line[0].isspace():
            if current_field is not None:
                fields[current_field] += "\n" + stripped
            continue
        key, separator, value = line.partition("=")
        if separator:
            current_field = key.strip().lower()
            fields[current_field] = value.strip()

    return fields


def test_metadata_has_required_general_fields():
    metadata = _parse_general_metadata(METADATA_PATH.read_text(encoding="utf-8"))
    missing = REQUIRED_METADATA_FIELDS.difference(metadata)
    assert not missing, f"Plugin metadata is missing fields: {sorted(missing)}"

    empty = sorted(field for field in REQUIRED_METADATA_FIELDS if not metadata[field])
    assert not empty, f"Plugin metadata fields must not be empty: {empty}"


def test_metadata_name_matches_readme_title():
    metadata = _parse_general_metadata(METADATA_PATH.read_text(encoding="utf-8"))
    readme_title = extract_h1_title(README_PATH.read_text(encoding="utf-8"))

    assert readme_title
    assert metadata.get("name") == readme_title
