# City Infrastructure Designer as a web service (for a server or a hosting service).
#   docker build -t cityinfra .
#   docker run -p 8765:8765 cityinfra          → http://<server>:8765/
# The app has no login: put it behind the office network or a login-protected proxy.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends build-essential cmake git \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /srv/cityinfra
COPY . .
RUN engines/build_engines.sh && pip install --no-cache-dir -e backend
WORKDIR /srv/cityinfra/backend
ENV PORT=8765
EXPOSE 8765
CMD ["sh", "-c", "python -m cityinfra.app --host 0.0.0.0 --port ${PORT} --no-browser"]
