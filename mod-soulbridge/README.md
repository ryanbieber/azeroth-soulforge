# mod-soulbridge

This AzerothCore module moves approved chat events to the Soul Service and
delivers returned bot whispers on the world thread. It observes direct whispers
and bot mentions in group or guild chat. A bounded queue keeps the world thread
free of network, database, and inference work; worker threads own signed HTTP
transport, polling, acknowledgement, and retry.

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
  after a successful whisper.
- The LLM never emits gameplay commands.
