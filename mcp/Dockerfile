# Serveur MCP de l'Atelier — image minimale, stdlib seule, rien à installer.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MCP_HTTP_HOST=0.0.0.0 \
    MCP_HTTP_PORT=8080

WORKDIR /app
COPY atelier_mcp.py /app/atelier_mcp.py

EXPOSE 8080

# L'image slim n'a pas curl : le healthcheck se fait en python (stdlib).
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python3 -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4).status == 200 else 1)"

CMD ["python3", "-u", "/app/atelier_mcp.py", "--http"]
