# Soul Service

The Soul Service owns immutable world canon, played-world time, narrative plans,
persistent bot identities, memories, provider routing, usage accounting, and
the durable reply outbox. It is a small Python HTTP service with
a SQLite WAL database, authenticated bridge requests, nonce replay protection,
idempotent event ingestion, and authenticated administration APIs. A production
React bundle is served by the service and exposed only through the HTTPS gateway.

Runtime configuration comes from the `SOULFORGE_*` and `OLLAMA_*` environment
variables in the root `compose.yaml`. The versioned endpoints are documented in
`contracts/openapi.yaml`; the health endpoint is `GET /health`. Dashboard
endpoints are described separately in `contracts/admin-openapi.yaml`.

The authenticated addon endpoints report package metadata and produce one
client ZIP from checksum-verified ConsolePortLK and WoWmapperX archives plus the
repository's Soulforge Commander source. The third-party archives are runtime data mounted
read-only from `runtime/client-addons`; it is never committed or served by the
public GitHub Pages site.

Provider credentials are encrypted with `SOULFORGE_SECRETS_KEY`, never returned
through the admin API, and excluded from exports. The service describes persistent role-play identity as a "soul," but it never
claims that the model is conscious or sentient. Model output is social text
only and cannot issue gameplay commands.

Every routed inference emits one `ai_call` JSON log line containing the route,
provider, model, success state, latency, and input/cached-input/output/reasoning/
total token counts. Prompt and response text and provider credentials are never
written to this operational log. Follow it with:

```bash
docker compose logs --follow soul-service | grep ai_call
```

AI Studio keeps the monthly totals and plots input versus output tokens in
hourly buckets over the latest 24 hours.

Human-authored messages can start companion dialogue by whispering a companion
or mentioning its character name in say, party, raid, guild, or a public channel
such as General. The durable outbox preserves that destination so the generated
reply appears in the same chat. Bot-authored output is never ingested again,
which prevents generated reply loops.

Random world bots use a separate local `ambient` route, defaulting to
`qwen3:1.7b` with a 96-token ceiling. Only a low configurable percentage of
human-authored say and public-channel messages receives one ambient response,
with a global cooldown. Fresh installs default to the measured maximum controls:
a 25 percent chance and five-second global cooldown, or at most 12 ambient
replies per minute. Public ambient replies require the current zone name in the
channel name, so General and LocalDefense remain local. The built-in `Trade -
City` channel is also eligible because the game only makes it available in
trade-enabled cities and shares it across those cities. World and
LookingForGroup are ignored. The compact prompt includes the actual zone and
channel and asks for era-appropriate, zone-specific realm culture without
storing deep personal memory for disposable population bots. AI Studio exposes
the route, reply chance, cooldown, and per-companion prompt previews.

Companion, ambient, and companion-to-companion prompts request only the literal
first-person words the character would type into WoW chat. A final delivery
guard removes speaker labels, wrapping quotation marks, and leading emotes, and
suppresses narration or third-person stage directions rather than displaying
them in game.

Run its tests from the repository root with `./scripts/verify.sh` or directly:

```bash
PYTHONPATH=soul-service/src python3 -m unittest discover -s soul-service/tests
```
