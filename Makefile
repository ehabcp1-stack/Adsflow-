# AdFlow AI — common tasks
.PHONY: help install seed api web dev test build lint migrate reset docker

help:
	@echo "install  – install backend + frontend dependencies"
	@echo "seed     – seed the demo project «مدينة الورد»"
	@echo "api      – run the API on :8000"
	@echo "web      – run the live preview on :3000"
	@echo "test     – backend tests + frontend typecheck/lint"
	@echo "build    – production frontend build (stop 'make web' first)"
	@echo "migrate  – alembic upgrade head"
	@echo "reset    – rebuild the database and reseed"
	@echo "docker   – docker compose up --build"

install:
	cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
	cd frontend && npm install

seed:
	cd backend && .venv/bin/python -m app.seed

reset:
	cd backend && .venv/bin/python -m app.seed --reset

api:
	cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000

web:
	cd frontend && npm run dev

test:
	cd backend && .venv/bin/python -m pytest -q
	cd frontend && npm run typecheck && npm run lint

build:
	cd frontend && npm run build

migrate:
	cd backend && .venv/bin/alembic upgrade head

docker:
	docker compose up --build
