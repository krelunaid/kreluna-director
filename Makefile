.PHONY: install test demo api agent web lint mac windows agents installers

install:
	python3 -m pip install -e ".[dev]"
	cd apps/director-web && npm install

test:
	python3 -m pytest -q

lint:
	python3 -m ruff check packages apps tests || true

api:
	PYTHONPATH=packages/kreluna-shared/src:apps/director-api python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8080

agent:
	PYTHONPATH=packages/kreluna-shared/src:apps/kreluna-agent python3 -m agent.main

web:
	cd apps/director-web && npm run dev -- --host 127.0.0.1 --port 5173

demo:
	bash scripts/run-demo.sh

mac:
	bash scripts/macos/build-mac-app.sh

windows:
	bash scripts/windows/build-windows-zip.sh

installers:
	bash scripts/build-installers.sh

agents:
	bash scripts/windows/build-agent-zip.sh
