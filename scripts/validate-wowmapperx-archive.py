#!/usr/bin/env python3
"""Validate the pinned legacy WoWmapperX Windows archive."""

from __future__ import annotations

import argparse
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile


EXPECTED_FILES = {
    "libHarfBuzzSharp.dll",
    "libSkiaSharp.dll",
    "WoWmapperX.exe",
    "WoWmapperX_Updater.exe",
    "av_libglesv2.dll",
}


def validate(path: str) -> None:
    try:
        with ZipFile(path) as archive:
            files = [item for item in archive.infolist() if not item.is_dir()]
            names = {item.filename for item in files}
            if names != EXPECTED_FILES:
                raise ValueError(
                    f"unexpected WoWmapperX files: expected {sorted(EXPECTED_FILES)}, got {sorted(names)}"
                )
            for item in files:
                candidate = PurePosixPath(item.filename)
                if candidate.is_absolute() or ".." in candidate.parts or len(candidate.parts) != 1:
                    raise ValueError(f"unsafe WoWmapperX path: {item.filename}")
                mode = item.external_attr >> 16
                if mode & 0o170000 == 0o120000:
                    raise ValueError(f"symbolic links are not allowed: {item.filename}")
                with archive.open(item) as handle:
                    if handle.read(2) != b"MZ":
                        raise ValueError(f"expected a Windows PE file: {item.filename}")
    except BadZipFile as error:
        raise ValueError("archive is not a valid ZIP file") from error


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive")
    args = parser.parse_args()
    validate(args.archive)
    print("WoWmapperX archive validation passed.")


if __name__ == "__main__":
    main()
