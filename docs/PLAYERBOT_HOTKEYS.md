# Playerbots party hotkeys

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

Start with follow, stay, attack, tank attack, pull, flee, and reset. Test more
specialized strategy commands outside an instance before relying on them in a
raid.
