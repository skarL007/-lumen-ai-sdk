FROM python:3.11-slim
WORKDIR /app
RUN pip install fastapi uvicorn anthropic \
    "lumen-ai-core @ git+https://github.com/skarL007/-lumen-ai-sdk.git#subdirectory=packages/lumen-ai-core"
COPY main.py .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
