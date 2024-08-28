# Use bash as shell
SHELL := /bin/bash

# Get the current git commit hash
GIT_COMMIT_HASH := $(shell git rev-parse --short HEAD)

# Set the tag to include commit hash
tag ?= $(GIT_COMMIT_HASH)

image_id = ritualnetwork/infernet-node-internal:$(tag)

###########
### DEV ###
###########

# Phony targets
.PHONY: install run deps

# Default: install deps
all: install

# Install dependencies
install:
	@uv venv && \
	source .venv/bin/activate && \
	uv pip install -r requirements.lock

# Update dependencies & generate new lockfile
update-lockfile:
	@uv venv && \
	source .venv/bin/activate && \
	uv pip install -r requirements.txt && \
	uv pip freeze > requirements.lock

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

# Run from source
run:
	INFERNET_CONFIG_PATH=./deploy/config.json python3.11 src/main.py

###########
# PUBLISH #
###########

build:
	docker build -t $(image_id) .

build-gpu:
	docker build -t $(image_id)-gpu -f Dockerfile-gpu .

publish:
	docker image push $(image_id)

# You may need to set up a docker builder, to do so run:
# docker buildx create --name mybuilder --bootstrap --use
# refer to https://docs.docker.com/build/building/multi-platform/#building-multi-platform-images for more info
build-multiplatform:
	docker buildx build --platform linux/amd64,linux/arm64 -t $(image_id) --push .
	docker buildx build --platform linux/amd64,linux/arm64 -t $(image_id)-gpu -f Dockerfile-gpu --push .
