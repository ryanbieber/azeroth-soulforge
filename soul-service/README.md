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

Provider credentials are encrypted with `SOULFORGE_SECRETS_KEY`, never returned
through the admin API, and excluded from exports. The service describes persistent role-play identity as a "soul," but it never
claims that the model is conscious or sentient. Model output is social text
only and cannot issue gameplay commands.

Run its tests from the repository root with `./scripts/verify.sh` or directly:

```bash
PYTHONPATH=soul-service/src python3 -m unittest discover -s soul-service/tests
```
