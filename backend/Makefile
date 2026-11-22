PY ?= .local/venv/bin/python

dev:
	$(PY) -m uvicorn main:app --reload --host 0.0.0.0 --port 8000

test:
	$(PY) -m pytest tests -q

install:
	$(PY) -m pip install -r requirements.txt

.PHONY: dev test install
