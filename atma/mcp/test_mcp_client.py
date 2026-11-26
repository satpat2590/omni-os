#!/usr/bin/env python3
"""Test script to verify Atma MCP server works in stdio mode."""
import asyncio
import json
import os
import sys
import subprocess
from typing import Any

async def test_mcp_server():
    """Test the MCP server by connecting to it via stdio."""
    # Start the MCP server as a subprocess
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "atma_remote_server.py"),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**dict(os.environ), **{
            "ATMA_BASE_URL": os.environ.get("ATMA_BASE_URL", "http://127.0.0.1:8602"),
            "ATMA_BEARER_TOKEN": os.environ.get("ATMA_BEARER_TOKEN", ""),
            "ATMA_HTTP_TIMEOUT": "30"
        }}
    )
    
    try:
        # Send initialization request
        init_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "test-client",
                    "version": "1.0.0"
                }
            }
        }
        
        # Write request
        proc.stdin.write(json.dumps(init_request).encode() + b"\n")
        await proc.stdin.drain()
        
        # Read response with timeout
        try:
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=5.0)
            response = json.loads(line.decode())
            print(f"Received response: {json.dumps(response, indent=2)}")
            return True
        except asyncio.TimeoutError:
            print("Timeout waiting for response")
            return False
        except json.JSONDecodeError as e:
            print(f"Failed to parse JSON: {e}")
            return False
            
    finally:
        # Clean up
        try:
            proc.terminate()
            await proc.wait()
        except:
            pass

if __name__ == "__main__":
    import os
    # Run the test
    success = asyncio.run(test_mcp_server())
    sys.exit(0 if success else 1)