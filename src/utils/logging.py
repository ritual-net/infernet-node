import logging
import logging.handlers
from typing import Literal, Optional

import pyfiglet  # type: ignore
import structlog
from rich import print
from structlog.typing import Processor

from utils.config import ConfigLog

# Re-export logger
log = structlog.get_logger()

# Structlog shared processors
SHARED_PROCESSORS: list[Processor] = [
    structlog.contextvars.merge_contextvars,  # Merge in global context
    structlog.stdlib.add_log_level,  # Add log level
    structlog.stdlib.add_logger_name,  # Add logging function
    structlog.dev.set_exc_info,  # Exception info handling
    structlog.processors.TimeStamper("%Y-%m-%d %H:%M:%S", utc=False),  # Timestamp
    structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
]

# Font for ASCII art, taken from http://www.figlet.org/examples.html
PIGLET_FONT = "o8"

DEFAULT_LOG_PATH = "infernet_node.log"
DEFAULT_MAX_FILE_SIZE = 2**30  # Default to 1GB log file size
DEFAULT_BACKUP_COUNT = 2  # Default to 2 log files to keep


def setup_logging(
    config: Optional[ConfigLog],
) -> None:
    """Setup logging configuration

    Args:
        config (Optional[ConfigLog]): Logging configuration options
    """

    path = config.get("path") if config else None
    max_file_size = config.get("max_file_size") if config else None
    backup_count = config.get("backup_count") if config else None

    # Configure structlog
    # Largely standard config: https://www.structlog.org/en/stable/configuration.html
    structlog.configure(
        processors=SHARED_PROCESSORS,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
    )

    # Setup raw python logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.NOTSET)

    # Setup log handlers
    console_handler = logging.StreamHandler()  # Stream to sys.stderr

    # Use RotatingFileHandler to limit log file size
    file_handler = logging.handlers.RotatingFileHandler(
        DEFAULT_LOG_PATH if path is None else path,
        maxBytes=DEFAULT_MAX_FILE_SIZE if max_file_size is None else max_file_size,
        backupCount=DEFAULT_BACKUP_COUNT if backup_count is None else backup_count,
    )

    # Setup log formatting
    console_handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            # Print to console, pad all events w/ min. 50 spaces, don't sort keys
            processor=structlog.dev.ConsoleRenderer(pad_event=50, sort_keys=False)
        )
    )
    console_handler.setLevel(logging.INFO)  # Console INFO+
    file_handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            # Format logs as JSON
            processor=structlog.processors.JSONRenderer()
        )
    )
    file_handler.setLevel(logging.DEBUG)  # Save to file DEBUG+

    # Add log handlers to raw python logger
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)


RITUAL_LABEL = pyfiglet.figlet_format("RITUAL", font=PIGLET_FONT)


def log_ascii_status(
    message: str, status: Literal["success", "failure", "warning"]
) -> None:
    """Display ASCII art status message with colorized text

    Args:
        message (str): Message to display
        status (Literal["success", "failure", "warning"]): Status of message
    """

    def _colorize(text: str, color: str) -> str:
        return f"[{color}]{text}[/{color}]"

    match status:
        case "success":
            print(
                f"\n{_colorize(RITUAL_LABEL, 'bold green')}\n"
                f"Status: {_colorize('SUCCESS', 'bold green')} " + message
            )
        case "failure":
            print(
                f"\n{_colorize(RITUAL_LABEL, 'bold red')}\n"
                f"Status: {_colorize('FAILURE', 'bold red')} " + message
            )
        case "warning":
            print(
                f"\n{_colorize(RITUAL_LABEL, 'bold yellow')}\n"
                f"Status: {_colorize('WARNING', 'bold yellow')} " + message
            )
