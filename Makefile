.PHONY: install test lint eval smoke-service readiness-audit release-evidence production-approval-bundle wheel docker-build check clean

install:
	python3 -m venv .venv
	.venv/bin/python -m pip install -e '.[dev]'

test:
	PYTHONWARNINGS=ignore .venv/bin/python -m pytest

lint:
	PYTHONWARNINGS=ignore .venv/bin/python -m ruff check src tests

eval:
	PYTHONWARNINGS=ignore .venv/bin/python -m self_correcting_langgraph_agent.evaluator

smoke-service:
	PYTHONWARNINGS=ignore sh scripts/smoke_service.sh

readiness-audit:
	PYTHONWARNINGS=ignore .venv/bin/python scripts/production_readiness_audit.py

release-evidence:
	PYTHONWARNINGS=ignore .venv/bin/python scripts/production_readiness_audit.py >/tmp/self-correcting-agent-production-readiness-audit.json
	PYTHONWARNINGS=ignore .venv/bin/python -m self_correcting_langgraph_agent.release_evidence --run-checks-exit-code 0 --readiness-audit /tmp/self-correcting-agent-production-readiness-audit.json --release-manifest /tmp/self-correcting-agent-release-manifest.json --output /tmp/self-correcting-agent-release-evidence.json

production-approval-bundle:
	PYTHONWARNINGS=ignore sh scripts/production_approval_bundle.sh --strict

wheel:
	rm -rf /tmp/self-correcting-agent-wheelhouse
	PYTHONWARNINGS=ignore .venv/bin/python -m pip wheel --no-deps --no-build-isolation . -w /tmp/self-correcting-agent-wheelhouse
	ls /tmp/self-correcting-agent-wheelhouse/self_correcting_langgraph_agent-0.1.0-*.whl >/dev/null

docker-build:
	docker build -t self-correcting-langgraph-agent:local .

check:
	scripts/run_checks.sh

clean:
	rm -rf build dist .pytest_cache .ruff_cache *.egg-info src/*.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type f -name '*.py[co]' -delete
