.PHONY: up-core down-core logs-core up-assistant up-audio backup restore-check

up-core:
	docker compose -f infra/turingpi2/compose/core.yml up -d

down-core:
	docker compose -f infra/turingpi2/compose/core.yml down

logs-core:
	docker compose -f infra/turingpi2/compose/core.yml logs -f

up-assistant:
	docker compose -f infra/turingpi2/compose/assistant.yml up -d

up-audio:
	docker compose -f infra/turingpi2/compose/audio.yml up -d

backup:
	ops/backup/backup.sh

restore-check:
	ops/backup/restore-check.sh
