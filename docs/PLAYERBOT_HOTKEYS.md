# Playerbots party hotkeys

> **Fallback workflow:** Soulforge Commander is now the primary interface. The
> dashboard packages a hold-to-open radial command wheel with mouse-direction
> selection. Keep these macros only for troubleshooting or commands not yet on
> the wheel.

Use **Assemble** after login to pace four `.playerbots bot add` commands for
Richpiana, Wife, Donaldtrump, and Samhyde. Playerbots logs them in and invites
them to the owner's group; the remaining wheel actions then control the party.

These commands match Soulforge's pinned `mod-playerbots` revision. Put each
line in a WoW macro and drag the macro to an action-bar hotkey. Use `/p` for a
five-player party. In a raid, use `/ra` to reach the whole raid.

## Core party macros

| Purpose | Macro |
| --- | --- |
| Resume following | `/p follow` |
| Hold the current position | `/p stay` |
| Attack your selected target | `/p attack` |
| Send only the tank first | `/p @tank tank attack` |
| Make only the tank pull | `/p @tank pull` |
| Stop fighting and follow you away | `/p flee` |
| Emergency spread away | `/p runaway` |
| Seek nearby valid enemies | `/p grind` |
| Ask for a ready check | `/p ready` |
| Reconsider all buffs | `/p rebuff` |
| Reset AI strategies to defaults | `/p reset` |

## Targeted commands

Prefix a command to address only a role:

```text
@tank @heal @dps @ranged @melee @rangeddps @meleedps
```

For example, `/p @heal stay` holds healers in place while everyone else keeps
following. Class prefixes are also supported: `@warrior`, `@paladin`,
`@hunter`, `@rogue`, `@priest`, `@dk`, `@shaman`, `@mage`, `@warlock`, and
`@druid`.

Raid leaders can target subgroups with prefixes such as `@group1` or
`@group1-3`, and raid-marker prefixes are supported: `@star`, `@circle`,
`@diamond`, `@triangle`, `@moon`, `@square`, `@cross`, and `@skull`. A level
or level range can also be addressed, for example `/p @19 stay` or
`/ra @10-19 follow`.

Commands can also be sent to one bot with a whisper:

```text
/w Botname stay
```

## Controller-ready general macros

Create these as **General Macros** (leave Character Specific unchecked). They
will then be available to every character on the same WoW account, so you only
need to put them on matching action-bar slots and map those slots through your
controller software once per character layout. A server cannot create client
macros for you, so this is the supported account-wide approach.

Normal press controls your current party or raid automatically. Hold **Ctrl**
to whisper `Wife` only; hold **Shift** to reach healer-role bots. Ctrl takes
priority if both are held. Replace `Wife` with another companion name only if
you rename that character.

| Macro | Body |
| --- | --- |
| Follow | `/run w=IsControlKeyDown();SendChatMessage(w and"follow"or(IsShiftKeyDown()and"@heal follow"or"follow"),w and"WHISPER"or(GetNumRaidMembers()>0 and"RAID"or"PARTY"),nil,w and"Wife")` |
| Hold | `/run w=IsControlKeyDown();SendChatMessage(w and"stay"or(IsShiftKeyDown()and"@heal stay"or"stay"),w and"WHISPER"or(GetNumRaidMembers()>0 and"RAID"or"PARTY"),nil,w and"Wife")` |
| Attack | `/run w=IsControlKeyDown();SendChatMessage(w and"attack"or(IsShiftKeyDown()and"@heal attack"or"attack"),w and"WHISPER"or(GetNumRaidMembers()>0 and"RAID"or"PARTY"),nil,w and"Wife")` |
| Rebuff | `/run w=IsControlKeyDown();SendChatMessage(w and"rebuff"or(IsShiftKeyDown()and"@heal rebuff"or"rebuff"),w and"WHISPER"or(GetNumRaidMembers()>0 and"RAID"or"PARTY"),nil,w and"Wife")` |
| Flee | `/run w=IsControlKeyDown();SendChatMessage(w and"flee"or(IsShiftKeyDown()and"@heal flee"or"flee"),w and"WHISPER"or(GetNumRaidMembers()>0 and"RAID"or"PARTY"),nil,w and"Wife")` |

Start with follow, stay, attack, tank attack, pull, flee, and reset. Test more
specialized strategy commands outside an instance before relying on them in a
raid.
