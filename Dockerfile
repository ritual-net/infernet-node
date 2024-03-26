# syntax=docker/dockerfile:1

# Comments are provided throughout this file to help you get started.
# If you need more help, visit the Dockerfile reference guide at
# https://docs.docker.com/engine/reference/builder/

ARG PYTHON_VERSION=3.11
FROM python:${PYTHON_VERSION}-slim as base

# Prevents Python from writing pyc files.
ENV PYTHONDONTWRITEBYTECODE=1

# Keeps Python from buffering stdout and stderr to avoid situations where
# the application crashes without emitting any logs due to buffering.
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Create a non-privileged user that the frenrug will run under.
# See https://docs.docker.com/develop/develop-images/dockerfile_best-practices/#user
ARG UID=10001
RUN adduser \
    --disabled-password \
    --gecos "" \
    --home "/nonexistent" \
    --shell "/sbin/nologin" \
    --no-create-home \
    --uid "${UID}" \
    appuser

RUN apt-get update
RUN apt-get install -y curl

# Install UV
ADD --chmod=755 https://astral.sh/uv/install.sh /install.sh
RUN /install.sh && rm /install.sh

# Download dependencies as a separate step to take advantage of Docker's caching.
# Leverage a cache mount to /root/.cache/uv to speed up subsequent builds.
# Leverage a bind mount to requirements to avoid having to copy them into
# into this layer.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=requirements.txt,target=requirements.txt \
    /root/.cargo/bin/uv pip install --system -r requirements.txt

# Install some executables
RUN apt-get update \
    && apt-get install -y curl procps sysstat ifstat \
    && rm -rf /var/lib/apt/lists/*

# Copy the source code into the container.
COPY src/ src/
COPY entrypoint.sh .
COPY version.txt .

# Run the application.
ENTRYPOINT ["/app/entrypoint.sh"]
