__version__ = "1.1.0"

from typing import Any

import requests

from utils import log
from utils.logging import log_ascii_status


def check_node_is_up_to_date() -> None:
    """Check if the node version is up to date with the latest release on GitHub"""
    try:
        # Fetch latest version file from GitHub
        url = "https://raw.githubusercontent.com/ritual-net/infernet-node/main/src/version.py"
        response = requests.get(url)
        if response.status_code != 200:
            log.warning(f"Failed to fetch latest node version ({response.text})")
            return

        namespace: dict[str, Any] = {}
        exec(response.text, namespace)
        if version := namespace.get("__version__"):
            if version != __version__:
                log_ascii_status(
                    f"Your node version (v{__version__}) does not match with latest "
                    f"release (v{version}). Consider updating your node.",
                    "warning",
                )
        else:
            log.warning("Latest version not found")
    except Exception as e:
        log.warning(e)
