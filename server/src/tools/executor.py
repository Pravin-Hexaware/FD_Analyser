from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict


def execute_generated_script(
    script_path: str,
    security_name: str,
    timeout: int = 240,
    *,
    use_staging_portal: bool = True,
) -> Dict[str, Any]:
    """
    Run a subprocess harness that imports the staging portal module and exercises
    navigate → search → filters → submit → wait_results → extract XBRL evidence.

    Sets FINBOT_HEAL_DISABLED=1 so PlaywrightHealRequired cannot nest another heal.
    """
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
            "runtime_log": "",
        }

    harness_code = f"""
import asyncio
import importlib.util
import os
import sys
from pathlib import Path

os.environ["FINBOT_HEAL_DISABLED"] = "1"

repo_root = Path(r"{repo_root}")
module_path = Path(r"{script_path_obj}")
sys.path.insert(0, str(repo_root))

module_name = "generated_results_portal"
spec = importlib.util.spec_from_file_location(module_name, module_path)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[module_name] = module
try:
    spec.loader.exec_module(module)
except Exception as exc:
    print("HEALED_MODULE_FAIL")
    print(f"IMPORT_ERROR: {{exc}}")
    raise SystemExit(1)

if not hasattr(module, "ResultsPortal"):
    print("HEALED_MODULE_FAIL")
    print("ERROR: staging module missing ResultsPortal")
    raise SystemExit(1)

PlaywrightHealRequired = getattr(module, "PlaywrightHealRequired", RuntimeError)

import services.batch_xbrl_finder as finder

portal = module.ResultsPortal(
    TARGET_URL=getattr(finder, "BSE_URL", module.ResultsPortal.TARGET_URL),
    HOME_URL=getattr(finder, "BSE_HOME", module.ResultsPortal.HOME_URL),
    USER_AGENT=getattr(finder, "USER_AGENT", module.ResultsPortal.USER_AGENT),
    NAV_TIMEOUT=getattr(finder, "NAV_TIMEOUT", 25000),
    GRID_TIMEOUT=getattr(finder, "GRID_TIMEOUT", 18000),
    XHR_TIMEOUT=getattr(finder, "XHR_TIMEOUT", 12000),
    POPUP_TIMEOUT=getattr(finder, "POPUP_TIMEOUT", 4000),
    POST_CLICK_SETTLE_MS=getattr(finder, "POST_CLICK_SETTLE_MS", 600),
)
finder.PORTAL = portal

async def main():
    company = sys.argv[1]
    print(f"HARNESS_TEST_INPUT={{company}}")
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser, ctx = await finder.create_browser_and_context(p)
        page = None
        try:
            page = await portal.prepare_page(ctx)
            print("HARNESS_PHASE=navigate")
            await portal.navigate(page)
            print("HARNESS_PHASE=search")
            await portal.fill_search(page, company, expected_scrip=company if str(company).strip().isdigit() else None)
            print("HARNESS_PHASE=filters")
            await portal.apply_filters(page)
            print("HARNESS_PHASE=submit")
            await portal.submit(page)
            print("HARNESS_PHASE=wait_results")
            await portal.wait_results(page)
            grid = await portal.results_container(page)
            rows = await portal.data_rows(grid)
            try:
                row_count = await rows.count()
            except Exception:
                row_count = 0
            print(f"HARNESS_ROW_COUNT={{row_count}}")
            if row_count <= 0:
                print("EMPTY_RESULTS_GRID")
                print("HEALED_MODULE_FAIL")
                return 1

            anchors = await portal.document_anchors(grid)
            try:
                anchor_count = await anchors.count()
            except Exception:
                anchor_count = 0
            print(f"HARNESS_ANCHOR_COUNT={{anchor_count}}")

            xbrl_url = None
            for i in range(min(anchor_count, 20)):
                try:
                    href = await anchors.nth(i).get_attribute("href")
                except Exception:
                    href = None
                if not href or str(href).lower().startswith("javascript:"):
                    continue
                abs_url = await portal.resolve_absolute_url(page, href)
                low = (abs_url or "").lower()
                if "xbrl" in low or low.endswith(".xml"):
                    xbrl_url = abs_url
                    break
                if abs_url and abs_url.startswith("http") and "comp_results" not in low:
                    xbrl_url = abs_url

            if not xbrl_url:
                # Fallback: full finder extract once (heal still disabled via env).
                print("HARNESS_PHASE=finder_fallback")
                url, period, attempts, *_rest = await finder.fetch_xbrl_for_company(
                    ctx, company, prefer="any"
                )
                if url:
                    print("HEALED_MODULE_OK")
                    print(f"xbrl_url={{url}}")
                    if period:
                        print(f"period={{period}}")
                    return 0
                print("EMPTY_RESULTS_GRID")
                print("HEALED_MODULE_FAIL")
                return 1

            print("HEALED_MODULE_OK")
            print(f"xbrl_url={{xbrl_url}}")
            return 0
        except PlaywrightHealRequired as exc:
            phase = getattr(exc, "phase", None) or "unknown"
            print("HEALED_MODULE_FAIL")
            print(f"HEAL_DISABLED_FAIL phase={{phase}} reason={{exc}}")
            return 1
        except Exception as exc:
            print("HEALED_MODULE_FAIL")
            print(f"HARNESS_EXCEPTION: {{type(exc).__name__}}: {{exc}}")
            return 1
        finally:
            if page is not None:
                try:
                    await page.close()
                except Exception:
                    pass
            await ctx.close()
            await browser.close()

raise SystemExit(asyncio.run(main()))
"""
    command = [sys.executable, "-c", harness_code, security_name]
    env = {
        **os.environ,
        "PYTHONIOENCODING": "utf-8",
        "FINBOT_HEAL_DISABLED": "1",
    }

    try:
        proc = subprocess.Popen(
            command,
            cwd=str(repo_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate(timeout=5)
            combined_out = (stdout or "") + "\nHARNESS_TIMEOUT"
            return {
                "status": "timeout",
                "exit_code": -1,
                "stdout": combined_out,
                "stderr": stderr or "",
                "command": " ".join(command),
                "runtime_log": "",
            }

        runtime_log_text = ""
        runtime_path = repo_root / "cache" / "generated_script_runtime.log"
        if runtime_path.exists():
            try:
                runtime_log_text = runtime_path.read_text(encoding="utf-8")
            except Exception:
                runtime_log_text = ""

        combined_stdout = stdout or ""
        if runtime_log_text.strip():
            combined_stdout = (
                combined_stdout.rstrip()
                + "\n--- RUNTIME FIELD LOG ---\n"
                + runtime_log_text.strip()
                + "\n"
            )

        return {
            "status": "success" if proc.returncode == 0 else "failed",
            "exit_code": proc.returncode,
            "stdout": combined_stdout,
            "stderr": stderr or "",
            "command": " ".join(command),
            "runtime_log": runtime_log_text,
        }
    except Exception as exc:
        return {
            "status": "error",
            "exit_code": -1,
            "stdout": "",
            "stderr": str(exc),
            "command": " ".join(command),
            "runtime_log": "",
        }
