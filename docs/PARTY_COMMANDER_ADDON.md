# Party Commander addon

`PartyCommander` is a small **WoW 3.3.5a client addon** for a human tank who
leads Playerbot companions. It sends supported Playerbots commands to the
current party or raid. It does not communicate with Soulforge, Ollama, or the
server administration API.

## Install

1. Copy `addons/PartyCommander` from this repository into the WoW client's
   `Interface/AddOns/PartyCommander` directory. The final directory must
   contain both `PartyCommander.toc` and `PartyCommander.lua`.
2. Start the 3.3.5a client and enable **Party Commander** on the character
   selection screen.
3. Log in and drag the small panel where you want it. Use `/pc show` or
   `/pc hide` when needed.

The companion default is `Wife`. If you rename or replace that shaman, use:

```text
/pc wife CharacterName
```

## Five tank commands

The panel and controller bindings deliberately contain only five actions:
**Follow**, **Hold**, **Attack**, **Rebuff**, and **Flee**. Normal commands are
sent to `PARTY` in a group of five and `RAID` automatically in a raid. Select
an enemy before **Attack**; as the human tank, that sends the group after your
target.

| Panel control | Recipient |
| --- | --- |
| Click | Whole current party or raid |
| Ctrl + click | `Wife` only |
| Shift + click | Playerbots with the healer role |

Ctrl wins if both are held. `Wife` is a shaman, so **Rebuff** is the usual
quick pre-pull request. Her healing remains governed by Playerbots' normal
combat AI, not a language model.

## Controller bindings

Open **Esc → Key Bindings → Party Commander** and assign only six controller
inputs: the five actions plus **Cycle command scope**. Bind the five commands
to your comfortable D-pad or face-button combinations. Bind Cycle command
scope to one spare chord; each press changes its target in this order:

```text
whole group → Wife → healers → whole group
```

The chat frame confirms the selected scope, so you know where the next
controller command will go. The addon never overwrites controller, keyboard,
or action-bar bindings; this works with a controller-mapping addon such as
ConsolePort because it uses normal WoW key bindings.

## In-game activation

The addon sends commands but does not add a character to Playerbots. From your
main character, add Wife once after creating her and logging her out:

```text
.playerbots bot add Wife
```

She must share your main character's faction to join your party or raid.
