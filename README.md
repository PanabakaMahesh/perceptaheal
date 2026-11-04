# PerceptaHeal v0.5 — Matte Black Studio

**PerceptaHeal** is a local-first, AI-assisted multilingual UI auditor and CSS repair-preview tool. It inspects the rendered layout of your own local development website, reports measurable issues, proposes a constrained CSS patch and re-runs the browser audit against a temporary preview.

## What this version does

- Matte-black dashboard with viewport, language and target-URL controls.
- Audits local development sites at `http://localhost:<port>` or `http://127.0.0.1:<port>`.
- Uses Playwright/Chromium to render and capture the selected page.
- Measures page/element horizontal overflow and possible vertical text clipping.
- Checks overlap between controls and badge-like elements.
- Measures text contrast only when a solid opaque background color can be established.
- Flags gradient/image contrast as not pixel-measured and can suggest a temporary black-text preview for light headings and paragraphs on gradients. Also records notes for missing image alt text, small controls and missing language-switch hooks.
- Highlights measured issue locations in the screenshot.
- Uses local Meta Llama 3.2 3B through Ollama when available to propose CSS.
- Validates selectors and CSS declarations against a strict allowlist.
- Uses a conservative rule-based preview when a model proposal is unavailable or invalid.
- Re-audits after the patch and labels the result as verified, partial or not verified.

## Safety and limitations

- **Public URLs are not supported.** Only `localhost`, `127.0.0.1` and `::1` are accepted.
- Requests from the server-side browser to non-local hosts are blocked. A local site that depends on external CDNs may render incompletely during the audit.
- Language selection changes visible text only when the target page exposes `window.setLang(language)`. Otherwise, the document language metadata is set, but the page's content is not translated by PerceptaHeal.
- The CSS repair is a **temporary Playwright preview**. It does not edit or save changes to the target site's source files. Review the CSS and apply it manually if appropriate.
- The model is not guaranteed to be used for every repair. The dashboard reports whether Llama or the safe rule-based fallback supplied the patch.
- This is not a complete WCAG audit or general screenshot-understanding system. Gradients, photographs, translucent layers and other cases may be reported as not measured.
- A zero measured-issue count means only that the implemented checks did not detect an issue; it does not prove universal visual correctness.

## Requirements

- Ubuntu or another Linux development environment
- Python 3.10+
- VS Code (optional)
- Ollama with `llama3.2:3b` (optional; audits work without it)

## Install on Ubuntu

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git curl
cd ~/projects/perceptaheal_starter
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m playwright install chromium
```

Install Ollama separately if you want local model-assisted repair:

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2:3b
```

## Run PerceptaHeal

```bash
cd ~/projects/perceptaheal_starter
source .venv/bin/activate
python -m compileall app.py audit_engine.py
python -m uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`.

## Audit another local website

Start your own frontend/backend development server in a second terminal. For example, to serve the included sample page on port 8765:

```bash
cd ~/projects/perceptaheal_starter
python3 -m http.server 8765 --directory examples
```

In PerceptaHeal, enter:

```text
http://127.0.0.1:8765/sample_site.html
```

Select a viewport and run the audit. You can use the same approach for your own Vite, React, Flask, Django or other local development server. The page must be reachable from the same Ubuntu machine.

## Repair preview

Click **Preview CSS repair**. PerceptaHeal will:

1. Capture a baseline audit.
2. Ask local Llama for a constrained CSS proposal if available.
3. Validate the generated CSS.
4. Use a safe rule-based preview if the model response is unavailable or rejected.
5. Inject the patch into a temporary Playwright browser page.
6. Capture and re-audit the result.

The returned CSS is displayed for review and can be copied. The target website's source files are not modified.

## API endpoints

- `GET /` — dashboard
- `GET /demo` — bundled multilingual demo page
- `GET /health` — backend health
- `GET /api/llm-status` — local Ollama model availability
- `POST /api/audit` — audit a local website
- `POST /api/heal` — create a temporary CSS repair preview and re-audit

## License

Original PerceptaHeal source code is licensed under the MIT License. See `LICENSE`. Third-party software, models and assets remain subject to their own licenses and terms.
