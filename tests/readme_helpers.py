import re
from pathlib import Path


README_PATH = Path(__file__).resolve().parents[1] / "README.md"


def extract_h2_sections(markdown):
    sections = {}
    current_title = None
    current_lines = []
    fence_character = None
    fence_length = 0

    for line in markdown.splitlines():
        fence_match = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if fence_character is not None:
            if current_title is not None:
                current_lines.append(line)
            if re.fullmatch(
                rf"\s{{0,3}}{re.escape(fence_character)}"
                rf"{{{fence_length},}}\s*",
                line,
            ):
                fence_character = None
            continue
        if fence_match:
            if current_title is not None:
                current_lines.append(line)
            fence = fence_match.group(1)
            fence_character = fence[0]
            fence_length = len(fence)
            continue

        heading_match = re.match(r"^\s{0,3}##[ \t]+(.+?)\s*#*\s*$", line)
        if heading_match:
            if current_title is not None:
                sections[current_title] = "\n".join(current_lines)
            current_title = heading_match.group(1).strip()
            current_lines = []
        elif current_title is not None:
            current_lines.append(line)

    if current_title is not None:
        sections[current_title] = "\n".join(current_lines)
    return sections


def extract_h1_title(markdown):
    match = re.search(r"(?m)^\s{0,3}#(?!#)[ \t]+(.+?)\s*#*\s*$", markdown)
    return match.group(1).strip() if match else None
