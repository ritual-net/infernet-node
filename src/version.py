__version__ = "1.2.0"


import re

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

        # extract the version from atop the file
        regex = r"__version__ = \"([0-9]+\.[0-9]+\.[0-9]+)\""
        matches = re.findall(regex, response.text)
        version = matches[0]

        if not version:
            log.warning("Latest version not found")
        elif version != __version__:
            log_ascii_status(
                f"Your node version (v{__version__}) does not match with latest "
                f"release (v{version}). Consider updating your node.",
                "warning",
            )
    except Exception as e:
        log.warning(e)
