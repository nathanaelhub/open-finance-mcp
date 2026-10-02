"""Run the plugin eval suite against the local server code.

    SEC_USER_AGENT="Name you@example.com" uv run python scripts/run_evals.py [claude plugin eval flags...]

Eval runs do not pass plugin userConfig values or the shell environment to a
plugin's MCP server, so the published manifest (which reads the SEC contact
from userConfig and installs the server from a git tag) cannot be evaluated
as-is. This copies plugin/ to a temp dir, points its server at this checkout
with the contact written in literally, and runs `claude plugin eval` on the
copy. Nothing written here is committed.

Defaults: real server (--mocks off), all open-finance tools plus web search
granted in both arms, trace kept out of the repo. Extra arguments are passed
through (e.g. --case consumer-comps --runs 1 --ablation none).
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = "mcp__plugin_open-finance_open-finance__"
TOOLS = ["lookup_company", "get_financials", "get_filings", "get_market_data",
         "get_treasury_yield", "get_comps"]


def main() -> int:
    contact = os.environ.get("SEC_USER_AGENT") or os.environ.get("OPEN_FINANCE_SEC_USER_AGENT")
    if not contact or "@" not in contact:
        sys.exit('set SEC_USER_AGENT="Your Name you@example.com" first')

    work = Path(tempfile.mkdtemp(prefix="open-finance-evals-"))
    plugin = work / "plugin"
    shutil.copytree(ROOT / "plugin", plugin, ignore=shutil.ignore_patterns("results"))
    manifest = plugin / ".claude-plugin" / "plugin.json"
    m = json.loads(manifest.read_text())
    m.pop("userConfig", None)
    m["mcpServers"]["open-finance"] = {
        "command": "uv",
        "args": ["run", "--quiet", "--directory", str(ROOT), "open-finance-mcp"],
        "env": {"SEC_USER_AGENT": contact,
                "OPEN_FINANCE_MCP_CACHE": str(work / "cache")},
    }
    manifest.write_text(json.dumps(m, indent=2))

    out = ROOT / "plugin" / "evals" / "results"
    cmd = ["claude", "plugin", "eval", str(plugin), "--mocks", "off", "--trust-plugin",
           "--output-dir", str(out / "latest"),
           "--allow-tools", *[SERVER + t for t in TOOLS], "WebSearch", "WebFetch",
           *sys.argv[1:]]
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"} \
        if os.environ.get("OPEN_FINANCE_EVAL_USE_LOGIN") else dict(os.environ)
    print("+", " ".join(cmd[:4]), "...", flush=True)
    return subprocess.call(cmd, env=env)


if __name__ == "__main__":
    sys.exit(main())
