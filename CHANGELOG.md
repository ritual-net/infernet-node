# Changelog

All notable changes to this project will be documented in this file.

- ##### The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
- ##### This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Forward fatal errors via metric sender at shutdown for better error diagnosing (only if forwarding stats is enabled.)
- Support for streaming offchain job responses, via the `/api/jobs/stream` endpoint.

### Changed
- Limit restarts within time window in `docker-compose.yaml`.
- Consolidated `/chain/enabled` and `/chain/address` endpoints into `/info`.
- Refactored node entrypoint (`main.py`) into a class.
- Increased metric sender intervals to combat outbound data rate limits.
  - `NODE_INTERVAL` for node metrics is now `3600` seconds.
  - `LIVE_INTERVAL` for live metrics is now `60` seconds.

### Fixed
- Orchestrator now works in dev mode (outside of docker), previously `host.docker.internal` was hardcoded.
- Surface dacite errors when parsing REST interface inputs for better UX.
- Don't return job IDs for Delegated Subscriptions (misleading, since results can only be fetched on-chain).
- Added pending job TTL (loose upper bound) to prevent jobs from being in a pending state indefinitely (due crashes and / or incorrect use of the /status endpoint)


## [0.2.0] - 2024-03-21

### Added
- Option for containers to be managed separately from the node (via `manage_containers` option in `config.json`)
- Option to specify alternate `config.json` file name / path via environment variable `INFERNET_CONFIG_PATH`.
- Batch-syncing support for snapshot-sync, along with batch-sync configuration in the `config.json` file.
- New endpoint `/api/status` for "independent" (i.e. non-conforming) containers to manually register status of jobs by ID with the node.
- Simulation of transactions before submitting them to the chain, to prevent submitting invalid transactions, resulting in wasted gas.
- Better error-checking and handling for all infernet-related on-chain transaction errors.

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
