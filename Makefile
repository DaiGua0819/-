install:
	python -m pip install -e .

lint:
	ruff check .
	ruff format --check .

format:
	ruff format .

test:
	pytest -q

config-validate:
	xvi config validate

fixture-capture:
	xvi fixture capture

docker-build:
	docker compose build

docker-up:
	docker compose up -d xvi

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f xvi

docker-status:
	docker compose exec xvi supervisorctl status

docker-worker-rerun:
	docker compose exec xvi supervisorctl start browser-worker
