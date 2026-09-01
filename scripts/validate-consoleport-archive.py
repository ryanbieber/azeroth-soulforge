#!/usr/bin/env python3
"""Validate the pinned ConsolePortLK client-addon archive layout."""

from __future__ import annotations

import argparse
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile


EXPECTED_ROOTS = {
    "ConsolePort",
    "ConsolePortAdvanced",
    "ConsolePortBar",
    "ConsolePortHelp",
    "ConsolePortKeyboard",
    "ConsolePortLoader",
    "ConsolePortUI_Loot",
    "ConsolePortUI_Menu",
}


def validate(path: str) -> None:
    try:
        with ZipFile(path) as archive:
            files = [item for item in archive.infolist() if not item.is_dir()]
            if not files:
                raise ValueError("archive contains no files")
            roots: set[str] = set()
            for item in files:
                candidate = PurePosixPath(item.filename)
                if candidate.is_absolute() or ".." in candidate.parts or len(candidate.parts) < 2:
                    raise ValueError(f"unsafe archive path: {item.filename}")
                roots.add(candidate.parts[0])
                mode = item.external_attr >> 16
                if mode & 0o170000 == 0o120000:
                    raise ValueError(f"symbolic links are not allowed: {item.filename}")
            if roots != EXPECTED_ROOTS:
                raise ValueError(
                    f"unexpected addon roots: expected {sorted(EXPECTED_ROOTS)}, got {sorted(roots)}"
                )
            required = {
                "ConsolePort/ConsolePort.toc",
                "ConsolePort/LICENSE.md",
                "ConsolePortBar/ConsolePortBar.toc",
                "ConsolePortKeyboard/ConsolePortKeyboard.toc",
            }
            names = {item.filename for item in files}
            missing = required - names
            if missing:
                raise ValueError(f"archive is missing required files: {sorted(missing)}")
    except BadZipFile as error:
        raise ValueError("archive is not a valid ZIP file") from error


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive")
    args = parser.parse_args()
    validate(args.archive)
    print("ConsolePortLK archive validation passed.")


if __name__ == "__main__":
    main()
