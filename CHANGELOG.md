# Changelog

All notable changes to this project will be documented in this file.

- ##### The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
- ##### This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2024-03-01

### Added
- Option for containers to be managed separately from the node (via `manage_containers` option in `config.json`)
- Option to specify alternate `config.json` file name / path via environment variable `INFERNET_CONFIG_PATH`.
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
