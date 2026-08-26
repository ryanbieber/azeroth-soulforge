#!/usr/bin/env python3
"""Validate the dependency-free GitHub Pages site without network access."""

from html.parser import HTMLParser
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.add(str(values["id"]))
        if tag in {"a", "link", "script"}:
            target = values.get("href") or values.get("src")
            if target:
                self.links.append(target)


def main() -> None:
    source = (SITE / "index.html").read_text(encoding="utf-8")
    parser = PageParser()
    parser.feed(source)
    required = {"requirements", "configure", "launch", "connect", "first-soul", "troubleshooting"}
    missing = required - parser.ids
    if missing:
        raise SystemExit(f"site/index.html missing sections: {sorted(missing)}")
    if "YOUR_LAN_IP" not in source or "set realmlist YOUR_LAN_IP" not in source:
        raise SystemExit("site must teach generic LAN and realmlist configuration")
    if re.search(r"(?:password|secret)\s*=\s*(?!YOUR_|replace-)[^<\s]+", source, re.I):
        raise SystemExit("site may contain a credential-like value")
    for target in parser.links:
        if target.startswith("#") and target[1:] not in parser.ids:
            raise SystemExit(f"broken page fragment: {target}")
        if target.startswith(("http://", "https://", "mailto:")) or target.startswith("#"):
            continue
        path = SITE / target.split("?", 1)[0].split("#", 1)[0]
        if not path.is_file():
            raise SystemExit(f"missing local site asset: {target}")
    print("GitHub Pages static site validation passed.")


if __name__ == "__main__":
    main()
