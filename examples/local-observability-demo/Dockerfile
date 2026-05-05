FROM python:3.11-slim

WORKDIR /repo

COPY packages/lumen-ai-core ./packages/lumen-ai-core
COPY examples/local-observability-demo/main.py ./main.py

RUN pip install --no-cache-dir fastapi uvicorn redis -e ./packages/lumen-ai-core

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
