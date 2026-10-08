FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home atelier
COPY server.py ./
COPY studio.py ./
COPY editorial.py api_v1.py api_docs.py agent.py backup.py search.py research.py ./
COPY public ./public
COPY corpus ./corpus
RUN mkdir -p /app/data && chown -R atelier:atelier /app/data
USER atelier
ENV PYTHONUNBUFFERED=1 ATELIER_BIND=0.0.0.0 ATELIER_PORT=8765 ATELIER_DATA=/app/data
EXPOSE 8765
CMD ["python", "server.py"]
