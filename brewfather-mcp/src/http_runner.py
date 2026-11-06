"""HTTP/SSE runner for the Brewfather MCP server.

The server holds your Brewfather API key, so this runner binds to loopback by default and
requires a bearer token (BREWFATHER_MCP_HTTP_TOKEN) on every request.
"""

import hmac
import logging
import os

import click
import uvicorn
from mcp.server.transport_security import TransportSecuritySettings

from brewfather_mcp.server import mcp

logger = logging.getLogger(__name__)

TOKEN_ENV_VAR = "BREWFATHER_MCP_HTTP_TOKEN"
MIN_TOKEN_LENGTH = 24
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class BearerAuthMiddleware:
    """Pure ASGI middleware (keeps SSE streaming intact) that checks the Authorization header."""

    def __init__(self, app, token: str) -> None:
        self.app = app
        self._token = token.encode()

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http":
            header = dict(scope["headers"]).get(b"authorization", b"")
            scheme, _, supplied = header.partition(b" ")
            if scheme.lower() != b"bearer" or not hmac.compare_digest(supplied.strip(), self._token):
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [
                            (b"content-type", b"text/plain"),
                            (b"www-authenticate", b"Bearer"),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": b"Unauthorized"})
                return
        await self.app(scope, receive, send)


def build_app(host: str, allowed_hosts: tuple[str, ...] = ()):
    """Build the SSE app with bearer auth and DNS-rebinding protection."""
    token = os.getenv(TOKEN_ENV_VAR, "")
    if len(token) < MIN_TOKEN_LENGTH:
        raise click.UsageError(
            f"Set {TOKEN_ENV_VAR} to a random secret of at least {MIN_TOKEN_LENGTH} characters."
        )

    if host in LOOPBACK_HOSTS:
        hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*", *allowed_hosts]
    elif allowed_hosts:
        hosts = list(allowed_hosts)
    else:
        raise click.UsageError("Binding to a non-loopback host requires at least one --allowed-host.")

    mcp.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=[],  # browsers send Origin; MCP clients do not
    )
    app = mcp.sse_app()
    app.add_middleware(BearerAuthMiddleware, token=token)
    return app


@click.command()
@click.option("--host", default="127.0.0.1", help="Host to bind to (loopback by default)")
@click.option("--port", default=8000, help="Port to listen on")
@click.option("--log-level", default="INFO", help="Logging level")
@click.option(
    "--allowed-host",
    "allowed_hosts",
    multiple=True,
    help="Host header value to accept, e.g. 'mcp.example.com:*'. Required when not binding to loopback.",
)
def main(host: str, port: int, log_level: str, allowed_hosts: tuple[str, ...]) -> None:
    """Run the Brewfather MCP server over HTTP/SSE."""

    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    app = build_app(host, allowed_hosts)
    if host not in LOOPBACK_HOSTS:
        logger.warning("Serving plain HTTP on a non-loopback host; put TLS in front of it.")

    logger.info(f"Starting Brewfather MCP HTTP server on {host}:{port}")
    try:
        uvicorn.run(app, host=host, port=port, log_level=log_level.lower())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")


def run_http_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    log_level: str = "INFO",
    allowed_hosts: tuple[str, ...] = (),
) -> None:
    """Programmatic way to run the HTTP server."""
    main.callback(host, port, log_level, allowed_hosts)


if __name__ == "__main__":
    main()
