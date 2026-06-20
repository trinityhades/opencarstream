"""OpenCarStream server package."""

__all__ = ["main"]


def main() -> None:
    from .server_app import main as _main

    _main()
