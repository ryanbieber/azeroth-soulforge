COMPOSE ?= docker compose

.PHONY: doctor setup bots up down status logs models account backup firewall verify

doctor:
	./scripts/check-host.sh

setup:
	./scripts/setup-source.sh

bots:
	COMPOSE="$(COMPOSE)" ./scripts/app-up.sh --bots-only

up:
	COMPOSE="$(COMPOSE)" ./scripts/app-up.sh

down:
	COMPOSE="$(COMPOSE)" ./scripts/app-down.sh

status:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs --follow --tail=100

models:
	$(COMPOSE) exec ollama ollama pull qwen3.5:4b

account:
	./scripts/create-account.sh

backup:
	./scripts/backup-databases.sh

firewall:
	./scripts/configure-firewall.sh

verify:
	./scripts/verify.sh
