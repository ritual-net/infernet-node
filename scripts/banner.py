import pyfiglet
from rich import print


def _wrap_color(color: str, art: str):
    return f"[{color}]{art}[/{color}]"


if __name__ == '__main__':
    art = pyfiglet.figlet_format("RITUAL", font="o8")
    print(
        f"\n{_wrap_color('#40ffaf', art)}\n"
        f"Status: {_wrap_color('green', 'SUCCESS')} Running containers: {[]}"
    )

