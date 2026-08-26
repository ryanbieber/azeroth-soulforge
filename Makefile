COMPOSE ?= docker compose

.PHONY: up down dev-up status logs models verify

up:
	COMPOSE="$(COMPOSE)" ./scripts/app-up.sh

down:
	COMPOSE="$(COMPOSE)" ./scripts/app-down.sh

dev-up:
	$(COMPOSE) --env-file .env.example up --detach --build mariadb ollama soul-service
	@$(COMPOSE) ps

status:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs --follow --tail=100

models:
	$(COMPOSE) exec ollama ollama pull qwen3:4b
	$(COMPOSE) exec ollama ollama pull embeddinggemma:300m-qat-q4_0

verify:
	./scripts/verify.sh
