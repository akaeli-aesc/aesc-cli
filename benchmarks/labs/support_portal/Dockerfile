FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY server.py /app/server.py
COPY downloads/ /app/downloads/
COPY private/ /app/private/
COPY static/ /app/static/

EXPOSE 80 22

CMD ["python", "/app/server.py"]
