#!/usr/bin/env python3
"""Static compatibility checks for the bundled WoW 3.3.5a Party Commander addon."""

from pathlib import Path
import xml.etree.ElementTree as ET


root = Path(__file__).resolve().parents[1] / "addons" / "PartyCommander"
toc = (root / "PartyCommander.toc").read_text(encoding="utf-8")
lua = (root / "PartyCommander.lua").read_text(encoding="utf-8")
bindings = ET.parse(root / "Bindings.xml").getroot()

if "## Interface: 30300" not in toc:
    raise SystemExit("Party Commander must target the WoW 3.3.5a interface")

for marker in ("GetNumRaidMembers()", "GetNumPartyMembers()", "@heal ", "Wife", "SendChatMessage", "CycleControllerScope"):
    if marker not in lua:
        raise SystemExit(f"Party Commander is missing required behavior: {marker}")

names = {node.attrib.get("name") for node in bindings.findall("Binding")}
for binding in ("FOLLOW", "HOLD", "ATTACK", "REBUFF", "FLEE", "CYCLE_SCOPE"):
    expected = f"PARTYCOMMANDER_{binding}"
    if expected not in names:
        raise SystemExit(f"Party Commander binding missing: {expected}")

print("Party Commander addon validation passed.")
