# Soul Service

The Soul Service will own persistent identities, relationships, memory,
retrieval, Ollama scheduling, the reply outbox, and the local dashboard.

The initial scaffold implements and tests the idempotent inbox/durable-delivery
semantics in memory. It is not yet an HTTP server and does not pretend to be a
production persistence layer. Its container exposes only a development health
endpoint. Later milestones will replace the repository adapter with SQLite,
expose the versioned FastAPI contract, and add Ollama inference.

Run its tests from the repository root with `./scripts/verify.sh` or directly:

```bash
PYTHONPATH=soul-service/src python3 -m unittest discover -s soul-service/tests
```
