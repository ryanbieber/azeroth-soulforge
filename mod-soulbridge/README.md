# mod-soulbridge

This directory will become the AzerothCore module that moves approved world
events to the Soul Service and schedules returned chat replies.

The initial code is a dependency-free, bounded queue primitive that can be
compiled and tested outside AzerothCore. It deliberately performs no HTTP,
inference, database access, or world mutation. AzerothCore hooks and its
world-thread scheduler will be added only after the pinned upstream compatibility
spike.

The module must always preserve the invariants in the root `AGENTS.md`:

- World hooks enqueue and return without blocking.
- Worker threads own transport and retry.
- Reply IDs are deduplicated before delivery.
- The LLM never emits gameplay commands.
