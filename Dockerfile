FROM node:22-slim AS frontend-build
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/runtime.ts frontend/app.ts frontend/tsconfig.json ./
RUN npm run build

FROM python:3.12-slim AS python-dependencies
COPY requirements.txt /build/requirements.txt
RUN pip install --no-cache-dir --prefix=/install -r /build/requirements.txt

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV HOST=0.0.0.0
ENV CLARA_ENV=pilot
ENV CLARA_REQUIRE_AUTH=true
ENV CLARA_ALLOW_REAL_XML=false
ENV CLARA_AUDIT_PATH=/data/audit.jsonl
WORKDIR /app
COPY --from=python-dependencies /install /usr/local
COPY backend ./backend
COPY data/regulatory_sources.json data/prompt_registry.json data/risk_register.json ./data/
COPY SOUL.md ./
COPY frontend/index.html frontend/*.css ./frontend/
COPY --from=frontend-build /build/frontend/app.js ./frontend/app.js
RUN useradd --uid 10001 --create-home clara && mkdir /data && chown clara:clara /data
USER clara
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8765')+'/api/ready', timeout=4)"
CMD ["python", "-u", "backend/server.py"]
