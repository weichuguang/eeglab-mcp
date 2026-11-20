"""Protocol-level check: connect to the server over stdio as a real MCP client.

Verifies tool discovery, a live status call, and a rejected unsafe call.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv" / "Scripts" / "python.exe"


async def main() -> int:
    params = StdioServerParameters(
        command=str(PY),
        args=["-m", "eeglab_mcp.server"],
        env={**__import__("os").environ, "PYTHONPATH": str(ROOT / "src"),
             "EEGLAB_MCP_CONFIG": str(ROOT / "config" / "default.yaml")},
    )
    failures = 0
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print("server:", init.server_info.name, init.server_info.version)

            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            print(f"tools discovered: {len(names)}")
            assert len(names) == 21, names
            assert "eeglab_get_status" in names
            assert "eeglab_compute_psd" in names
            print("  discovery OK")

            # 1) a real call against MATLAB
            res = await session.call_tool("eeglab_get_status", {})
            payload = _json(res)
            ok = payload.get("success") is True
            print("  eeglab_get_status ->", "PASS" if ok else "FAIL",
                  "| matlab", payload.get("result", {}).get("matlab_release"))
            failures += 0 if ok else 1

            # 2) an unsafe call must be rejected with a structured error
            res = await session.call_tool("eeglab_inspect_dataset", {"file_path": "C:/Windows/notepad.exe"})
            payload = _json(res)
            err = (payload.get("errors") or [{}])[0].get("code")
            rejected = payload.get("success") is False and err in ("PATH_NOT_ALLOWED", "UNSUPPORTED_FORMAT")
            print("  unsafe path rejected ->", "PASS" if rejected else "FAIL", "|", err)
            failures += 0 if rejected else 1

    print("RESULT:", "PASS" if failures == 0 else f"{failures} failure(s)")
    return 1 if failures else 0


def _json(result) -> dict:
    import json

    for c in result.content:
        if getattr(c, "type", "") == "text":
            try:
                return json.loads(c.text)
            except json.JSONDecodeError:
                continue
    return {}


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
