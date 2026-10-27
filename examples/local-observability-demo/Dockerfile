FROM python:3.11-slim

WORKDIR /repo

# Same layout as the repository: the dashboard imports the README scenario
# from examples/multi-tenant-cost-report.
COPY packages/lumen-ai-core ./packages/lumen-ai-core
COPY examples/multi-tenant-cost-report ./examples/multi-tenant-cost-report
COPY examples/local-observability-demo ./examples/local-observability-demo

RUN pip install --no-cache-dir fastapi uvicorn redis -e ./packages/lumen-ai-core

EXPOSE 8000
CMD ["uvicorn", "main:app", "--app-dir", "examples/local-observability-demo", "--host", "0.0.0.0", "--port", "8000"]
