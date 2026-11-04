from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
import tinycss2
from playwright.async_api import async_playwright

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}


AUDIT_JS = r"""() => {
  const selectors = [
    'h1','h2','h3','h4','h5','h6','p','span','button','a','label','input','textarea','select',
    '[role="button"]','[class*="badge"]','[class*="pill"]','img'
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
    const idx = el.getAttribute('data-ph-audit-index');
    return idx !== null ? `[data-ph-audit-index="${idx}"]` : el.tagName.toLowerCase();
  };
  const visible = (el, r, s) => r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity) > 0;
  const getBackground = (el) => {
    let cur = el;
    while (cur && cur.nodeType === 1) {
      const st = getComputedStyle(cur);
      if (st.backgroundImage && st.backgroundImage !== 'none') {
        return {known:false, reason:'A background image or gradient is present; rendered-pixel contrast is not measured by this DOM audit.'};
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
  const rectFor = (r) => ({
    x:Math.round(r.x), y:Math.round(r.y + window.scrollY),
    right:Math.round(r.right), bottom:Math.round(r.bottom + window.scrollY),
    width:Math.round(r.width), height:Math.round(r.height)
  });
  const describe = (el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    const text = (el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('alt') || '').trim();
    const parent = el.parentElement;
    const ps = parent ? getComputedStyle(parent) : null;
    const parentIndex = parent ? Number(parent.getAttribute('data-ph-audit-index')) : null;
    return {
      auditIndex:Number(el.getAttribute('data-ph-audit-index')),
      parentIndex:Number.isFinite(parentIndex) ? parentIndex : null,
      tag:el.tagName.toLowerCase(), selector:selectorFor(el),
      id:el.id || '', classes:typeof el.className === 'string' ? el.className : '',
      parentTag:parent ? parent.tagName.toLowerCase() : '',
      parentClasses:parent && typeof parent.className === 'string' ? parent.className : '',
      parentDisplay:ps ? ps.display : '',
      text:text.slice(0,120), rect:rectFor(r),
      x:Math.round(r.x), y:Math.round(r.y), right:Math.round(r.right), bottom:Math.round(r.bottom),
      width:Math.round(r.width), height:Math.round(r.height),
      scrollWidth:el.scrollWidth, clientWidth:el.clientWidth,
      scrollHeight:el.scrollHeight, clientHeight:el.clientHeight,
      overflowX:s.overflowX, overflowY:s.overflowY,
      lineHeight:s.lineHeight, fontSize:s.fontSize, fontWeight:s.fontWeight,
      color:s.color, backgroundColor:s.backgroundColor, backgroundImage:s.backgroundImage,
      display:s.display, position:s.position,
      visible:visible(el,r,s), isImage:el.tagName.toLowerCase()==='img',
      alt:el.getAttribute('alt'), ariaLabel:el.getAttribute('aria-label') || ''
    };
  };
  const elements = nodes.map(describe).filter(e => e.visible && (e.text.length > 0 || e.isImage));
  const notes = [];
  const issues = [];
  const contrastIssues = [];
  const repairHints = [];
  for (const el of elements) {
    const node = document.querySelector(`[data-ph-audit-index="${el.auditIndex}"]`);
    if (el.isImage) {
      if ((!el.alt || !el.alt.trim()) && node?.getAttribute('role') !== 'presentation' && node?.getAttribute('aria-hidden') !== 'true') {
        notes.push({type:'image_alt_review',severity:'info',selector:el.selector,message:'Image has no descriptive alt text. Confirm whether it needs accessible text or is decorative.',measured:`image ${el.width}x${el.height}px`,rect:el.rect});
      }
      continue;
    }
    if (!el.text || !node) continue;
    const bg = getBackground(node);
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
          repairIndexes:[el.auditIndex],recommendedFix:'Choose a sufficiently contrasting text or solid background color, then recheck the rendered result.'});
      }
    } else if (bg.reason && ['h1','h2','h3','p','button','a'].includes(el.tag)) {
      const isGradient = bg.reason.includes('background image or gradient');
      const foreground = parseColor(el.color);
      const isLightText = foreground && luminance(foreground) >= 0.75;

      if (isGradient && isLightText && ['h1','h2','h3','p'].includes(el.tag)) {
        repairHints.push({
          type:'gradient_text_color_preview',
          severity:'info',
          selector:el.selector,
          text:el.text,
          message:'Light text is displayed over a gradient background. Preview black text to improve readability; rendered-pixel contrast is not measured.',
          measured:'Gradient background; pixel-level contrast not measured.',
          rect:el.rect,
          repairIndexes:[el.auditIndex],
          recommendedFix:'Preview black text (#000000) on this text element only. Preserve the gradient and nearby buttons.'
        });
      }

      notes.push({type:'contrast_not_measured',severity:'info',selector:el.selector,text:el.text,
        message:bg.reason,measured:`foreground=${el.color}; backgroundImage=${el.backgroundImage || 'none'}`,rect:el.rect});
    }
    const line = parseFloat(el.lineHeight);
    const fontSize = parseFloat(el.fontSize) || 16;
    if (['h1','h2','h3','p'].includes(el.tag) && line && line < fontSize*1.05) {
      notes.push({type:'tight_line_height_review',severity:'warning',selector:el.selector,text:el.text,
        message:'Line height is unusually tight for this text size. Check complex-script marks and multi-line wrapping visually.',
        measured:`fontSize=${el.fontSize}; lineHeight=${el.lineHeight}`,rect:el.rect});
    }
  }

  const root = document.documentElement;
  if (root.scrollWidth > root.clientWidth + 1) {
    issues.push({type:'page_horizontal_overflow',severity:'high',selector:'html',
      message:'The document is wider than the viewport and may scroll horizontally.',
      measured:`document scrollWidth=${root.scrollWidth}px; viewport=${root.clientWidth}px`,
      rect:{x:0,y:0,right:innerWidth,bottom:innerHeight,width:innerWidth,height:innerHeight},
      repairIndexes:[],recommendedFix:'Inspect the widest child elements. Avoid hiding the overflow until the element causing it is identified.'});
  }
  for (const el of elements) {
    if (el.isImage) continue;
    if (el.scrollWidth > el.clientWidth + 1) {
      issues.push({type:'horizontal_text_or_content_overflow',severity:'high',selector:el.selector,text:el.text,
        message:'Content is wider than its element box.',
        measured:`scrollWidth=${el.scrollWidth}px; clientWidth=${el.clientWidth}px`,rect:el.rect,
        repairIndexes:[el.auditIndex],recommendedFix:'Allow text to wrap or make the element/container responsive.'});
    }
    if (el.scrollHeight > el.clientHeight + 1 && ['hidden','clip'].includes(el.overflowY)) {
      issues.push({type:'possible_vertical_clipping',severity:'high',selector:el.selector,text:el.text,
        message:'Content exceeds the element height while vertical overflow is hidden or clipped.',
        measured:`scrollHeight=${el.scrollHeight}px; clientHeight=${el.clientHeight}px; overflowY=${el.overflowY}`,
        rect:el.rect,repairIndexes:[el.auditIndex],recommendedFix:'Use content-driven height, adequate line-height and visible overflow where appropriate.'});
    }
  }

  const candidates = elements.filter(e => ['button','a','input','textarea','select'].includes(e.tag) || /badge|pill/i.test(e.classes));
  const findCommonAncestorIndex = (a,b) => {
    const na=document.querySelector(`[data-ph-audit-index="${a.auditIndex}"]`);
    const nb=document.querySelector(`[data-ph-audit-index="${b.auditIndex}"]`);
    if (!na || !nb) return null;
    const ancestors=[]; let cur=na.parentElement;
    while(cur){ancestors.push(cur);cur=cur.parentElement;}
    cur=nb.parentElement;
    while(cur){if(ancestors.includes(cur)){const tag=cur.tagName.toLowerCase();if(tag!=='body' && tag!=='html') return Number(cur.getAttribute('data-ph-audit-index'));return null;}cur=cur.parentElement;}
    return null;
  };
  for (let i=0;i<candidates.length;i++) {
    for (let j=i+1;j<candidates.length;j++) {
      const a=candidates[i], b=candidates[j];
      const na=document.querySelector(`[data-ph-audit-index="${a.auditIndex}"]`);
      const nb=document.querySelector(`[data-ph-audit-index="${b.auditIndex}"]`);
      if (!na || !nb || na.contains(nb) || nb.contains(na)) continue;
      const ix=Math.max(0,Math.min(a.right,b.right)-Math.max(a.x,b.x));
      const iy=Math.max(0,Math.min(a.bottom,b.bottom)-Math.max(a.y,b.y));
      const area=ix*iy, smaller=Math.min(a.width*a.height,b.width*b.height);
      if (area>9 && smaller>0 && area/smaller>0.12) {
        const parentIndex=findCommonAncestorIndex(a,b);
        const parentNode = parentIndex === null ? null : document.querySelector(`[data-ph-audit-index="${parentIndex}"]`);
        const parentStyle = parentNode ? getComputedStyle(parentNode) : null;
        const repairContext = {
          parent: parentNode ? {
            auditIndex: parentIndex,
            tag: parentNode.tagName.toLowerCase(),
            classes: typeof parentNode.className === 'string' ? parentNode.className : '',
            display: parentStyle.display,
            position: parentStyle.position
          } : null,
          elements: [a,b].map(e => ({
            auditIndex: e.auditIndex,
            tag: e.tag,
            classes: e.classes,
            display: e.display,
            position: e.position,
            parentClasses: e.parentClasses,
            parentDisplay: e.parentDisplay
          }))
        };
        issues.push({type:'element_overlap',severity:'high',selector:a.selector,text:`${a.text} / ${b.text}`,
          message:'Two separate controls or a control and badge overlap. Review whether the overlap is intentional.',
          measured:`intersection=${ix}x${iy}px (${Math.round(area/smaller*100)}% of the smaller element)`,
          rect:a.rect,rects:[a.rect,b.rect],repairIndexes:parentIndex===null?[a.auditIndex,b.auditIndex]:[parentIndex,a.auditIndex,b.auditIndex],
          repairParentIndex:parentIndex,
          repairContext,
          recommendedFix:'Review the closest shared layout container; a wrapping flex/grid layout and consistent gap may resolve an unintended overlap.'});
      }
    }
  }
  for (const el of elements.filter(e => ['button','a','input','textarea','select'].includes(e.tag))) {
    if (el.width>0 && el.height>0 && (el.width<24 || el.height<24)) {
      notes.push({type:'small_interactive_target',severity:'warning',selector:el.selector,text:el.text,
        message:'Interactive target is smaller than 24x24 CSS pixels. Review pointer/touch usability and spacing.',
        measured:`target=${el.width}x${el.height}px`,rect:el.rect});
    }
  }
  return {
    title:document.title, language:document.documentElement.lang || 'unknown',
    viewport:{width:innerWidth,height:innerHeight},
    document:{scrollWidth:document.documentElement.scrollWidth,clientWidth:document.documentElement.clientWidth},
    elements,issues:[...issues,...contrastIssues],notes,repairHints,elementsChecked:elements.length
  };
}
"""


def _is_local_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False
        if parsed.username or parsed.password:
            return False
        if parsed.hostname not in ALLOWED_HOSTS:
            return False
        if parsed.port is not None and not (1 <= parsed.port <= 65535):
            return False
        return True
    except ValueError:
        return False


async def audit_page(
    url: str,
    viewport_width: int = 390,
    viewport_height: int = 844,
    screenshot_name: str = "audit_before.png",
    language: str = "ta",
    injected_css: str = "",
) -> dict[str, Any]:
    if not _is_local_url(url):
        raise ValueError("Only your own localhost or 127.0.0.1 development websites can be inspected in this release.")

    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    blocked_external: list[str] = []
    async with async_playwright() as p:
        launch_args = {"headless": True, "args": ["--disable-dev-shm-usage", "--no-proxy-server", "--proxy-bypass-list=<-loopback>"]}
        try:
            browser = await p.chromium.launch(**launch_args)
        except Exception as launch_error:
            # Prefer Playwright-managed Chromium; fall back to an OS Chromium install when available.
            system_chromium = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
            if not system_chromium:
                raise launch_error
            browser = await p.chromium.launch(executable_path=system_chromium, **launch_args)
        page = await browser.new_page(
            viewport={"width": viewport_width, "height": viewport_height},
            device_scale_factor=1,
        )

        async def local_only(route):
            request_url = route.request.url
            parsed = urlparse(request_url)
            if parsed.scheme in {"data", "blob", "about"}:
                await route.continue_()
                return
            if parsed.scheme in {"http", "https"} and parsed.hostname in ALLOWED_HOSTS:
                await route.continue_()
                return
            blocked_external.append(request_url[:180])
            await route.abort()

        await page.route("**/*", local_only)
        try:
            response = await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            if response is None and page.url == "about:blank":
                raise RuntimeError("The local website did not return a page.")
            if not _is_local_url(page.url):
                raise ValueError("The website redirected outside localhost; navigation was stopped.")
            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            await page.evaluate("() => document.fonts.ready")
            language_result = await page.evaluate(
                """(lang) => {
                    const hook = typeof window.setLang === 'function';
                    if (hook) window.setLang(lang);
                    document.documentElement.lang = lang;
                    return {hookAvailable:hook, hookApplied:hook};
                }""",
                language,
            )
            await page.evaluate("() => document.fonts.ready")
            await page.add_style_tag(content="*, *::before, *::after { animation: none !important; transition: none !important; caret-color: transparent !important; }")
            if injected_css.strip():
                await page.add_style_tag(content=injected_css)
            await page.evaluate("""() => {
                [...document.querySelectorAll('body *')].forEach((el,i) => el.setAttribute('data-ph-audit-index', String(i)));
            }""")
            metrics = await page.evaluate(AUDIT_JS)

            if not language_result["hookAvailable"]:
                metrics["notes"].append({
                    "type": "language_hook_not_available", "severity": "info",
                    "message": "This page does not expose window.setLang(language). The audit set the document language metadata, but did not translate visible text. Test only the language already rendered by the target page.",
                    "measured": f"requested language={language}; content translation not applied."
                })
            if blocked_external:
                metrics["notes"].append({
                    "type": "external_resources_blocked", "severity": "info",
                    "message": "Requests to non-local hosts were blocked for safety. If this local app relies on an external CDN, its rendered page may be incomplete during this audit.",
                    "measured": f"blocked request count={len(blocked_external)}; examples={blocked_external[:3]}"
                })

            boxes = []
            for issue_number, issue in enumerate(metrics["issues"], start=1):
                rects = issue.get("rects") or ([issue["rect"]] if issue.get("rect") else [])
                for rect_number, rect in enumerate(rects):
                    if rect.get("width", 0) > 0 and rect.get("height", 0) > 0:
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
                        Object.assign(box.style,{position:'absolute',left:r.x+'px',top:r.y+'px',width:r.width+'px',height:r.height+'px',border:'2px solid #fb7185',background:'rgba(251,113,133,0.07)',boxSizing:'border-box'});
                        if (item.label) {
                          const label=document.createElement('span'); label.textContent=item.label;
                          Object.assign(label.style,{position:'absolute',left:'0',top:'0',transform:'translateY(-100%)',background:'#be123c',color:'#fff',font:'bold 10px system-ui',padding:'2px 5px',borderRadius:'4px',whiteSpace:'nowrap'});
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
        finally:
            await browser.close()

    return {
        "url": url,
        "viewport": metrics["viewport"],
        "language": metrics["language"],
        "language_applied": bool(language_result["hookApplied"]),
        "title": metrics["title"],
        "issues": metrics["issues"],
        "issue_count": len(metrics["issues"]),
        "notes": metrics["notes"],
        "repair_hints": metrics.get("repairHints", []),
        "note_count": len(metrics["notes"]),
        "screenshot": f"/static/{screenshot_name}",
        "elements_checked": metrics["elementsChecked"],
        "document": metrics["document"],
        "external_requests_blocked": len(blocked_external),
    }


ALLOWED_PROPERTIES = {
    "display", "height", "min-height", "max-height", "width", "min-width", "max-width",
    "overflow", "overflow-x", "overflow-y", "line-height", "white-space", "overflow-wrap",
    "word-break", "flex-wrap", "gap", "align-items", "justify-content", "padding", "margin",
    "margin-bottom", "margin-top", "position", "box-sizing", "color", "background-color", "font-size", "font-weight",
}


def _safe_spacing_value(value: str, allow_negative: bool = False) -> bool:
    """Allow small bounded CSS spacing values."""
    if value == "0":
        return True

    match = re.fullmatch(
        r"(-?[0-9]+(?:[.][0-9]{1,2})?)(px|rem|em)", value
    )
    if not match:
        return False

    amount = float(match.group(1))
    unit = match.group(2)

    if amount < 0 and not allow_negative:
        return False

    if unit == "em":
        return -1.0 <= amount <= 2.0 if allow_negative else 0.0 <= amount <= 2.0

    return -32.0 <= amount <= 32.0 if allow_negative else 0.0 <= amount <= 32.0


def _is_safe_css_value(prop: str, value: str) -> bool:
    value = value.strip().lower()
    if not value or len(value) > 100:
        return False
    if any(token in value for token in ("url(", "expression(", "javascript:", "!important", "var(", "calc(", "@import", "<", ">")):
        return False
    if prop == "display": return value in {"block", "inline-block", "inline-flex", "flex", "grid"}
    if prop == "height": return value == "auto"
    if prop in {"min-height", "min-width"}: return value in {"0", "0px", "auto"}
    if prop in {"max-height", "max-width"}: return value in {"none", "100%"}
    if prop == "width": return value in {"auto", "100%"}
    if prop in {"overflow", "overflow-x", "overflow-y"}: return value in {"visible", "auto"}
    if prop == "line-height":
        if value == "normal": return True
        try: return 1.1 <= float(value) <= 2.0
        except ValueError: return bool(re.fullmatch(r"(?:1\.[1-9]|2)em", value))
    if prop == "white-space": return value in {"normal", "pre-wrap"}
    if prop == "overflow-wrap": return value in {"normal", "anywhere", "break-word"}
    if prop == "word-break": return value in {"normal", "break-word", "keep-all"}
    if prop == "flex-wrap": return value in {"wrap", "wrap-reverse"}
    if prop == "gap":
        parts = value.split()
        return 1 <= len(parts) <= 2 and all(_safe_spacing_value(part) for part in parts)
    if prop == "align-items": return value in {"center", "stretch", "flex-start", "flex-end"}
    if prop == "justify-content": return value in {"flex-start", "flex-end", "center", "space-between", "space-around"}
    if prop in {"padding", "margin"}:
        parts = value.split()
        return 1 <= len(parts) <= 4 and all(
            _safe_spacing_value(part, allow_negative=(prop == "margin")) for part in parts
        )
    if prop in {"margin-bottom", "margin-top"}:
        return _safe_spacing_value(value, allow_negative=True)
    if prop == "position": return value in {"static", "relative"}
    if prop == "box-sizing": return value == "border-box"
    if prop in {"color", "background-color"}:
        return bool(re.fullmatch(r"#[0-9a-f]{3,8}|black|white|transparent", value))
    if prop == "font-size":
        m = re.fullmatch(r"(\d{1,2})(px|rem)", value)
        if m and 10 <= int(m.group(1)) <= 32:
            return True

        em_match = re.fullmatch(r"(\d+(?:\.\d+)?)em", value)
        if em_match:
            try:
                return 0.8 <= float(em_match.group(1)) <= 1.5
            except ValueError:
                return False

        return False
    if prop == "font-weight": return value in {"400", "500", "600", "700", "bold", "normal"}
    return False


def validate_generated_css(
    raw_css: str,
    allowed_indexes: set[int],
    allowed_properties_by_index: dict[int, set[str]] | None = None
) -> str:
    """Accept only simple rules scoped to DOM audit IDs and a small safe property/value allowlist."""
    cleaned = re.sub(r"```(?:css)?", "", raw_css, flags=re.IGNORECASE).strip()
    rules = tinycss2.parse_stylesheet(cleaned, skip_comments=True, skip_whitespace=True)
    if not rules or len(rules) > 12:
        return ""
    accepted: list[str] = []
    for rule in rules:
        if rule.type != "qualified-rule":
            return ""
        selector = tinycss2.serialize(rule.prelude).strip()
        match = re.fullmatch(r'\[data-ph-audit-index\s*=\s*["\']?(\d+)["\']?\]', selector)
        if not match:
            return ""
        index = int(match.group(1))
        if index not in allowed_indexes:
            return ""
        declarations = tinycss2.parse_declaration_list(rule.content, skip_comments=True, skip_whitespace=True)
        safe_declarations: list[str] = []
        if not declarations:
            return ""
        for declaration in declarations:
            # Ignore unsupported declarations without rejecting other safe rules.
            if declaration.type != "declaration" or declaration.important:
                continue

            prop = declaration.lower_name
            value = tinycss2.serialize(declaration.value).strip()

            if allowed_properties_by_index is not None:
                if prop not in allowed_properties_by_index.get(index, set()):
                    continue

            if prop not in ALLOWED_PROPERTIES:
                continue

            if not _is_safe_css_value(prop, value):
                continue

            safe_declarations.append(f"  {prop}: {value};")
        if safe_declarations:
            stronger_selector = selector + selector
            accepted.append(f'{stronger_selector} {{\n' + "\n".join(safe_declarations) + "\n}")
    return "\n\n".join(accepted)


def _allowed_properties_for_repairs(
    issues: list[dict[str, Any]], allowed_indexes: set[int]
) -> dict[int, set[str]]:
    """Limit each audited element to properties appropriate for its defect."""
    policy = {index: set() for index in allowed_indexes}

    def grant(index: Any, properties: set[str]) -> None:
        try:
            key = int(index)
        except (TypeError, ValueError):
            return
        if key in policy:
            policy[key].update(properties)

    for issue in issues:
        issue_type = issue.get("type")
        indexes = issue.get("repairIndexes", [])

        if issue_type == "possible_vertical_clipping":
            for index in indexes:
                grant(index, {"height", "min-height", "overflow", "line-height"})

        elif issue_type == "horizontal_text_or_content_overflow":
            for index in indexes:
                grant(index, {
                    "max-width", "min-width", "white-space",
                    "overflow-wrap", "box-sizing"
                })

        elif issue_type == "element_overlap":
            parent = issue.get("repairParentIndex")
            if parent is not None:
                grant(parent, {
                    "display", "flex-wrap", "gap",
                    "align-items", "justify-content"
                })

            context = issue.get("repairContext") or {}
            for element in context.get("elements", []):
                if element.get("position") == "absolute":
                    grant(element.get("auditIndex"), {"position"})

        elif issue_type == "gradient_text_color_preview":
            for index in indexes:
                grant(index, {"color"})
        elif issue_type == "low_text_contrast":
            for index in indexes:
                grant(index, {"color", "background-color"})

    return policy


def _fallback_repair(issues: list[dict[str, Any]]) -> str:
    rules: dict[int, dict[str, str]] = {}
    for issue in issues:
        issue_type = issue.get("type")
        indexes = [int(x) for x in issue.get("repairIndexes", []) if str(x).isdigit()]
        if issue_type == "horizontal_text_or_content_overflow":
            for index in indexes:
                rules.setdefault(index, {}).update({
                    "max-width": "100%", "min-width": "0", "white-space": "normal",
                    "overflow-wrap": "anywhere", "box-sizing": "border-box"
                })
        elif issue_type == "possible_vertical_clipping":
            for index in indexes:
                rules.setdefault(index, {}).update({
                    "height": "auto", "min-height": "0", "overflow": "visible", "line-height": "1.4"
                })
        elif issue_type == "element_overlap" and issue.get("repairParentIndex") is not None:
            parent = int(issue["repairParentIndex"])
            rules.setdefault(parent, {}).update({
                "display": "flex", "flex-wrap": "wrap", "gap": "8px", "align-items": "center"
            })
            context = issue.get("repairContext") or {}
            for element in context.get("elements", []):
                if element.get("position") == "absolute":
                    badge_index = element.get("auditIndex")
                    if isinstance(badge_index, int):
                        rules.setdefault(badge_index, {}).update({"position": "static"})
        elif issue_type == "gradient_text_color_preview":
            for index in indexes:
                rules.setdefault(index, {}).update({"color": "#000000"})
        elif issue_type == "low_text_contrast":
            for index in indexes:
                rules.setdefault(index, {}).update({"color": "black"})
    chunks = []
    for index, declarations in rules.items():
        body = "\n".join(f"  {prop}: {value};" for prop, value in declarations.items())
        selector = f'[data-ph-audit-index="{index}"]'
        chunks.append(f'{selector}{selector} {{\n{body}\n}}')
    return "\n\n".join(chunks)


def _normalize_llama_repair(raw_response: str) -> str:
    """Convert Llama JSON property maps into CSS for safety validation."""
    cleaned = raw_response.strip()

    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = chr(10).join(lines).strip()

    try:
        payload = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        return raw_response

    if not isinstance(payload, dict):
        return raw_response

    newline = chr(10)
    chunks = []

    for index, declarations in payload.items():
        if not isinstance(index, str) or not index.isdigit():
            return raw_response
        if not isinstance(declarations, dict):
            return raw_response

        for prop, value in declarations.items():
            if not isinstance(prop, str) or not isinstance(value, str):
                return raw_response

        if declarations:
            body = newline.join(
                f"  {prop}: {value};" for prop, value in declarations.items()
            )
            chunks.append(
                f'[data-ph-audit-index="{index}"] {{'
                + newline + body + newline + "}"
            )

    return (newline + newline).join(chunks) if chunks else raw_response


def get_repair(issues: list[dict[str, Any]]) -> tuple[str, str, str]:
    if not issues:
        return "", "The baseline audit found no measured issues. No CSS repair was necessary.", "none"
    allowed_indexes = {int(i) for issue in issues for i in issue.get("repairIndexes", []) if str(i).isdigit()}
    allowed_properties_by_index = _allowed_properties_for_repairs(issues, allowed_indexes)
    issue_context = [
        {k: issue.get(k) for k in ("type", "severity", "selector", "text", "message", "measured", "repairIndexes", "repairParentIndex", "repairContext", "recommendedFix")}
        for issue in issues
    ]
    prompt = (
        "You are a cautious CSS repair assistant. Return ONLY CSS rules. "
        "You are repairing a temporary preview of a local development page; do not use scripts, URLs, imports, at-rules, pseudo-selectors, "
        "descendant selectors, universal selectors, !important, fixed/absolute positioning or overflow:hidden/clip. "
        "Selectors MUST be exactly [data-ph-audit-index=\"N\"] where N is one of these permitted DOM indexes: "
        f"{sorted(allowed_indexes)}. Do not invent selectors or indexes. "
        "Allowed properties for each exact index (JSON): "
        + json.dumps({
            str(index): sorted(properties)
            for index, properties in allowed_properties_by_index.items()
        })
        + ". Use only properties listed for that exact index. "
        "Unsupported declarations will be discarded. "
        "Global properties safety allowlist: "
        + ", ".join(sorted(ALLOWED_PROPERTIES)) + ". "
        "Use safe responsive values: height:auto, min-height:0, max-width:100%, min-width:0, overflow:visible, "
        "line-height between 1.1 and 2, white-space:normal, overflow-wrap:anywhere, flex-wrap:wrap, modest pixel gaps, "
        "and border-box sizing. Repair instructions by issue type: "
        "For possible_vertical_clipping, modify only the clipped text element using height:auto, min-height:0, overflow:visible and line-height between 1.2 and 1.5. Never add padding or margins. "
        "For element_overlap, use repairParentIndex as the shared layout container. Apply display:flex, flex-wrap:wrap and gap:8px to that parent. If repairContext identifies an absolute-positioned child, set position:static on that child. Never set display:flex on a button or badge. Never add padding or margins. "
        "For horizontal overflow, use max-width:100%, min-width:0, white-space:normal, overflow-wrap:anywhere and box-sizing:border-box on the affected element. "
        "For gradient_text_color_preview, set color:#000000 on the listed heading or paragraph only. Preserve the gradient and buttons. This is a visual preview suggestion, not a measured contrast result. "
        "For contrast, change only the text or solid background color. "
        "Do not modify unrelated elements. Use only the minimum rules needed. Do not redesign the page.\n\n"
        "Measured issues (JSON):\n" + json.dumps(issue_context, ensure_ascii=False)
    )
    try:
        response = requests.post(
            "http://127.0.0.1:11434/api/chat",
            json={
                "model": "llama3.2:3b",
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "keep_alive": "10m",
                "options": {"temperature": 0.0, "num_ctx": 4096}
            },
            timeout=180,
        )
        response.raise_for_status()
        raw_css = response.json().get("message", {}).get("content", "")
        normalized_css = _normalize_llama_repair(raw_css)
        safe_css = validate_generated_css(
            normalized_css, allowed_indexes, allowed_properties_by_index
        )

        if safe_css:
            return safe_css, "The local Meta Llama 3.2 3B model proposed this temporary CSS patch. PerceptaHeal accepted it using a strict selector and property/value allowlist. The target source files were not modified.", "llama3.2:3b"
        model_note = "The local model response did not pass the CSS safety validator."
    except requests.RequestException as exc:
        model_note = f"The local model could not be reached ({type(exc).__name__})."
    except (ValueError, TypeError, KeyError):
        model_note = "The local model returned an unreadable response."

    fallback = _fallback_repair(issues)
    if fallback:
        return fallback, model_note + " PerceptaHeal applied a conservative rule-based preview patch instead. Review it before using it in your source code.", "safe-rule-fallback"
    return "", model_note + " No automatic patch was applied because the issue requires manual review or more context.", "none"
