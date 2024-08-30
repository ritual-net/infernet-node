from __future__ import annotations

import json
import sys
from typing import Any

from pydantic import BaseModel, ValidationError

from utils import log
from utils.config import ConfigContainer


class InfernetContainer(BaseModel):
    """Full Infernet Container configuration"""

    # Required
    id: str
    image: str

    # Can be defaulted
    port: int
    external: bool
    gpu: bool

    # Optional - default to empty
    accepted_payments: dict[str, int]
    allowed_ips: list[str]
    allowed_addresses: list[str]
    allowed_delegate_addresses: list[str]
    command: str
    description: str
    env: dict[str, Any]
    generates_proofs: bool
    volumes: list[str]


def assign_ports(configs: list[ConfigContainer]) -> dict[str, int]:
    """Assigns ports to container configurations.

    Args:
        configs (list[ConfigContainer]): The container configurations to assign ports to.

    Returns:
        dict[str, int]: The mapping of container IDs to ports.
    """
    log.info("Assigning ports to container configurations...")

    def auto_assign_port(ports: set[int]) -> int:
        """Finds an available port starting at 3999 and decrementing by 1."""
        port = 3999
        while port in ports:
            port -= 1
        return port

    requested_ports = {config["id"]: config.get("port") for config in configs}
    assigned_ports: dict[str, int] = {}

    for id, port in requested_ports.items():
        if port is not None:
            if port in assigned_ports.values():
                # Auto-assign port if requested port is already in use
                next_port = auto_assign_port(set(assigned_ports.values()))
                log.warning(
                    f"Port {port} is already in use. "
                    f"Auto-assigning port {next_port} for container '{id}'"
                )
                assigned_ports[id] = next_port
            else:
                assigned_ports[id] = port
        else:
            # Auto-assign port if not specified
            assigned_ports[id] = auto_assign_port(set(assigned_ports.values()))

    return assigned_ports


def validate_configurations(
    configs: list[ConfigContainer],
) -> list[InfernetContainer]:
    """Validates and sanitizes ConfigContainer objects.

    Default values are used where possible, and errors are raised for missing required
    fields.
        - `id` and `image` are required fields. `id` must be unique.
        - `port` is auto-assigned if not provided.
        - `external` defaults to True.
        - `gpu` defaults to False.
        - `accepted_payments`, `command`, `description`, `env`, `generates_proofs`,
            `volumes`, `allowed_ips`, `allowed_addresses`, and
            `allowed_delegate_addresses` default to empty.

    Args:
        configs (list[ConfigContainer]): The container configurations to generate.

    Returns:
        list[InfernetContainer]: The validated container configurations.

    """
    log.info("Validating container configurations...")

    containers = []
    ids = set()
    ports = assign_ports(configs)

    for config in configs:
        # Required fields
        id = config.get("id")
        image = config.get("image")
        if not id or not image:
            raise ValueError(
                "Fatal error: container config must contain non-empty 'id' and 'image'"
                " fields."
            )

        # Check for duplicate IDs
        if id in ids:
            raise ValueError(
                f"Container ID {id} is already in use. IDs must be unique."
            )
        ids.add(id)

        try:
            containers.append(
                InfernetContainer(
                    id=id,
                    image=image,
                    port=ports[id],
                    external=config.get("external", True),
                    gpu=config.get("gpu", False),
                    # Default to empty
                    accepted_payments=config.get("accepted_payments", dict()),
                    command=config.get("command", ""),
                    description=config.get("description", ""),
                    env=config.get("env", dict()),
                    generates_proofs=config.get("generates_proofs", False),
                    volumes=config.get("volumes", []),
                    # Default firewall values to allow all
                    allowed_ips=config.get("allowed_ips", []),
                    allowed_addresses=config.get("allowed_addresses", []),
                    allowed_delegate_addresses=config.get(
                        "allowed_delegate_addresses", []
                    ),
                )
            )
        except ValidationError as e:
            error = json.loads(e.json())
            log.error(
                f"Config validation error: field '{error[0]['loc'][0]}'. "
                f"{error[0]['msg']}"
            )
            sys.exit(1)

    return containers
