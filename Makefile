SHELL := /bin/bash
AGENT_DIR := services/rolecall-agent
WEB_DIR := apps/web
TF_DIR := infra/terraform
RUNTIME_SCRIPT := scripts/dev-runtime.sh
ENVIRONMENT_SCRIPT := scripts/full-environment.sh

.PHONY: install dev-api dev-web test test-python test-web test-e2e eval-validate lint build terraform-init terraform-validate terraform-plan runtime-status runtime-down runtime-up environment-status environment-destroy environment-create

install:
	cd $(AGENT_DIR) && uv sync --all-extras --dev
	cd $(WEB_DIR) && npm install

dev-api:
	cd $(AGENT_DIR) && uv run uvicorn app.fast_api_app:app --reload --host 0.0.0.0 --port 8000

dev-web:
	cd $(WEB_DIR) && npm run dev

test: test-python test-web

test-python:
	cd $(AGENT_DIR) && uv run pytest tests/unit tests/integration

test-web:
	cd $(WEB_DIR) && npm run test -- --run

test-e2e:
	cd $(WEB_DIR) && npm run test:e2e

eval-validate:
	cd $(AGENT_DIR) && uv run python tests/eval/validate_eval.py

lint:
	cd $(AGENT_DIR) && uv run ruff check . && uv run ruff format --check .
	cd $(WEB_DIR) && npm run lint && npm run typecheck

build:
	cd $(WEB_DIR) && npm run build
	cd $(AGENT_DIR) && uv build

terraform-init:
	terraform -chdir=$(TF_DIR) init -backend=false

terraform-validate: terraform-init
	terraform -chdir=$(TF_DIR) validate

terraform-plan:
	terraform -chdir=$(TF_DIR) plan -var-file=vars/dev.tfvars -out=rolecall-dev.tfplan

runtime-status:
	./$(RUNTIME_SCRIPT) status

runtime-down:
	./$(RUNTIME_SCRIPT) down

runtime-up:
	./$(RUNTIME_SCRIPT) up

environment-status:
	./$(ENVIRONMENT_SCRIPT) status

environment-destroy:
	./$(ENVIRONMENT_SCRIPT) destroy

environment-create:
	./$(ENVIRONMENT_SCRIPT) create
