from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from audit_engine import ALLOWED_HOSTS, audit_page, get_repair

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
app = FastAPI(title="PerceptaHeal", version="0.5.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class AuditRequest(BaseModel):
    url: str = "http://127.0.0.1:8000/demo"
    width: int = Field(default=390, ge=320, le=1920)
    height: int = Field(default=844, ge=480, le=1600)
    language: Literal["ta", "hi", "en", "de"] = "ta"


def validate_local_url(url: str) -> None:
    try:
        parsed = urlparse(url)
        valid_port = parsed.port is None or 1 <= parsed.port <= 65535
    except ValueError:
        valid_port = False
        parsed = urlparse("")
    if (parsed.scheme not in {"http", "https"} or parsed.hostname not in ALLOWED_HOSTS
            or parsed.username or parsed.password or not valid_port):
        raise HTTPException(
            status_code=400,
            detail="This release audits only your own local development websites: use http://localhost:<port> or http://127.0.0.1:<port>. Public URLs and private-network hosts are not accepted.",
        )


@app.get("/", response_class=HTMLResponse)
async def home():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/demo", response_class=HTMLResponse)
async def demo():
    return FileResponse(STATIC_DIR / "demo_target.html")


@app.get("/health")
async def health():
    return {"status": "ok", "project": "PerceptaHeal", "version": app.version}


@app.get("/api/llm-status")
async def llm_status():
    try:
        response = requests.get("http://127.0.0.1:11434/api/tags", timeout=2)
        response.raise_for_status()
        models = [item.get("name", "") for item in response.json().get("models", [])]
        installed = "llama3.2:3b" in models
        return {"available": installed, "model": "llama3.2:3b" if installed else None,
                "message": "Meta Llama 3.2 3B is installed in Ollama." if installed else "Ollama is reachable, but llama3.2:3b is not listed."}
    except requests.RequestException:
        return {"available": False, "model": None, "message": "Ollama is not reachable. Auditing still works; repair will use a safe rule-based preview where possible."}


@app.post("/api/audit")
async def run_audit(req: AuditRequest):
    validate_local_url(req.url)
    try:
        return await audit_page(req.url, req.width, req.height, "audit_before.png", req.language)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Audit failed: {type(exc).__name__}: {exc}") from exc


@app.post("/api/heal")
async def heal(req: AuditRequest):
    """Apply a CSS patch only inside a temporary Playwright preview; never write to the target app."""
    validate_local_url(req.url)
    try:
        before = await audit_page(req.url, req.width, req.height, "audit_before.png", req.language)
        repair_inputs = before["issues"] + before.get("repair_hints", [])
        css, explanation, repair_source = get_repair(repair_inputs)
        after = await audit_page(req.url, req.width, req.height, "audit_after.png", req.language, injected_css=css)
        before_keys = {(x.get("type"), x.get("selector"), x.get("measured")) for x in before["issues"]}
        after_keys = {(x.get("type"), x.get("selector"), x.get("measured")) for x in after["issues"]}
        resolved_count = len(before_keys - after_keys)
        introduced_count = len(after_keys - before_keys)
        improved = after["issue_count"] < before["issue_count"]
        verified = after["issue_count"] == 0 and introduced_count == 0
        if css and not verified and not improved:
            explanation += " The preview patch did not improve the measured audit; inspect the highlighted before/after screenshots."
        elif improved and not verified:
            explanation += " Partial improvement only: one or more measured issues remain."
        if not css:
            explanation += " No patch was applied. This issue needs manual review or richer visual context."
        return {
            "before": before, "after": after, "css_patch": css, "ai_explanation": explanation,
            "repair_source": repair_source, "verified": verified, "improved": improved,
            "resolved_count": resolved_count, "introduced_count": introduced_count,
            "preview_only": True,
            "source_modified": False,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Repair preview failed: {type(exc).__name__}: {exc}") from exc
