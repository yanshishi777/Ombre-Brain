# ============================================================
# Ombre Brain Docker Build
# Docker 构建文件
#
# Build: docker build -t ombre-brain .
# Run:   docker run -e OMBRE_API_KEY=your-key -p 8000:8000 ombre-brain
# ============================================================

FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (leverage Docker cache)
# 先装依赖（利用 Docker 缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

# Copy project files / 复制项目文件
COPY *.py .
COPY entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh
COPY resources ./resources
COPY scripts ./scripts
COPY dashboard.html .
COPY dashboard_assets ./dashboard_assets
COPY config.example.yaml ./config.yaml
RUN chmod +x scripts/*.sh
# 兼容 service start command "python /app/src/server.py"：包装成转交 entrypoint.sh
RUN mkdir -p /app/src && printf 'import os\nos.execvpe("bash", ["bash", "/app/entrypoint.sh"], os.environ)\n' > /app/src/server.py

# Railway: volume is managed via Railway Volumes (ombre-brain-ombre-buckets), not Dockerfile VOLUME
# Default to streamable-http for container (remote access)
# 容器场景默认用 streamable-http
ENV OMBRE_TRANSPORT=streamable-http
ENV OMBRE_BUCKETS_DIR=/app/buckets

EXPOSE 8000

# OMBRE_SERVICE_ROLE=gateway -> clone memory repo + run gateway.py; default -> run server.py (Brain)
CMD ["bash", "entrypoint.sh"]
