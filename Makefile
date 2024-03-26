# Use bash as shell
SHELL := /bin/bash

# Phony targets
.PHONY: install run deps

# Default: install deps
all: install

# Install dependencies
install:
	@pip install -r requirements.txt

# Save dependencies
deps:
	@pip-chill > requirements.txt

# Lint code
lint:
	@echo "Linting src/"
	@ruff check src --fix
	@echo "Linting scripts/"
	@ruff check scripts --fix

# Type check code
types:
	@mypy src/main.py --check-untyped-defs

# Format code
format:
	@echo "Formatting src/"
	@ruff format src
	@echo "Formatting scripts/"
	@ruff format scripts

# Run process
run:
	@python3.11 src/main.py

# Script: register node
register-node:
	@PYTHONPATH=$$PYTHONPATH:src python3.11 scripts/register_node.py

# Script: activate node
activate-node:
	@PYTHONPATH=$$PYTHONPATH:src python3.11 scripts/activate_node.py

tag ?= latest

build:
	docker build -t ritualnetwork/infernet-node:$(tag) .

# You may need to set up a docker builder, to do so run:
# docker buildx create --name mybuilder --bootstrap --use
# refer to https://docs.docker.com/build/building/multi-platform/#building-multi-platform-images for more info
build-multiplatform:
	docker buildx build --platform linux/amd64,linux/arm64 -t ritualnetwork/infernet-node:$(tag) --push .
