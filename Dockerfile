ARG PLAYWRIGHT_BASE_IMAGE=mcr.microsoft.com/playwright/python:v1.58.0-noble
FROM ${PLAYWRIGHT_BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

COPY pyproject.toml README.md LICENSE /app/
COPY src /app/src

RUN python -m pip install --upgrade pip && \
    python -m pip install "playwright==1.58.0" && \
    python -m pip install .

RUN mkdir -p /app/browser_data /app/screenshots

EXPOSE 18000

CMD ["python", "-m", "xianyu_mcp.server"]
