[![pre-commit](https://github.com/ritual-net/infernet-node-internal/actions/workflows/workflow.yaml/badge.svg)](https://github.com/ritual-net/infernet-node-internal/actions/workflows/workflow.yaml)

# Infernet Node

The Infernet Node is the off-chain counterpart to the [Infernet SDK](https://github.com/ritual-net/infernet-sdk) from [Ritual](https://ritual.net), responsible for servicing compute workloads and delivering responses to on-chain smart contracts.

Developers can flexibily configure an Infernet Node for both on- and off-chain compute consumption, with extensible and robust parameterization at a per-container level.

> [!IMPORTANT]
> Infernet Node architecture, quick-start guides, and in-depth documentation can be found on the [Ritual documentation website](https://docs.ritual.net/infernet/node/introduction)

> [!WARNING]
> This software is being provided as is. No guarantee, representation or warranty is being made, express or implied, as to the safety or correctness of the software.

## Configuration

The Infernet Node operates according to a set of runtime configurations. Most of these configurations have sane defaults and do not need modification. See [config.sample.json](./config.sample.json) for an example configuration.

For a full list of available configurations, check out our [Node Configuration](https://docs.ritual.net/infernet/node/configuration/v1_3_0) docs.

## Deployment

### Locally via Docker

```bash
# Set tag
tag="1.3.0"

# Build image from source
docker build -t ritualnetwork/infernet-node:$tag .

# Configure node
cd deploy
cp ../config.sample.json config.json
# FILL IN config.json #

# Run node and dependencies
docker compose up -d
```

### Locally via Docker (GPU-enabled)

The GPU-enabled version of the image comes pre-installed with the [NVIDIA CUDA Toolkit](https://developer.nvidia.com/cuda-toolkit?ref=blog.kobus.me). Using this image on your GPU-enabled machine enables the node to interact with the attached accelerators for diagnostic and purposes, such as heartbeat checks and utilization reports.

```bash
# Set tag
tag="1.3.0"

# Build GPU-enabled image from source
docker build -f Dockerfile-gpu -t ritualnetwork/infernet-node:$tag-gpu .

# Configure node
cd deploy
cp ../config.sample.json config.json
# FILL IN config.json #

# Run node and dependencies
docker compose -f docker-compose-gpu.yaml  up -d
```

### Locally via source

```bash
# Create and source new python venv
python3.11 -m venv env
source ./env/bin/activate
pip install -r requirements.txt

# Install dependencies
make install

# Configure node
cp config.sample.json config.json
# FILL IN config.json #

# Run node
make run
```

### Remotely via AWS / GCP

Follow README instructions in the [infernet-deploy](https://github.com/ritual-net/infernet-deploy) repository.

## Publishing a Docker image

```bash
# Set tag
tag="1.3.0"

# Build for local platform
make build

# Multi-platform build and push to repo
make build-multiplatform
```

## License

[BSD 3-clause Clear](./LICENSE)
