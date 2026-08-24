# Government Browser Agent

A semantic, closed-loop browser agent for government form filling using Playwright + OpenRouter.

## Quick Start

```bash
pip install -e ".[dev]"
playwright install chromium
```

## Run

```bash
uvicorn app.main:app --reload
```

Open http://localhost:8000

## Test

```bash
pytest
```
