"""Command-line entry point: ``python -m lazis <command>``."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from lazis import __version__


def _cmd_serve(args: argparse.Namespace) -> int:
    from lazis.app.server import ServeOptions, serve

    if not args.stdin_secrets:
        sys.stderr.write("lazis-core: refusing to start without --stdin-secrets\n")
        return 2
    return serve(
        ServeOptions(
            environment=args.environment,
            data_dir=args.data_dir,
            log_dir=args.log_dir,
            config_path=args.config,
            secrets_timeout=args.secrets_timeout,
            require_os_sandbox=args.require_os_sandbox,
        )
    )


def _cmd_openapi(_args: argparse.Namespace) -> int:
    from lazis.api.app_factory import ApiContext, create_app
    from lazis.config import Settings

    app = create_app(ApiContext(settings=Settings(), storage=None, token_matches=lambda _t: False))
    sys.stdout.write(json.dumps(app.openapi(), indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    return 0


def _cmd_check_driver(_args: argparse.Namespace) -> int:
    from lazis.errors import LazisError
    from lazis.storage.driver import verify_driver

    try:
        cipher, sqlite = verify_driver()
    except LazisError as exc:
        sys.stderr.write(f"SQLCipher NOT available ({exc.code})\n")
        return 1
    sys.stdout.write(f"SQLCipher {cipher} (SQLite {sqlite}) OK\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lazis-core", description="LAZIS local backend")
    parser.add_argument("--version", action="version", version=f"lazis-core {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the managed backend (started by the desktop app)")
    serve.add_argument(
        "--stdin-secrets",
        action="store_true",
        help="read the session token and database key from stdin (required)",
    )
    serve.add_argument("--environment", choices=["development", "production", "test"])
    serve.add_argument("--data-dir", type=Path)
    serve.add_argument("--log-dir", type=Path)
    serve.add_argument("--config", type=Path, help="user config TOML (optional)")
    serve.add_argument("--secrets-timeout", type=float)
    serve.add_argument(
        "--require-os-sandbox",
        action="store_true",
        help="refuse to start unless the OS network sandbox is in effect (set by the shell)",
    )
    serve.set_defaults(func=_cmd_serve)

    sub.add_parser("openapi", help="print the OpenAPI schema").set_defaults(func=_cmd_openapi)
    sub.add_parser("check-driver", help="verify that SQLCipher is active").set_defaults(
        func=_cmd_check_driver
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))
