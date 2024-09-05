from __future__ import annotations

from utils.config import InfernetContainer
from utils.logging import log


def assign_ports(configs: list[InfernetContainer]) -> list[InfernetContainer]:
    """Assigns ports to container configurations.

    Args:
        configs (list[InfernetContainer]): The container configurations.

    Returns:
        list[InfernetContainer]: The container configurations with assigned ports.
    """
    log.info("Assigning ports to container configurations...")

    def auto_assign_port(ports: set[int]) -> int:
        """Finds an available port starting at 3999 and decrementing by 1."""
        port = 3999
        while port in ports:
            port -= 1
        return port

    requested_ports = {config.id: config.port for config in configs}
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

    for config in configs:
        config.port = assigned_ports[config.id]
    return configs
