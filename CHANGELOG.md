# Changelog

All notable changes to this project will be documented in this file.

- ##### The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
- ##### This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.4.0] - XXXX-XX-XX

### Added

- New `resources/` endpoint used to advertize supported services' hardware and software capabilities.
- Option for service containers to be ran on remote machines.

### Fixed

- Bug with empty input transaction simulations

## [1.3.1] - 2024-10-02

### Fixed

- Bug with `chain_id` being undefined when chain is disabled.

## [1.3.0] - 2024-09-20

### Added

- New `sync_period` field as `snapshot_sync` configuration parameter, to optionally set the period of polling the chain for new blocks/subscriptions.

### Changed

- Almost all container configurations (except `id` and `image`) are now reasonably defaulted (e.g. port auto-assignment), making it easier to configure a service and enabling the use of service recipes. Container configurations are validated at startup and errors are reported early.
- Added validation for entire `config.json` using pydantic, for sane defaulting and more meaningful error messages.

### Fixed

- Bug with batch syncing new subscriptions

## [1.2.0] - 2024-08-15

### Added

- New `starting_sub_id` field as `snapshot_sync` configuration parameter, to optionally start syncing from a certain subscription id instead of 0.

### Changed

- Subscriptions collection now is handled through smart contract reads instead of RPC calls, resulting in higher efficiency

### Fixed

- Reduced(almost eliminated) "429: Too many requests" RPC errors on Base Mainnet. Public RPCs can be used.
- Snapshot sync time is significantly less for chains with high number of subscriptions
- Fixed duplicate snapshot syncing bug

## [1.1.0] - 2024-07-30

### Added

- Node version check at node boot to notify user if node version is outdated.

### Changed

- Logger now uses RotatingFileHandler to limit disk space impact.
- `config.json` now accepts optional `log` object, with new configuration options `max_file_size` and `backup_count` for managing logging.

### Fixed

- Docker subnets are also considered "local IPs" for storing data in Redis via `POST api/status`.

## [1.0.0] - 2024-06-06

### Added
- Added files `Dockerfile-gpu` and `docker-compose-gpu.yaml` for building and deploying GPU-enabled node with access to all local GPUs.
- Better error-checking and handling for all infernet-related on-chain transaction errors.
- Forward fatal errors via metric sender at shutdown for better error diagnosing (only if forwarding stats is enabled.)
- New `destination` field to container inputs, to decouple job input source from output destination.
- OpenAPI spec for the REST server.
- Simulation of transactions before submitting them to the chain, to prevent submitting invalid transactions, resulting in wasted gas.
- Support for streaming offchain job responses, via the `POST /api/jobs/stream` endpoint.
- Support for CIDR ranges in container-level firewalls (`"allowed_ips"`).
- Support for volume mounts to managed containers.
- Support for streaming offchain job responses, via the `/api/jobs/stream` endpoint.
- New flag `"allowed_sim_errors"` in the `config.json` file to specify which error messages are allowed to be ignored by the node when simulating transactions.
- New flag `"payment_address"` in the `config.json` file to specify the public address of the node's escrow wallet. This is an instance of Infernet's `Wallet` contract.
- New flag `"accepted_payments"` in the `config.json`'s `"containers"` subsection to specify which tokens the container accepts as payment for jobs.
- New flag `"generates_proofs"` in the `config.json`'s `"containers"` subsection to specify whether the container generates proofs, defaults to `false`.
- New flag `"requires_proof"` in the input to the containers. Containers can check that flag to determine if they need to provide a proof, or error if they don't support proofs.
- New flag `"registry_address"` in the `config.json` file to specify the public address of Infernet's `Registry` contract. This contract is used to retrieve the addresses
  of the rest of the Infernet contracts. Therefore, the `"coordinator_address"` is now removed.
- New optional flag `"rate_limit"` in the `config.json`'s `"server"` configuration to allow rate limiting of incoming requests to the REST server.

### Changed
- Limit restarts within time window in `docker-compose.yaml`.
- Consolidated `GET /chain/enabled` and `GET /chain/address` endpoints into `GET /info`.
- Refactored node entrypoint (`main.py`) into a class.
- Increased metric sender intervals to combat outbound data rate limits.
  - `NODE_INTERVAL` for node metrics is now `3600` seconds.
  - `LIVE_INTERVAL` for live metrics is now `60` seconds.
- Moved `snapshot_sync` under the `chain` section of `config.json`.
- Snapshot syncing retries now include exponential backoff when syncing chain state.
- Job and container counts are now reported separately via metric sender. The REST port is also reported.
- `chain/processor.py` & `chain/listener.py` are extensively refactored to remove the dependency on on-chain events. `SubscriptionCreated` is now caught by repeatedly
  checking the latest `sub_id` & syncing all subscriptions since the last sync. `SubscriptionCancelled` is now caught by checking if `activeAt` is set to `max uint32`.
  This was an optimization done in the `infernet-sdk 1.0.0` contracts. `SubscriptionFulfilled` is now checked instead by reading the `redundancyCount` from the coordinator contract.
- Guardian no longer checks whether container isn't supported, since that check is already being done at the `ContainerLookup`
  level. If a subscription's `containers` field is not empty, it means that it must require a subset of the containers that this
  node supports.
- Since node registration feature has been removed in `1.0.0`, `register_node` & `activate_node` scripts have been removed from
  the `scripts` directory. The `Wallet` class also has the `register_node` & `activate_node` methods removed.
- Removed the `"coordinator_address"` flag from the `config.json` file. The address of the coordinator contract is now retrieved from the registry contract.

### Fixed
- Orchestrator now works in dev mode (outside of docker), previously `host.docker.internal` was hardcoded.
- Surface dacite errors when parsing REST interface inputs for better UX.
- Don't return job IDs for Delegated Subscriptions (misleading, since results can only be fetched on-chain).
- Added pending job TTL (loose upper bound) to prevent jobs from being in a pending state indefinitely (due crashes and / or incorrect use of the /status endpoint)
- Fixed a bug where the node could not send multiple transactions in a single block.

### Security
- Bumped `aiohttp` version to `3.9.4`.
- Only `localhost` allowed to make calls to `PUT /api/status`.

## [0.2.0] - 2024-03-21

### Added
- Option for containers to be managed separately from the node (via `manage_containers` option in `config.json`)
- Option to specify alternate `config.json` file name / path via environment variable `INFERNET_CONFIG_PATH`.
- Batch-syncing support for snapshot-sync, along with batch-sync configuration in the `config.json` file.
- New endpoint `/api/status` for "independent" (i.e. non-conforming) containers to manually register status of jobs by ID with the node.

### Changed
- `NODE_INTERVAL` for forwarding node metrics is now `900` seconds.

### Fixed
- Sample config `rpc_ws` should be `rpc_url` in `config.sample.json`.
- Added working container example to `config.sample.json`.
- Bug in `processor.py` where state dictionaries could be mutated while being iterated over.

### Security
- Bumped `aiohttp` version to `3.9.2`.
- Compose file no longer exposes Fluentbit and Redis ports to the host.

## [0.1.0] - 2024-01-18

### Added
- Initial release of Infernet Node.
