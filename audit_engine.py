from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import requests
from playwright.async_api import async_playwright

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}


AUDIT_JS = r"""() => {
  const selectors = [
    'h1','h2','h3','h4','p','span','button','a','label','input','textarea','select',
    '[role="button"]','[class*="badge"]','img'
  ].join(',');
  const nodes = [...new Set(document.querySelectorAll(selectors))];
  const parseColor = (value) => {
    const m = value.match(/rgba?\(([^)]+)\)/i);
    if (!m) return null;
    const parts = m[1].split(',').map(x => parseFloat(x.trim()));
    if (parts.length < 3 || parts.slice(0,3).some(Number.isNaN)) return null;
    return {r:parts[0], g:parts[1], b:parts[2], a:parts.length > 3 ? parts[3] : 1};
  };
  const selectorFor = (el) => {
    if (el.id) return '#' + CSS.escape(el.id);
    const classes = typeof el.className === 'string' ? el.className.trim().split(/\s+/).filter(Boolean) : [];
    return el.tagName.toLowerCase() + classes.slice(0,2).map(c => '.' + CSS.escape(c)).join('');
  };
  const visible = (el, r, s) => r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity) > 0;
  const getBackground = (el) => {
    let cur = el;
    while (cur && cur.nodeType === 1) {
      const st = getComputedStyle(cur);
      if (st.backgroundImage && st.backgroundImage !== 'none') {
        return {known:false, reason:'A background image or gradient is present; pixel-level contrast is not measured by this MVP.'};
      }
      const c = parseColor(st.backgroundColor);
      if (c && c.a >= 0.98) return {known:true, color:c};
      if (c && c.a > 0.02 && c.a < 0.98) {
        return {known:false, reason:'A translucent background is present; the effective composited color is not calculated.'};
      }
      cur = cur.parentElement;
    }
    return {known:false, reason:'No opaque solid background color could be established.'};
  };
  const luminance = (c) => {
    const vals = [c.r,c.g,c.b].map(v => {
      const x = v / 255;
      return x <= 0.04045 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4);
    });
    return 0.2126*vals[0] + 0.7152*vals[1] + 0.0722*vals[2];
  };
  const describe = (el, index) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    const text = (el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('alt') || '').trim();
    const rect = {x:Math.round(r.x), y:Math.round(r.y + window.scrollY), right:Math.round(r.right), bottom:Math.round(r.bottom + window.scrollY), width:Math.round(r.width), height:Math.round(r.height)};
    return {
      index, tag:el.tagName.toLowerCase(), selector:selectorFor(el),
      id:el.id || '', classes:typeof el.className === 'string' ? el.className : '',
      text:text.slice(0,120), rect,
      x:Math.round(r.x), y:Math.round(r.y), right:Math.round(r.right), bottom:Math.round(r.bottom),
      width:Math.round(r.width), height:Math.round(r.height),
      scrollWidth:el.scrollWidth, clientWidth:el.clientWidth,
      scrollHeight:el.scrollHeight, clientHeight:el.clientHeight,
      overflowX:s.overflowX, overflowY:s.overflowY,
      lineHeight:s.lineHeight, fontSize:s.fontSize, fontWeight:s.fontWeight,
      color:s.color, backgroundColor:s.backgroundColor, backgroundImage:s.backgroundImage,
      display:s.display, position:s.position,
      visible:visible(el,r,s),
      isImage:el.tagName.toLowerCase()==='img',
      alt:el.getAttribute('alt'),
      ariaLabel:el.getAttribute('aria-label') || '',
      parentTag:el.parentElement ? el.parentElement.tagName.toLowerCase() : ''
    };
  };
  const elements = nodes.map(describe).filter(e => e.visible && (e.text.length > 0 || e.isImage));
  const notes = [];
  const contrastIssues = [];
  for (const el of elements) {
    if (el.isImage) {
      if ((!el.alt || !el.alt.trim()) && el.getAttribute('role') !== 'presentation' && el.getAttribute('aria-hidden') !== 'true') {
        notes.push({type:'image_alt_review',severity:'info',selector:el.selector,message:'Image has no descriptive alt text. Confirm whether it needs accessible text or is decorative.',measured:`image ${el.width}x${el.height}px`,rect:el.rect});
      }
      continue;
    }
    if (!el.text) continue;
    const node = document.querySelector(`[data-ph-audit-index="${el.index}"]`);
    const bg = node ? getBackground(node) : {known:false,reason:'Element lookup unavailable.'};
    const fg = parseColor(el.color);
    if (bg.known && fg) {
      const L1 = luminance(fg), L2 = luminance(bg.color);
      const ratio = (Math.max(L1,L2)+0.05)/(Math.min(L1,L2)+0.05);
      const fs = parseFloat(el.fontSize) || 16;
      const fw = parseInt(el.fontWeight,10) || 400;
      const large = fs >= 24 || (fs >= 18.66 && fw >= 700);
      const threshold = large ? 3 : 4.5;
      if (ratio < threshold) {
        contrastIssues.push({type:'low_text_contrast',severity:'medium',selector:el.selector,text:el.text,
          message:`Text contrast is below the ${threshold}:1 WCAG reference threshold for this text size.`,
          measured:`contrast=${ratio.toFixed(2)}:1; expected at least ${threshold}:1`,rect:el.rect,
          recommendedFix:'Increase the text/background contrast. Verify the rendered result after changing the colors.'});
      }
    } else if (bg.reason && (el.tag==='h1' || el.tag==='h2' || el.tag==='p' || el.tag==='button')) {
      notes.push({type:'contrast_not_measured',severity:'info',selector:el.selector,text:el.text,
        message:bg.reason,measured:`foreground=${el.color}; backgroundImage=${el.backgroundImage || 'none'}`,rect:el.rect});
    }
    const line = parseFloat(el.lineHeight);
    if ((el.tag==='h1' || el.tag==='h2' || el.tag==='p') && line && fsOf(el) > 0 && line < fsOf(el)*1.05) {
      notes.push({type:'tight_line_height_review',severity:'warning',selector:el.selector,text:el.text,
        message:'Line height is unusually tight for this text size. Check complex-script marks and multi-line wrapping visually.',
        measured:`fontSize=${el.fontSize}; lineHeight=${el.lineHeight}`,rect:el.rect});
    }
  }
  function fsOf(el){ return parseFloat(el.fontSize)||16; }

  const issues = [];
  if (document.documentElement.scrollWidth > document.documentElement.clientWidth + 1) {
    issues.push({type:'page_horizontal_overflow',severity:'high',selector:'html',
      message:'The document is wider than the viewport and may scroll horizontally.',
      measured:`document scrollWidth=${document.documentElement.scrollWidth}px; viewport=${document.documentElement.clientWidth}px`,
      rect:{x:0,y:0,right:innerWidth,bottom:innerHeight,width:innerWidth,height:innerHeight}});
  }
  for (const el of elements) {
    if (el.isImage) continue;
    if (el.scrollWidth > el.clientWidth + 1) {
      issues.push({type:'horizontal_text_or_content_overflow',severity:'high',selector:el.selector,text:el.text,
        message:'Content is wider than its element box.',
        measured:`scrollWidth=${el.scrollWidth}px; clientWidth=${el.clientWidth}px`,rect:el.rect,
        recommendedFix:'Allow text to wrap or make the element/container responsive.'});
    }
    if (el.scrollHeight > el.clientHeight + 1 && ['hidden','clip'].includes(el.overflowY)) {
      issues.push({type:'possible_vertical_clipping',severity:'high',selector:el.selector,text:el.text,
        message:'Content exceeds the element height while vertical overflow is hidden or clipped.',
        measured:`scrollHeight=${el.scrollHeight}px; clientHeight=${el.clientHeight}px; overflowY=${el.overflowY}`,
        rect:el.rect,recommendedFix:'Use content-driven height, adequate line-height and visible overflow where appropriate.'});
    }
  }

  const candidates = elements.filter(e => ['button','a','input','textarea','select'].includes(e.tag) || /badge|pill/i.test(e.classes));
  for (let i=0;i<candidates.length;i++) {
    for (let j=i+1;j<candidates.length;j++) {
      const a = candidates[i], b = candidates[j];
      const na = document.querySelector(`[data-ph-audit-index="${a.index}"]`);
      const nb = document.querySelector(`[data-ph-audit-index="${b.index}"]`);
      if (!na || !nb || na.contains(nb) || nb.contains(na)) continue;
      const ix = Math.max(0,Math.min(a.right,b.right)-Math.max(a.x,b.x));
      const iy = Math.max(0,Math.min(a.bottom,b.bottom)-Math.max(a.y,b.y));
      const area = ix*iy, smaller = Math.min(a.width*a.height,b.width*b.height);
      if (area > 9 && smaller > 0 && area/smaller > 0.12) {
        issues.push({type:'element_overlap',severity:'high',selector:a.selector,text:`${a.text} / ${b.text}`,
          message:'Two separate controls or a control and badge overlap. Review whether the overlap is intentional.',
          measured:`intersection=${ix}x${iy}px (${Math.round(area/smaller*100)}% of the smaller element)`,
          rect:a.rect,rects:[a.rect,b.rect],
          recommendedFix:'Use a wrapping layout, grid/flex gap, or non-overlapping positioning.'});
      }
    }
  }
  for (const el of elements.filter(e => ['button','a','input','textarea','select'].includes(e.tag))) {
    if (el.width > 0 && el.height > 0 && (el.width < 24 || el.height < 24)) {
      notes.push({type:'small_interactive_target',severity:'warning',selector:el.selector,text:el.text,
        message:'Interactive target is smaller than 24x24 CSS pixels. Review pointer/touch usability and spacing.',
        measured:`target=${el.width}x${el.height}px`,rect:el.rect});
    }
  }
  return {
    title:document.title,
    language:document.documentElement.lang || 'unknown',
    viewport:{width:innerWidth,height:innerHeight},
    document:{scrollWidth:document.documentElement.scrollWidth,clientWidth:document.documentElement.clientWidth},
    elements,issues:[...issues,...contrastIssues],notes,
    elementsChecked:elements.length
  };
}
"""


async def audit_page(
    url: str,
    viewport_width: int = 390,
    viewport_height: int = 844,
    screenshot_name: str = "audit_before.png",
    language: str = "ta",
) -> dict[str, Any]:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(
            viewport={"width": viewport_width, "height": viewport_height},
            device_scale_factor=1,
        )
        await page.goto(url, wait_until="networkidle", timeout=20000)
        await page.evaluate("() => document.fonts.ready")
        await page.evaluate(
            """(lang) => {
              if (typeof window.setLang === 'function') window.setLang(lang);
              document.documentElement.lang = lang;
            }""",
            language,
        )
        await page.evaluate("() => document.fonts.ready")
        await page.add_style_tag(content="*, *::before, *::after { animation: none !important; transition: none !important; caret-color: transparent !important; }")
        await page.evaluate("""() => {
          [...document.querySelectorAll('h1,h2,h3,h4,p,span,button,a,label,input,textarea,select,[role="button"],[class*="badge"],img')]
            .forEach((el,i) => el.setAttribute('data-ph-audit-index', String(i)));
        }""")
        metrics = await page.evaluate(AUDIT_JS)
        issues = metrics["issues"]
        notes = metrics["notes"]

        # Draw non-interactive boxes around measured defects. The overlay is only
        # added after measurement, so it cannot change the metrics being audited.
        boxes = []
        for issue_number, issue in enumerate(issues, start=1):
            rects = issue.get("rects") or ([issue["rect"]] if issue.get("rect") else [])
            for rect_number, rect in enumerate(rects):
                if rect.get("width", 0) > 0 and rect.get("height", 0) > 0:
                    # Keep screenshot labels compact; the dashboard lists the
                    # full issue name and matching number.
                    boxes.append({"rect": rect, "label": str(issue_number) if rect_number == 0 else ""})
        if boxes:
            await page.evaluate(
                """(items) => {
                  const layer = document.createElement('div');
                  layer.setAttribute('data-ph-overlay','true');
                  layer.setAttribute('aria-hidden','true');
                  Object.assign(layer.style,{position:'absolute',inset:'0',pointerEvents:'none',zIndex:'2147483647'});
                  for (const item of items) {
                    const r=item.rect;
                    const box=document.createElement('div');
                    Object.assign(box.style,{position:'absolute',left:r.x+'px',top:r.y+'px',width:r.width+'px',height:r.height+'px',
                      border:'2px solid #ef4444',background:'rgba(239,68,68,0.06)',boxSizing:'border-box'});
                    if (item.label) {
                      const label=document.createElement('span'); label.textContent=item.label;
                      Object.assign(label.style,{position:'absolute',left:'0',top:'0',transform:'translateY(-100%)',
                        background:'#b91c1c',color:'#fff',font:'bold 10px system-ui',padding:'2px 5px',borderRadius:'4px',whiteSpace:'nowrap'});
                      box.appendChild(label);
                    }
                    layer.appendChild(box);
                  }
                  document.body.appendChild(layer);
                }""",
                boxes,
            )
        screenshot_path = STATIC_DIR / screenshot_name
        await page.screenshot(path=str(screenshot_path), full_page=True)
        await browser.close()

    return {
        "url": url,
        "viewport": metrics["viewport"],
        "language": language,
        "title": metrics["title"],
        "issues": issues,
        "issue_count": len(issues),
        "notes": notes,
        "note_count": len(notes),
        "screenshot": f"/static/{screenshot_name}",
        "elements_checked": metrics["elementsChecked"],
        "document": metrics["document"],
    }


def _safe_demo_patch() -> str:
    """Known-safe patch for the bundled multilingual demonstration page."""
    return """/* PerceptaHeal safe demo repair */
.hero-card { background-image: linear-gradient(135deg, #10233f, #173c5e); color: #ffffff; }
.hero-title { height: auto; min-height: 1.5em; line-height: 1.5; overflow: visible; }
.hero-sub { height: auto; line-height: 1.5; overflow: visible; }
.action-row { height: auto; display: flex; flex-wrap: wrap; align-items: center; gap: 12px; }
.pill-btn { width: auto; min-width: 120px; max-width: 100%; height: auto; min-height: 42px; white-space: normal; padding: 10px 16px; line-height: 1.4; }
.promo-badge { position: static; display: inline-block; }
.lang button { color: #fff; }
"""


ALLOWED_SELECTORS = {".hero-card", ".hero-title", ".hero-sub", ".action-row", ".pill-btn", ".promo-badge", ".lang button"}
SELECTOR_DISPLAY = {
    ".hero-card": {"block"}, ".hero-title": {"block"}, ".hero-sub": {"block"},
    ".action-row": {"flex"}, ".pill-btn": {"inline-flex", "inline-block"},
    ".promo-badge": {"inline-block"}, ".lang button": {"inline-block", "inline-flex"},
}


def _safe_value(selector: str, prop: str, value: str) -> bool:
    value = value.strip().lower()
    if not value or len(value) > 100:
        return False
    if any(token in value for token in ("url(", "expression(", "javascript:", "!important", "var(", "calc(")):
        return False
    if prop == "display": return value in SELECTOR_DISPLAY.get(selector, set())
    if prop == "height": return value == "auto"
    if prop == "min-height": return value in {"0", "0px", "1.5em", "42px"}
    if prop == "max-height": return value == "none"
    if prop in {"overflow", "overflow-x", "overflow-y"}: return value == "visible"
    if prop == "line-height":
        try: return 1.2 <= float(value) <= 1.8
        except ValueError: return value in {"normal", "1.4em", "1.5em"}
    if prop == "color": return bool(re.fullmatch(r"#[0-9a-f]{3,8}|white|black", value))
    if prop == "background-color": return bool(re.fullmatch(r"#[0-9a-f]{3,8}|white|black|transparent", value))
    if prop == "background-image": return bool(re.fullmatch(r"linear-gradient\([^;{}]+\)|none", value))
    if prop == "background": return bool(re.fullmatch(r"#[0-9a-f]{3,8}|white|black|transparent", value))
    if prop == "width": return value == "auto"
    if prop == "min-width": return value in {"0", "0px", "115px", "120px"}
    if prop == "max-width": return value in {"100%", "none"}
    if prop == "white-space": return value == "normal"
    if prop == "flex-wrap": return selector == ".action-row" and value == "wrap"
    if prop == "align-items": return selector in {".action-row", ".pill-btn"} and value in {"center", "flex-start"}
    if prop == "justify-content": return selector == ".action-row" and value in {"flex-start", "space-between"}
    if prop == "gap": return selector == ".action-row" and value in {"8px", "10px", "12px", "16px"}
    if prop == "padding": return bool(re.fullmatch(r"(?:0|[0-9]{1,2}px)(?:\s+(?:0|[0-9]{1,2}px)){0,3}", value))
    if prop == "position": return (selector in {".hero-card", ".action-row"} and value == "relative") or (selector == ".promo-badge" and value == "static")
    if prop == "margin-bottom": return value in {"0", "0px", "10px", "12px", "16px", "18px"}
    if prop == "box-sizing": return value == "border-box"
    if prop == "word-break": return value in {"normal", "break-word"}
    if prop == "overflow-wrap": return value in {"normal", "anywhere", "break-word"}
    return False


def validate_generated_css(raw_css: str) -> str:
    cleaned = re.sub(r"```(?:css)?", "", raw_css, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.DOTALL)
    if re.search(r"url\s*\(|expression\s*\(|@import|javascript:|</?style|[<>]", cleaned, re.IGNORECASE):
        return ""
    blocks = re.findall(r"([^{}]+)\{([^{}]*)\}", cleaned)
    if not blocks: return ""
    accepted: list[str] = []
    declarations_by_selector: dict[str, dict[str, str]] = {}
    for selector_text, body in blocks:
        selectors = [x.strip() for x in selector_text.split(",")]
        if len(selectors) != 1 or selectors[0] not in ALLOWED_SELECTORS: return ""
        selector = selectors[0]
        declarations: list[str] = []
        declarations_by_selector[selector] = {}
        for item in body.split(";"):
            if not item.strip(): continue
            if ":" not in item: return ""
            prop, value = item.split(":", 1)
            prop, value = prop.strip().lower(), value.strip()
            if not _safe_value(selector, prop, value): return ""
            declarations.append(f"  {prop}: {value};")
            declarations_by_selector[selector][prop] = value.lower()
        if declarations: accepted.append(selector + " {\n" + "\n".join(declarations) + "\n}")
    required = {
        ".hero-card": {"background-image", "color"},
        ".hero-title": {"height", "overflow", "line-height"},
        ".hero-sub": {"height", "overflow", "line-height"},
        ".action-row": {"height", "display", "flex-wrap"},
        ".pill-btn": {"width", "height", "white-space"},
        ".promo-badge": {"position"},
        ".lang button": {"color"},
    }
    for selector, props in required.items():
        if not props.issubset(declarations_by_selector.get(selector, {}).keys()): return ""
    expected = {
        (".hero-title", "height"): "auto", (".hero-title", "overflow"): "visible",
        (".hero-sub", "height"): "auto", (".hero-sub", "overflow"): "visible",
        (".action-row", "height"): "auto", (".action-row", "display"): "flex",
        (".action-row", "flex-wrap"): "wrap", (".pill-btn", "width"): "auto",
        (".pill-btn", "height"): "auto", (".pill-btn", "white-space"): "normal",
        (".promo-badge", "position"): "static",
        (".lang button", "color"): "#fff",
    }
    for (selector, prop), value in expected.items():
        if declarations_by_selector.get(selector, {}).get(prop) != value: return ""
    hero_bg = declarations_by_selector[".hero-card"]["background-image"].lower()
    hero_color = declarations_by_selector[".hero-card"]["color"].lower()
    if "linear-gradient" not in hero_bg or hero_color not in {"#fff", "#ffffff", "white"}: return ""
    return "\n\n".join(accepted)


def get_repair(issues: list[dict[str, Any]]) -> tuple[str, str]:
    prompt = (
        "You are proposing a minimal CSS repair for the bundled multilingual demo. Return ONLY CSS blocks. "
        "Use only these exact selectors: .hero-card, .hero-title, .hero-sub, .action-row, .pill-btn, .promo-badge, .lang button. "
        "Do not redesign the page. Never use viewport heights, percentage heights, fixed heights, overflow:hidden/clip, "
        "display:flex on text elements, absolute positioning, url(), imports, scripts or external resources. "
        "Use height:auto and overflow:visible for text containers; line-height 1.3–1.6; flex-wrap:wrap for .action-row; "
        "width:auto, height:auto, min-height:42px and white-space:normal for .pill-btn; position:static for .promo-badge; "
        "color:#fff for .lang button. Provide a complete patch for all seven selectors.\n\n"
        f"Measured browser issues: {issues}"
    )
    try:
        response = requests.post(
            "http://127.0.0.1:11434/api/chat",
            json={"model":"llama3.2:3b","messages":[{"role":"user","content":prompt}],"stream":False,"options":{"temperature":0.0,"num_ctx":4096}},
            timeout=90,
        )
        response.raise_for_status()
        raw_css = response.json().get("message", {}).get("content", "")
        safe_css = validate_generated_css(raw_css)
        if safe_css:
            return safe_css, "CSS proposed by the local Meta Llama 3.2 3B model and accepted by PerceptaHeal's constrained CSS validator. The page was re-audited after applying the patch."
    except requests.RequestException:
        pass
    except (ValueError, TypeError, KeyError):
        pass
    return _safe_demo_patch(), "Local Llama is unavailable or returned CSS outside the safety allowlist. PerceptaHeal used its predefined safe demo patch, then re-audited the page."
