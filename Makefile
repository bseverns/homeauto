.PHONY: up-core down-core logs-core up-assistant up-audio backup restore-check

up-core:
	docker compose -f infra/roles/compose/core.yml up -d

down-core:
	docker compose -f infra/roles/compose/core.yml down

logs-core:
	docker compose -f infra/roles/compose/core.yml logs -f

up-assistant:
	docker compose -f infra/roles/compose/assistant.yml up -d

up-audio:
	docker compose -f infra/roles/compose/audio.yml up -d

backup:
	ops/backup/backup.sh

restore-check:
	ops/backup/restore-check.sh
