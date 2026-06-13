"""Connect to the Voicenotes hosted MCP server via browser OAuth and list its tools."""

from __future__ import annotations

import asyncio
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from mcp.client.auth import OAuthClientProvider
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

SERVER_URL = "https://api.voicenotes.com/mcp"
CALLBACK_HOST = "localhost"
CALLBACK_PORT = 3000
CALLBACK_PATH = "/callback"
REDIRECT_URI = f"http://{CALLBACK_HOST}:{CALLBACK_PORT}{CALLBACK_PATH}"


class InMemoryTokenStorage:
    """Re-auth on every run; tokens live only for the process lifetime."""

    def __init__(self) -> None:
        self._tokens: OAuthToken | None = None
        self._client_info: OAuthClientInformationFull | None = None

    async def get_tokens(self) -> OAuthToken | None:
        return self._tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self._tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return self._client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self._client_info = client_info


async def redirect_handler(authorization_url: str) -> None:
    print(f"\nOpening browser for authorization:\n  {authorization_url}\n")
    webbrowser.open(authorization_url)


async def callback_handler() -> tuple[str, str | None]:
    """Run a one-shot localhost server, capture ?code=&state=, return them."""
    captured: dict[str, str | None] = {}
    done = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path != CALLBACK_PATH:
                self.send_response(404)
                self.end_headers()
                return
            params = parse_qs(parsed.query)
            code = params.get("code", [None])[0]
            state = params.get("state", [None])[0]
            error = params.get("error", [None])[0]

            if error or not code:
                self.send_response(400)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(f"OAuth error: {error or 'missing code'}".encode())
                captured["error"] = error or "missing code"
                done.set()
                return

            captured["code"] = code
            captured["state"] = state
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<!doctype html><h1>Authorization complete.</h1>"
                b"<p>You can close this tab and return to the terminal.</p>"
            )
            done.set()

        def log_message(self, *_args, **_kwargs) -> None:
            return

    server = HTTPServer((CALLBACK_HOST, CALLBACK_PORT), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        await asyncio.to_thread(done.wait)
    finally:
        server.shutdown()
        server.server_close()

    if "error" in captured:
        raise RuntimeError(f"OAuth callback failed: {captured['error']}")
    return captured["code"], captured.get("state")


async def main() -> None:
    metadata = OAuthClientMetadata(
        client_name="bootcamp-connect",
        redirect_uris=[REDIRECT_URI],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="none",
    )

    auth = OAuthClientProvider(
        server_url=SERVER_URL,
        client_metadata=metadata,
        storage=InMemoryTokenStorage(),
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
    )

    async with streamablehttp_client(SERVER_URL, auth=auth) as (read, write, _get_session_id):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()

            print(f"Connected to {SERVER_URL}")
            print(f"{len(result.tools)} tool(s) available:\n")
            for tool in result.tools:
                print(f"- {tool.name}")
                if tool.description:
                    print(f"  description: {tool.description.strip().splitlines()[0]}")
                print(f"  input_schema: {tool.inputSchema}")
                print()


if __name__ == "__main__":
    asyncio.run(main())
