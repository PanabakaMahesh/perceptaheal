from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Literal

from audit_engine import ALLOWED_HOSTS, audit_page, get_repair, _safe_demo_patch

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
app = FastAPI(title="PerceptaHeal MVP", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class AuditRequest(BaseModel):
    url: str = "http://127.0.0.1:8000/demo"
    width: int = Field(default=390, ge=320, le=1920)
    height: int = Field(default=844, ge=480, le=1600)
    language: Literal["ta", "hi", "en", "de"] = "ta"


def validate_local_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or parsed.hostname not in ALLOWED_HOSTS:
        raise HTTPException(status_code=400, detail="For this MVP, scan only your own local website using localhost or 127.0.0.1.")


@app.get("/", response_class=HTMLResponse)
async def home():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/demo", response_class=HTMLResponse)
async def demo():
    return FileResponse(STATIC_DIR / "demo_target.html")


@app.get("/health")
async def health():
    return {"status": "ok", "project": "PerceptaHeal MVP"}


@app.post("/api/audit")
async def run_audit(req: AuditRequest):
    validate_local_url(req.url)
    try:
        return await audit_page(req.url, req.width, req.height, "audit_before.png", req.language)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Audit failed: {type(exc).__name__}: {exc}") from exc


@app.post("/api/heal")
async def heal(req: AuditRequest):
    validate_local_url(req.url)
    try:
        before = await audit_page(req.url, req.width, req.height, "audit_before.png", req.language)
        css, explanation = get_repair(before["issues"])
        # Patch only the bundled demo page. This keeps the first release safe and reproducible.
        if urlparse(req.url).path != "/demo":
            raise HTTPException(status_code=400, detail="Auto-heal is enabled only for the bundled /demo page in this starter version.")
        patched_page = (STATIC_DIR / "demo_target.html").read_text(encoding="utf-8")
        patched_page = patched_page.replace("</head>", f"<style id='perceptaheal-patch'>{css}</style></head>")
        temp_path = STATIC_DIR / "demo_target_healed.html"
        temp_path.write_text(patched_page, encoding="utf-8")
        after = await audit_page("http://127.0.0.1:8000/demo-healed", req.width, req.height, "audit_after.png", req.language)

        # Closed-loop safeguard: require a complete, visually safer patch.
        # An issue-count reduction alone is only partial improvement; it must
        # not be labelled as a fully verified repair.
        used_fallback_retry = False
        if explanation.startswith("CSS proposed by the local Meta Llama") is False:
            # get_repair already selected the deterministic fallback.
            used_fallback_retry = True
        if after["issue_count"] > 0 and not used_fallback_retry:
            used_fallback_retry = True
            css = _safe_demo_patch()
            explanation = (
                explanation + " The model proposal left measured issues, so PerceptaHeal "
                "rejected it and retried with the complete constrained demo repair."
            )
            patched_page = (STATIC_DIR / "demo_target.html").read_text(encoding="utf-8")
            patched_page = patched_page.replace("</head>", f"<style id='perceptaheal-patch'>{css}</style></head>")
            temp_path.write_text(patched_page, encoding="utf-8")
            after = await audit_page("http://127.0.0.1:8000/demo-healed", req.width, req.height, "audit_after.png", req.language)

        before_keys = {(x.get("type"), x.get("selector")) for x in before["issues"]}
        after_keys = {(x.get("type"), x.get("selector")) for x in after["issues"]}
        resolved_count = len(before_keys - after_keys)
        introduced_count = len(after_keys - before_keys)
        improved = resolved_count > 0 and after["issue_count"] < before["issue_count"]
        verified = after["issue_count"] == 0 and introduced_count == 0
        if not verified and improved:
            explanation += " Partial improvement only: at least one measured issue remains."
        elif not verified:
            explanation += " Repair not verified: inspect remaining issues and the screenshots manually."
        return {
            "before": before,
            "after": after,
            "css_patch": css,
            "ai_explanation": explanation,
            "verified": verified,
            "improved": improved,
            "resolved_count": resolved_count,
            "introduced_count": introduced_count,
            "used_fallback_retry": used_fallback_retry,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Auto-heal failed: {type(exc).__name__}: {exc}") from exc


@app.get("/demo-healed", response_class=HTMLResponse)
async def demo_healed():
    path = STATIC_DIR / "demo_target_healed.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Run Auto-heal first.")
    return FileResponse(path)
