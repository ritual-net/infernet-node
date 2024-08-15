from json import load as json_load
from typing import Any, NamedTuple, Optional, TypedDict, cast


class ConfigRateLimit(TypedDict):
    """Expected config[server][rate_limit] format"""

    num_requests: Optional[int]
    period: Optional[int]


class ConfigServer(TypedDict):
    """Expected config[server] format"""

    port: int
    rate_limit: Optional[ConfigRateLimit]


class ConfigWallet(TypedDict):
    """Expected config[chain][wallet] format"""

    max_gas_limit: int
    private_key: str
    payment_address: Optional[str]
    allowed_sim_errors: Optional[list[str]]


class ConfigSnapshotSync(TypedDict):
    """Expected config[snapshot_sync] format"""

    sleep: float
    batch_size: int
    starting_sub_id: int


class ConfigChain(TypedDict):
    """Expected config[chain] format"""

    enabled: bool
    rpc_url: str
    trail_head_blocks: int
    registry_address: str
    wallet: ConfigWallet
    snapshot_sync: Optional[ConfigSnapshotSync]


class ConfigDocker(TypedDict):
    """Expected config[docker] format"""

    username: str
    password: str


class ConfigContainer(TypedDict):
    """Expected config[containers] format"""

    id: str
    image: str
    description: Optional[str]
    command: str
    env: dict[str, Any]
    port: int
    allowed_ips: list[str]
    allowed_addresses: list[str]
    allowed_delegate_addresses: list[str]
    external: bool
    gpu: Optional[bool]
    volumes: Optional[list[str]]
    accepted_payments: Optional[dict[str, int]]
    generates_proofs: Optional[bool]


class ConfigRedis(TypedDict):
    """Expected config[redis] format"""

    host: str
    port: int


class ConfigLog(TypedDict):
    """Expected config[log] format"""

    path: Optional[str]
    max_file_size: Optional[int]
    backup_count: Optional[int]


class ConfigDict(TypedDict):
    """Expected config format"""

    log: Optional[ConfigLog]
    manage_containers: Optional[bool]
    server: ConfigServer
    chain: ConfigChain
    docker: Optional[ConfigDocker]
    redis: ConfigRedis
    containers: list[ConfigContainer]
    forward_stats: bool
    startup_wait: Optional[float]


class ValidationItem(NamedTuple):
    """Validation parser item (dict key path, expected type of value, required)"""

    key_path: str
    expected_type: type
    optional: bool = False


# Config dict path => expected type
VALIDATION_CONFIG: list[ValidationItem] = [
    ValidationItem("server.port", int),
    ValidationItem("chain.enabled", bool),
    ValidationItem("chain.rpc_url", str),
    ValidationItem("chain.trail_head_blocks", int),
    ValidationItem("chain.registry_address", str),
    ValidationItem("chain.wallet.max_gas_limit", int),
    ValidationItem("chain.wallet.private_key", str),
]


def validate(
    config: dict[Any, Any], path: list[str], expected_type: type, optional: bool
) -> None:
    """Validates individual ValidationItem

    Args:
        config (dict[Any, Any]): recursed config dict
        path (list[str]): recursed dot-seperated dict path
        expected_type (type): expected type of root value
        optional (bool): is path optional

    Raises:
        TypeError: Thrown if root value has type mismatch to expected type
        KeyError: Thrown if root value is required but missing in config
    """
    if len(path) == 0:
        # At root value, validate type before returning
        if type(config) is not expected_type:
            raise TypeError
        return

    # Collect next key from path
    next_key: str = path.pop(0)

    # If key exists in config, recurse one-level deeper
    if next_key in config:
        validate(config[next_key], path, expected_type, optional)
    else:
        # If key does not exist in config, check if key is optional
        if optional:
            # If key is optional, populate key and continue down-level population
            config[next_key] = None
            validate(config[next_key], path, expected_type, optional)
        else:
            # Else, raise KeyError
            raise KeyError


def validate_config(config: dict[Any, Any]) -> None:
    """In-place validates passed config for optionality and argument type

    Args:
        config (dict[Any, Any]): raw loaded JSON config

    Raises:
        Exception: Thrown if invalid config param (missing required or incorrect type)
    """
    for item in VALIDATION_CONFIG:
        # Split at "." to generate nested key path
        path: list[str] = item.key_path.split(".")

        try:
            # Recursively validate path
            validate(config, path, item.expected_type, item.optional)
        except KeyError:
            raise Exception(f"Missing config param: {item.key_path}")
        except TypeError:
            raise Exception(f"Incorrect config type: {item.key_path}")


def load_validated_config(path: str = "config.json") -> ConfigDict:
    """Loads and validates configuration file. Throws if config can't be validated

    Args:
        path (str, optional): Path to config file. Defaults to "config.json".

    Returns:
        ConfigDict: parsed config
    """
    config: dict[Any, Any] = json_load(open(path))
    validate_config(config)
    return cast(ConfigDict, config)
