FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends g++ && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir uv && uv sync --frozen --no-dev
EXPOSE 8000
CMD ["uv", "run", "--no-sync", "acm-agent", "--web", "--host", "0.0.0.0"]
