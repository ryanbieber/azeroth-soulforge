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
                "ConsolePort/Config/Lookup.lua",
                "ConsolePort/Frames/Utility.lua",
                "ConsolePort/Controllers/XBOX/Xbox.lua",
                "ConsolePort/Controllers/PS4/PS4.lua",
                "ConsolePortBar/ConsolePortBar.toc",
                "ConsolePortBar/Core/Bar.lua",
                "ConsolePortKeyboard/ConsolePortKeyboard.toc",
            }
            names = {item.filename for item in files}
            missing = required - names
            if missing:
                raise ValueError(f"archive is missing required files: {sorted(missing)}")

            utility = archive.read("ConsolePort/Frames/Utility.lua").decode("utf-8", errors="strict")
            lookup = archive.read("ConsolePort/Config/Lookup.lua").decode("utf-8", errors="strict")
            bar = archive.read("ConsolePortBar/Core/Bar.lua").decode("utf-8", errors="strict")
            for marker in (
                "function ConsolePort:SetupUtilityBindings()",
                "function Utility:Refresh()",
                "function Utility:GetBindingForSet(setID)",
            ):
                if marker not in utility:
                    raise ValueError(f"ConsolePortLK utility API is incompatible: missing {marker}")
            if "function ConsolePort:GetData" not in lookup:
                raise ValueError("ConsolePortLK plugin data API is incompatible")
            if "RegisterCallback('OnNewBindings', Bar.OnNewBindings" not in bar:
                raise ValueError("ConsolePortBar does not refresh after utility binding changes")
            for controller in ("XBOX", "PS4"):
                source = archive.read(
                    f"ConsolePort/Controllers/{controller}/{controller.title() if controller == 'XBOX' else controller}.lua"
                ).decode("utf-8", errors="strict")
                if "'CLICK ConsolePortUtilityToggle:LeftButton'" not in source:
                    raise ValueError(f"{controller} profile lacks the default utility-ring chord")
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
