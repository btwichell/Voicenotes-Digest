"""Agent loop: repeat tool calls until Claude returns a final answer."""

from __future__ import annotations

import asyncio
import json
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from anthropic import Anthropic
from dotenv import load_dotenv

from mcp.client.auth import OAuthClientProvider
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

from send_sms import send_sms

load_dotenv()
client = Anthropic()
MODEL = "claude-sonnet-4-5"

SERVER_URL = "https://api.voicenotes.com/mcp"
CALLBACK_HOST = "localhost"
CALLBACK_PORT = 3000
CALLBACK_PATH = "/callback"
REDIRECT_URI = f"http://{CALLBACK_HOST}:{CALLBACK_PORT}{CALLBACK_PATH}"
MAX_RETRIES = 3
RETRY_DELAY = 5
TOKEN_FILE = Path.home() / ".config" / "voicenotes_mcp" / "tokens.json"


class FileTokenStorage:
    def __init__(self, path: Path = TOKEN_FILE) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict = {}
        if self._path.exists():
            with open(self._path) as f:
                self._data = json.load(f)

    def _save(self) -> None:
        with open(self._path, "w") as f:
            json.dump(self._data, f)

    async def get_tokens(self) -> OAuthToken | None:
        if "tokens" not in self._data:
            return None
        return OAuthToken(**self._data["tokens"])

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self._data["tokens"] = tokens.model_dump(mode="json")
        self._save()

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        if "client_info" not in self._data:
            return None
        return OAuthClientInformationFull(**self._data["client_info"])

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self._data["client_info"] = client_info.model_dump(mode="json")
        self._save()


async def redirect_handler(authorization_url: str) -> None:
    print(f"\nOpening browser for authorization:\n  {authorization_url}\n")
    webbrowser.open(authorization_url)


async def callback_handler() -> tuple[str, str | None]:
    captured: dict[str, str | None] = {}
    done = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
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


async def call_tool_with_retry(session, name, input, retries=MAX_RETRIES):
    """Run a tool call, retrying on 429 up to MAX_RETRIES times."""
    for attempt in range(retries):
        try:
            return await session.call_tool(name, input)
        except Exception as e:
            if "429" in str(e) and attempt < retries - 1:
                print(f"\n429 rate limit hit, waiting {RETRY_DELAY}s before retry {attempt + 1}/{retries - 1}...")
                await asyncio.sleep(RETRY_DELAY)
            else:
                raise


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
        storage=FileTokenStorage(),
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
    )

    try:
        async with streamablehttp_client(SERVER_URL, auth=auth) as (read, write, _get_session_id):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()

                tools = [
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "input_schema": tool.inputSchema,
                    }
                    for tool in result.tools
                ]

                with open("prompts/digest_v1.md") as f:
                    system_prompt = f.read()

                messages = [
                    {"role": "user", "content": "Review all my voice notes and give me my morning briefing."}
                ]

                while True:
                    response = client.messages.create(
                        model=MODEL,
                        max_tokens=1024,
                        system=system_prompt,
                        tools=tools,
                        messages=messages,
                    )

                    print(f"\n=== Response (stop_reason: {response.stop_reason}) ===")
                    for block in response.content:
                        print(block)

                    messages.append({"role": "assistant", "content": response.content})

                    if response.stop_reason != "tool_use":
                        final_text = "\n".join(
                            block.text for block in response.content if block.type == "text"
                        )
                        if not final_text.strip():
                            print("\nNo digest content returned. Exiting without sending.")
                            return
                        print("\n=== Final answer ===")
                        print(final_text)
                        send_sms(final_text)
                        break

                    tool_results = []
                    for block in response.content:
                        if block.type != "tool_use":
                            continue
                        print(f"\n=== Calling tool: {block.name} {block.input} ===")
                        tool_result = await call_tool_with_retry(session, block.name, block.input)
                        result_text = tool_result.content[0].text

                        if block.name == "list_notes" and "Found these notes" not in result_text:
                            print("\nNo notes found. Nothing to digest today.")
                            return

                        print(result_text[:300])
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": result_text,
                            }
                        )

                    messages.append({"role": "user", "content": tool_results})

    except Exception as e:
        error_msg = str(e)
        if "401" in error_msg or "unauthorized" in error_msg.lower() or "auth" in error_msg.lower():
            print("\nAuth error: your Voicenotes session has expired. Re-run the script to re-authenticate.")
        else:
            print(f"\nUnexpected error: {e}")
            raise


if __name__ == "__main__":
    asyncio.run(main())
