Soulforge Commander 2.1 for World of Warcraft 3.3.5a

Install the complete Azeroth Soulforge Client Addons pack from the private
dashboard. Extract every top-level folder directly into Interface/AddOns. The
pack includes the pinned ConsolePortLK modules required by this addon.

WoWmapperX supplies the controller-to-keyboard/mouse input that legacy WoW
needs. Start WoWmapperX before WoW. Soulforge then assigns its managed ring to
ConsolePort's default utility-ring chord (both modifiers + lower face button),
so it appears on ConsolePortBar without manual ring setup. No movement binding
is replaced.

After controller input is active:

1. Open ConsolePort configuration and its Ring Manager.
2. Select the automatically created "Soulforge Commander" ring.
3. Hold the default utility-ring chord, aim with ConsolePort's radial stick, and
   release to issue
   Follow, Stay, Attack, Tank Pull, Flee, Reset, Rebuff, or open Companions.
5. The Companions panel is controller navigable. Sync the active world, enable
   or disable entries, choose a command target, and select Assemble enabled.

/sfc opens Companions. /sfc sync refreshes the roster. /sfc assemble invites
enabled companions. /sfc status prints integration diagnostics. `/sfc unbind`
restores the prior ConsolePort utility action; `/sfc bind` enables Commander on
the bar chord again.

Every order is a user-initiated Playerbots chat command. The addon never calls
an external URL, never controls AI, and never changes controller bindings.
