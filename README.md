[![pre-commit](https://github.com/ritual-net/infernet-node-internal/actions/workflows/workflow.yaml/badge.svg)](https://github.com/ritual-net/infernet-node-internal/actions/workflows/workflow.yaml)

# Infernet Node

The Infernet Node is the off-chain counterpart to the [Infernet SDK](https://github.com/ritual-net/infernet-sdk) from [Ritual](https://ritual.net), responsible for servicing compute workloads and delivering responses to on-chain smart contracts.

Developers can flexibily configure an Infernet Node for both on- and off-chain compute consumption, with extensible and robust parameterization at a per-container level.

> [!IMPORTANT]
> Infernet Node architecture, quick-start guides, and in-depth documentation can be found on the [Ritual documentation website](https://docs.ritual.net/infernet/node/introduction)

> [!WARNING]
> This software is being provided as is. No guarantee, representation or warranty is being made, express or implied, as to the safety or correctness of the software.

## Node configuration

At its core, the Infernet Node operates according to a set of runtime configurations. Some of these configurations have sane defaults and do not need modification. See [config.sample.json](./config.sample.json) for an example, or copy to begin modifying:

```bash
# Copy and modify sample config
cp config.sample.json config.json
vim config.json
```

### Required configuration parameters

- **log_path** (`string`). The local file path for logging.
- **startup_wait** (`float`, Optional). The number of seconds to wait for containers to start up before starting the node.
- **chain** (`object`). Chain configurations.
  - **enabled** (`boolean`). Whether chain is enabled on this node.
  - **trail_head_blocks** (`integer`). _if enabled_: how many blocks to stay behind head when syncing. Set to `0` to ignore.
  - **rpc_url** (`string`). _if enabled_: the HTTP(s) JSON-RPC url.
  - **registry_address** (`string`). _if enabled_: the `Registry` contract address.
  - **wallet** (`object`). _if enabled_:
    - **max_gas_limit** (`integer`). Maximum gas limit per node transaction
    - **private_key** (`string`). Node wallet private key
    - **payment_address** (`string`). Public address of the node's escrow wallet.
      This is an instance of Infernet's `Wallet` contract.
    - **allowed_sim_errors** (`array[string]`). Allowed error messages to ignore when simulating transactions. Checks for inclusion in error message. Case-insensitive. i.e. `["out of gas"]` matches `"Contract reverted: Out of gas"`.
  - **snapshot_sync** (`object`, Optional). Snapshot sync configurations.
    - **sleep** (`float`, Optional).  Number of seconds to sleep between snapshot syncs. Defaults to `1.0`.
    - **batch_size** (`int`, Optional). Number of subscriptions to sync in each batch. Defaults to `200`.
- **docker** (`object`, optional). Docker credentials to pull private containers with
  - **username** (`string`). The Dockerhub username.
  - **password** (`string`). The Dockerhub [Personal Access Token](https://docs.docker.com/security/for-developers/access-tokens/) (PAT).
- **containers** (`array[container_spec]`). Array of supported container specifications.
  - **container_spec** (`object`). Specification of supported container.
    - **id** (`string`). **Must be unique**. ID of supported service.
    - **image** (`string`). Dockerhub image to run container from. Must be local, public, or accessible with provided DockerHub credentials.
    - **command** (`string`). The command and flags to run the container with.
    - **env** (`object`). The environment variables to pass into the container.
    - **port** (`integer`). Local port to expose this container on.
    - **rate_limit** (`object`). REST server rate-limiting configurations.
      - **num_requests** (`integer`). Maximum number of requests per `period`.
      - **period** (`float`). Time period in seconds for `num_requests`.
    - **external** (`boolean`). Whether this container can be the first container in a [JobRequest](https://docs.ritual.net/infernet/node/api#jobrequest).
    - **description** (`string`, optional). Description of service provided by this container.
    - **allowed_ips** (`array[string]`). Container-level firewall. Only specified IPs and/or [CIDR blocks](https://www.ipaddressguide.com/cidr) allowed to request execution of this container.
      - _Leave empty for no restrictions_.
    - **allowed_addresses** (`array[string]`). Container-level firewall. Only specified addresses allowed to request execution of this container, with request originating from on-chain contract.
      - _Leave empty for no restrictions_.
    - **allowed_delegate_addresses** (`array[string]`). Container-level firewall. Only specified addresses allowed to request execution of this container, with request originating from on-chain contract but via off-chain delegate subscription (with this address corresponding to the delegate subscription `owner`).
      - _Leave empty for no restrictions_.
    - **gpu** (`boolean`). Whether this should be a GPU-enabled container. Host must also be GPU-enabled.
    - **volumes** (`array[string]`). The volume mounts for this container.

### Sane default configuration parameters

- **server** (`object`). Server configurations.
  - **port** (`integer`). Port to run server on. Defaults to `4000`.
- **redis** (`object`). Redis configurations.
  - **host** (`string`). Host to connect to. Defaults to `"redis"`.
  - **port** (`integer`). Port to connect to. Defaults to `6379`.
- **forward_stats** (`boolean`). Whether to send diagnostic system stats to Ritual. Defaults to `true`.
- **startup_wait** (`float`). Number of seconds to wait for containers to start up before starting the node.
  Defaults to `60`.

## Deploying the node

### Locally via Docker

```bash
# Set tag
tag="0.1.0"

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
tag="0.1.0"

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
tag="0.1.0"

# Build for local platform
make build

# Multi-platform build and push to repo
make build-multiplatform
```

## License

[BSD 3-clause Clear](./LICENSE)
