"""Build GitHub release notes from localized changelog entries."""

import argparse
import re
from pathlib import Path


_RELEASE_HEADING_RE = re.compile(
    r"^## (?P<version>\d+\.\d+\.\d+) - (?P<date>\d{4}-\d{2}-\d{2})\s*$",
    re.MULTILINE)


def extract_release_notes(changelog, version):
    """버전 제목 다음부터 다음 버전 제목 전까지의 Markdown을 반환한다."""
    matches = list(_RELEASE_HEADING_RE.finditer(changelog))
    selected = [item for item in matches if item.group("version") == version]
    if len(selected) != 1:
        raise ValueError(
            "CHANGELOG.md에서 %s 버전 항목을 하나만 찾을 수 있어야 합니다."
            % version)
    match = selected[0]
    index = matches.index(match)
    end = matches[index + 1].start() if index + 1 < len(matches) \
        else len(changelog)
    notes = changelog[match.end():end].strip()
    if not notes:
        raise ValueError("%s 버전의 변경 내용이 비어 있습니다." % version)
    return notes + "\n"


def compose_localized_release_notes(version, english, korean):
    """Compose a bilingual body that the updater can select by UI language."""
    sections = []
    for code, title, changelog in (
            ("en", "English", english), ("ko", "한국어", korean)):
        notes = extract_release_notes(changelog, version).strip()
        sections.append(
            "## %s\n\n"
            "<!-- spdf-release-notes:start:%s -->\n%s\n"
            "<!-- spdf-release-notes:end:%s -->"
            % (title, code, notes, code))
    return "\n\n".join(sections) + "\n"


def compose_localized_documents(version, english, korean):
    """Publish only the requested version, retaining updater language markers."""
    return compose_localized_release_notes(version, english, korean)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--changelog", default="CHANGELOG.md")
    parser.add_argument("--changelog-ko")
    parser.add_argument("--release-notes")
    parser.add_argument("--release-notes-ko")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    if args.release_notes or args.release_notes_ko:
        if not args.release_notes or not args.release_notes_ko:
            parser.error(
                "--release-notes and --release-notes-ko must be used together")
        english = Path(args.release_notes).read_text(encoding="utf-8")
        korean = Path(args.release_notes_ko).read_text(encoding="utf-8")
        notes = compose_localized_documents(args.version, english, korean)
    elif args.changelog_ko:
        changelog = Path(args.changelog).read_text(encoding="utf-8")
        korean = Path(args.changelog_ko).read_text(encoding="utf-8")
        notes = compose_localized_release_notes(
            args.version, changelog, korean)
    else:
        changelog = Path(args.changelog).read_text(encoding="utf-8")
        notes = extract_release_notes(changelog, args.version)
    Path(args.output).write_text(notes, encoding="utf-8")


if __name__ == "__main__":
    main()
