import logging
import logging.handlers
from typing import Literal

import pyfiglet  # type: ignore
import structlog
from rich import print
from structlog.typing import Processor

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


def setup_logging(log_path: str = "/tmp/infernet_node.log") -> None:
    """Setup logging configuration

    Args:
        log_path (str, optional): Path for log file. Defaults to
            "/app/infernet_node.log".
    """

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
    max_file_size = 100 * 1024 * 1024  # 100 MB
    backup_count = 10  # Keep 10 backup files, ~1 GB total
    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=max_file_size, backupCount=backup_count
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
    message: str, success: Literal["success", "failure", "warning"]
) -> None:
    """Display ASCII art status message with colorized text

    Args:
        message (str): Message to display
        success (Literal["success", "failure", "warning"]): Status of message
    """

    def _colorize(text: str, color: str) -> str:
        return f"[{color}]{text}[/{color}]"

    match success:
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
