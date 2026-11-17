.PHONY: frontend-install frontend-dev backend-install backend-dev db-up build

frontend-install:
	cd frontend && bun install --frozen-lockfile

frontend-dev:
	cd frontend && bun run dev

backend-install:
	cd backend && uv sync --extra dev

# Export the backend environment before running this target.
backend-dev:
	cd backend && uv run uvicorn app_core.main:create_app --factory --host 127.0.0.1 --port 8000

db-up:
	docker compose up -d db

build:
	cd frontend && bun run build
