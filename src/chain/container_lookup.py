from __future__ import annotations

from itertools import permutations
from typing import List

import structlog
from eth_abi.abi import encode
from web3 import Web3

from shared.config import InfernetContainer


def get_all_comma_separated_permutations(containers: List[str]) -> List[str]:
    """
    Get all possible permutations of comma-separated container IDs. It performs this on
    the power set of the containers List, which includes all possible combinations of
    containers, including the empty set.

    Args:
        containers (List[str]): List of container IDs

    Returns:
        List[str]: All possible permutations of comma-separated container IDs

    """
    # Single elements
    single_elements = containers

    # All possible permutations with 2 or more elements
    permuted_elements = []
    for r in range(2, len(containers) + 1):
        permuted_elements.extend([",".join(p) for p in permutations(containers, r)])

    # Combine single elements and permuted elements
    all_elements = single_elements + permuted_elements

    return all_elements


log = structlog.get_logger(__name__)


class ContainerLookup:
    """
    ContainerLookup class. Since on-chain container IDs are keccak hashes of
    comma-separated container IDs, we need to build a lookup table to find out which
    containers are required for a given subscription.

    This class is instantiated at the beginning of the infernet-node's lifecycle and
    is used to decode container IDs from keccak hashes.

    """

    def __init__(self: ContainerLookup, configs: List[InfernetContainer]) -> None:
        """
        Initialize the container lookup table.

        Args:
            configs (List[InfernetContainer]): Container configurations
        """
        self._init_container_lookup(configs)

    def _init_container_lookup(
        self: ContainerLookup, configs: List[InfernetContainer]
    ) -> None:
        """
        Build a lookup table keccak hash of a container set -> container set

        Since the containers field of a subscription is a keccak hash of the
        comma-separated container IDs that it requires, we need to build a lookup
        table of all possible container sets on the node side to find out which
        containers are required for a given subscription.

        Args:
            configs (List[InfernetContainer]): Container configurations
        """
        all_permutations = get_all_comma_separated_permutations(
            [container.id for container in configs]
        )

        def _calculate_hash(perm: str) -> str:
            _hash = Web3.keccak(encode(["string"], [perm])).hex()
            # strip leading 0x
            return _hash

        self._container_lookup = {
            _calculate_hash(perm): perm.split(",") for perm in all_permutations
        }
        log.debug(f"Initialized container lookup: {self._container_lookup}")

    def get_containers(self: ContainerLookup, _hash: str) -> List[str]:
        """
        Get the container IDs from a keccak hash. Returns an empty List if the hash is
        not found.

        Args:
            _hash (str): Keccak hash of the container IDs

        Returns:
            List[str]: Container IDs
        """

        return self._container_lookup.get(_hash, [])
