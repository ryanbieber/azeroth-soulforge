# Soul Service

The Soul Service owns persistent bot identities, memories, Ollama inference,
and the durable reply outbox. It is a standard-library Python HTTP service with
a SQLite WAL database, authenticated bridge requests, nonce replay protection,
idempotent event ingestion, and a loopback-only profile dashboard.

Runtime configuration comes from the `SOULFORGE_*` and `OLLAMA_*` environment
variables in the root `compose.yaml`. The versioned endpoints are documented in
`contracts/openapi.yaml`; the health endpoint is `GET /health`.

The service describes persistent role-play identity as a "soul," but it never
claims that the model is conscious or sentient. Ollama output is social text
only and cannot issue gameplay commands.

Run its tests from the repository root with `./scripts/verify.sh` or directly:

```bash
PYTHONPATH=soul-service/src python3 -m unittest discover -s soul-service/tests
```
