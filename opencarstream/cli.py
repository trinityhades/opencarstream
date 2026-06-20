import argparse
import os
import sys
import webbrowser


def _set_env(name: str, value: object | None) -> None:
    if value is not None:
        os.environ[name] = str(value)


def main() -> None:
    parser = argparse.ArgumentParser(prog="opencarstream")
    subparsers = parser.add_subparsers(dest="command")

    serve = subparsers.add_parser("serve", help="Start the OpenCarStream server")
    serve.add_argument("--host", help="Host/interface to bind")
    serve.add_argument("--port", type=int, help="Port to listen on")
    serve.add_argument("--admin-password", help="Admin password; pass an empty value to disable auth")
    serve.add_argument("--local-media-dir", help="Directory containing local media")
    serve.add_argument("--iptv-lists-dir", help="Directory containing IPTV playlist files")
    serve.add_argument("--subscriptions-file", help="Path to subscriptions JSON")
    serve.add_argument("--config-dir", help="Directory for writable JSON config/cache files")
    serve.add_argument("--open", action="store_true", help="Open the dashboard in the default browser")

    argv = sys.argv[1:]
    if not argv:
        argv = ["serve", *argv]
    elif argv[0].startswith("-") and argv[0] not in ("-h", "--help"):
        argv = ["serve", *argv]
    args = parser.parse_args(argv)

    _set_env("HOST", args.host)
    _set_env("PORT", args.port)
    _set_env("ADMIN_PASSWORD", args.admin_password)
    _set_env("LOCAL_MEDIA_DIR", args.local_media_dir)
    _set_env("IPTV_LISTS_DIR", args.iptv_lists_dir)
    _set_env("SUBSCRIPTIONS_FILE", args.subscriptions_file)

    if args.config_dir:
        config_dir = os.path.abspath(args.config_dir)
        os.makedirs(config_dir, exist_ok=True)
        os.environ.setdefault("ACE_STREAMS_FILE", os.path.join(config_dir, "ace_streams.json"))
        os.environ.setdefault("FAVORITES_FILE", os.path.join(config_dir, "favorites.json"))
        os.environ.setdefault("PROGRESS_FILE", os.path.join(config_dir, "watch_progress.json"))
        os.environ.setdefault("HOME_FEED_CACHE_FILE", os.path.join(config_dir, "home_feed_cache.json"))
        os.environ.setdefault("SUBSCRIPTIONS_FILE", os.path.join(config_dir, "subscriptions.json"))

    if args.open:
        host = args.host or os.environ.get("HOST", "0.0.0.0")
        browser_host = "127.0.0.1" if host in ("", "0.0.0.0", "::") else host
        port = args.port or os.environ.get("PORT", "8080")
        webbrowser.open(f"http://{browser_host}:{port}/")

    from .server_app import main as serve_main

    serve_main()


if __name__ == "__main__":
    main()
