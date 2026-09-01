# mod-soulbridge

This AzerothCore module moves approved chat events to the Soul Service and
delivers returned bot dialogue on the world thread. It observes direct whispers
and human-authored companion mentions in say, party, raid, guild, and public
channel chat. Replies return through the originating chat destination. A bounded queue keeps the world thread
free of network, database, and inference work; worker threads own signed HTTP
transport, polling, acknowledgement, and retry.

For human-authored `/say` and public-channel lines that do not address a
companion, the bridge may select one same-faction random Playerbot in the same
zone as an ambient-dialogue candidate. `/say` candidates must also be within 60
yards. The event carries the zone and channel name to the Soul Service, which
applies its probability and global cooldown before any inference. Generated bot
messages are rejected by the capture hooks, so ambient chatter cannot create a
bot-to-bot reply chain.

The same bounded queue captures compact social gameplay signals for a human and
their controlled Playerbots: player or companion death, resurrection, human
level-up, quest completion, and dungeon/world-boss kills. Hooks only assemble
and enqueue JSON; HTTP, inference, and SQLite remain off the world thread.
Routine damage, movement, combat ticks, loot spam, and random-bot activity are
not captured.

Soulforge Commander can issue `.soulforge roster` as an ordinary player. The
command only queues an internal signed roster request. Soulbridge resolves it on
the worker thread and returns machine-readable system messages on the world
thread, so the addon can refresh Companion Setup without direct network access
or a new download.

The module is copied into the pinned upstream source tree by
`scripts/setup-source.sh` and is built into the local worldserver image. Its
configuration template is `conf/soulbridge.conf.dist`.

The module must always preserve the invariants in the root `AGENTS.md`:

- World hooks enqueue and return without blocking.
- Worker threads own transport and retry.
- Reply IDs are held pending to prevent duplicate delivery and acknowledged only
  after successful same-channel delivery.
- The LLM never emits gameplay commands.
