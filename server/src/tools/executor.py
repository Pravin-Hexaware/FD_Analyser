import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict


def execute_generated_script(script_path: str, security_name: str, timeout: int = 180) -> Dict[str, Any]:
    repo_root = Path(__file__).resolve().parent.parent
    script_path_obj = Path(script_path)
    if not script_path_obj.is_absolute():
        script_path_obj = repo_root / script_path_obj

    if not script_path_obj.exists():
        error_message = f"Generated script not found: {script_path_obj}"
        return {
            "status": "error",
            "exit_code": -1,
            "stdout": "",
            "stderr": error_message,
            "command": f"{sys.executable} {script_path_obj} {security_name}",
            "runtime_log": ""
        }

    harness_code = f"""
import asyncio
import importlib.util
import sys
from pathlib import Path

repo_root = Path(r"{repo_root}")
module_path = Path(r"{script_path_obj}")
sys.path.insert(0, str(repo_root))

spec = importlib.util.spec_from_file_location("generated_results_portal", module_path)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)

from playwright.async_api import async_playwright
from services.batch_xbrl_finder import fetch_xbrl_for_company

async def main():
    async with async_playwright() as p:
        from services.batch_xbrl_finder import create_browser_and_context
        browser, ctx = await create_browser_and_context(p)
        try:
            url, period, attempts, annual_url, annual_period, quarterly_url, quarterly_period = await fetch_xbrl_for_company(ctx, sys.argv[1], prefer="any")
            if url:
                print("HEALED_MODULE_OK")
                print(f"xbrl_url={{url}}")
                return 0
            print("HEALED_MODULE_FAIL")
            return 1
        finally:
            await ctx.close()
            await browser.close()

raise SystemExit(asyncio.run(main()))
"""
    command = [sys.executable, "-c", harness_code, security_name]

    try:
        proc = subprocess.Popen(
            command,
            cwd=str(repo_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate(timeout=5)
            return {
                "status": "timeout",
                "exit_code": -1,
                "stdout": stdout,
                "stderr": stderr,
                "command": " ".join(command)
            }

        runtime_log_text = ""
        runtime_path = os.path.join("cache", "generated_script_runtime.log")
        if os.path.exists(runtime_path):
            try:
                with open(runtime_path, "r", encoding="utf-8") as f:
                    runtime_log_text = f.read()
            except Exception:
                runtime_log_text = ""
        else:
            # Fallback: parse runtime log lines from script stdout/stderr output
            combined = "\n".join([stdout or "", stderr or ""])
            lines = []
            recording = False
            for line in combined.splitlines():
                stripped = line.strip()
                if stripped.startswith("RUNTIME_ACTION_LOG"):
                    recording = True
                    continue
                if recording:
                    if stripped == "":
                        continue
                    if stripped.startswith("FINAL_URL:"):
                        break
                    lines.append(line)
            runtime_log_text = "\n".join(lines)

        return {
            "status": "success" if proc.returncode == 0 else "failed",
            "exit_code": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "command": " ".join(command),
            "runtime_log": runtime_log_text
        }
    except Exception as exc:
        return {
            "status": "error",
            "exit_code": -1,
            "stdout": "",
            "stderr": str(exc),
            "command": " ".join(command)
        }
