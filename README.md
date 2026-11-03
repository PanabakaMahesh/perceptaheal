# PerceptaHeal

### AI-Powered Multilingual Visual UI Auditor & Self-Healing CSS Engine

PerceptaHeal is an AI-assisted website quality testing application designed to identify and repair visual layout problems that can occur across different screen sizes and languages.

It focuses on multilingual UI issues such as text clipping, content overflow, overlapping elements and responsive layout problems.

## Problem Statement

A website that looks correct in one language or screen size may become difficult to use when translated into another language or viewed on a smaller device.

For example:
- Tamil and Hindi text may be clipped due to insufficient line height.
- Longer German text may overflow buttons and containers.
- Promotional badges may overlap call-to-action buttons.
- Responsive layouts may behave differently across mobile and desktop screens.

Traditional layout checks do not identify every visual usability problem.

## Proposed Solution

PerceptaHeal provides a workflow to inspect a website, identify measurable visual defects, suggest CSS corrections and verify the repaired page.

**Core workflow:**

Detect → Explain → Repair → Verify

## Key Features

- Multilingual testing: Tamil, Hindi, English and German.
- Responsive viewport testing: Mobile 390px, Mobile 412px and Desktop 1280px.
- Browser-based website inspection using Playwright.
- Detection of horizontal and vertical content overflow.
- Detection of potential text clipping.
- Identification of overlapping interactive elements.
- Contrast measurement where supported by available color information.
- Screenshot-based defect highlighting.
- Safe CSS repair with validation.
- Before-and-after screenshot comparison.
- Automatic re-audit after repairs.

## Technology Stack

| Component | Technology |
|---|---|
| Programming Language | Python |
| Backend | FastAPI |
| Browser Automation | Playwright |
| Frontend | HTML, CSS, JavaScript |
| AI Model | Meta Llama 3.2 3B through Ollama (optional local integration) |
| Data Storage | Local file-based MVP |

## AI Integration

PerceptaHeal is designed to use Meta Llama 3.2 3B through local Ollama inference to assist with CSS repair suggestions.

Generated CSS is subject to safety validation before it is applied.

When the model is unavailable or produces an invalid or unsafe repair, the application can use a predefined safe fallback.

The application also uses deterministic browser measurements to verify layout changes rather than relying only on the language model's claims.

## System Architecture

1. User selects a target website, language and viewport.
2. FastAPI receives the audit request.
3. Playwright renders the selected page.
4. The audit engine measures relevant DOM layout properties.
5. Detected issues are displayed with screenshot highlights.
6. The repair engine generates or selects a safe CSS correction.
7. Playwright captures the repaired page.
8. The second audit evaluates the measured changes.

## Installation – Ubuntu

### 1. Clone the repository

```bash
git clone https://github.com/PanabakaMahesh/perceptaheal.git
cd perceptaheal
```

### 2. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Install Chromium

```bash
python -m playwright install chromium
```

### 5. Optional local AI model

Install Ollama and download the model:

```bash
ollama pull llama3.2:3b
```

### 6. Start the application

```bash
python -m uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

Open the application:

http://127.0.0.1:8000

## Current Testing Coverage

The bundled demo supports four language options:

- Tamil
- Hindi
- English
- German

It supports three viewport configurations:

- 390px mobile
- 412px mobile
- 1280px desktop

The current implementation uses DOM-based measurements and defined visual checks. It does not claim complete pixel-level visual understanding or automated contrast verification over every gradient and photograph.

The multilingual content is currently implemented for the bundled demonstration page.

## Hardware Used

Development environment:

- Intel Core i5-1235U
- 16 GB RAM
- NVIDIA GeForce MX550 2 GB
- Ubuntu Linux
- Visual Studio Code

## Future Improvements

- General-purpose website inspection.
- Screenshot-based visual defect analysis.
- Improved multilingual typography verification.
- More advanced contrast and accessibility evaluation.
- Context-aware AI CSS generation.
- Multi-viewport regression testing.
- Exportable visual audit reports.

## License

This project's original source code is licensed under the MIT License. See the LICENSE file for details.

Third-party libraries, models and external assets remain subject to their respective licenses and terms.