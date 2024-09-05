from __future__ import annotations

import json
from typing import Any, List, Optional

import structlog
from pydantic import BaseModel, ValidationError, model_validator

log = structlog.get_logger(__name__)


class ConfigRateLimit(BaseModel):
    """Expected config[server][rate_limit] format"""

    num_requests: int = 60
    period: int = 60


class ConfigServer(BaseModel):
    """Expected config[server] format"""

    port: int = 4000
    rate_limit: ConfigRateLimit = ConfigRateLimit()


class ConfigWallet(BaseModel):
    """Expected config[chain][wallet] format"""

    max_gas_limit: int = 5000000
    private_key: Optional[str] = None
    payment_address: Optional[str] = None
    allowed_sim_errors: List[str] = []


class ConfigSnapshotSync(BaseModel):
    """Expected config[snapshot_sync] format"""

    sleep: float = 1.0
    batch_size: int = 500
    starting_sub_id: int = 0
    sync_period: float = 0.5


class ConfigChain(BaseModel):
    """Expected config[chain] format"""

    enabled: bool = False
    rpc_url: Optional[str] = None
    trail_head_blocks: int = 1
    registry_address: Optional[str] = None
    wallet: Optional[ConfigWallet] = None
    snapshot_sync: ConfigSnapshotSync = ConfigSnapshotSync()

    @model_validator(mode="after")
    def check_fields_when_enabled(self: ConfigChain) -> ConfigChain:
        # If `enabled` is True, check that certain fields are not None or empty
        enabled = self.enabled

        if enabled:
            if not self.rpc_url:
                raise ValueError("rpc_url must be defined when chain is enabled")
            if not self.registry_address:
                raise ValueError(
                    "registry_address must be defined when chain is enabled"
                )
            if not self.wallet:
                raise ValueError("wallet must be defined when chain is enabled")
            if not self.wallet.private_key:
                raise ValueError("private_key must be defined when chain is enabled")
        return self


class ConfigDocker(BaseModel):
    """Expected config[docker] format"""

    username: str
    password: str


class InfernetContainer(BaseModel):
    """Expected config[containers] format"""

    id: str
    image: str

    port: int = -1
    external: bool = True
    gpu: bool = False
    accepted_payments: dict[str, int] = {}
    allowed_ips: List[str] = []
    allowed_addresses: List[str] = []
    allowed_delegate_addresses: List[str] = []
    description: str = ""
    command: str = ""
    env: dict[str, Any] = {}
    generates_proofs: bool = False
    volumes: List[str] = []


class ConfigRedis(BaseModel):
    """Expected config[redis] format"""

    host: str = "redis"
    port: int = 6379


class ConfigLog(BaseModel):
    """Expected config[log] format"""

    path: str = "infernet_node.log"
    max_file_size: int = 2**30  # 1GB
    backup_count: int = 2


class Config(BaseModel):
    """Expected config format"""

    containers: List[InfernetContainer] = []
    chain: ConfigChain = ConfigChain()
    docker: Optional[ConfigDocker] = None
    forward_stats: bool = True
    log: ConfigLog = ConfigLog()
    manage_containers: bool = True
    redis: ConfigRedis = ConfigRedis()
    server: ConfigServer = ConfigServer()
    startup_wait: float = 5.0


def load_validated_config(path: str = "config.json") -> Optional[Config]:
    """Loads and validates configuration file. Throws if config can't be validated

    Args:
        path (str, optional): Path to config file. Defaults to "config.json".

    Returns:
        Optional[Config]: parsed and validated config
    """
    with open(path) as config_file:
        config_data = json.load(config_file)

        try:
            return Config(**config_data)
        except ValidationError as e:
            log.error(f"Invalid input data: {e}")
            return None
