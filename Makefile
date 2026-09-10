.PHONY: up-core down-core logs-core up-assistant up-audio backup restore-check coordination-refresh coordination-status coordination-directive

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

coordination-refresh:
	python3 scripts/lab-console refresh
	python3 scripts/world_state.py
	python3 scripts/lab-console refresh

coordination-status:
	python3 scripts/lab-console status

coordination-directive:
	@echo 'Usage: python3 scripts/lab-console new-directive TARGET "INSTRUCTION" [options]'
