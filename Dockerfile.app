FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .
COPY database/ /database/

RUN useradd --create-home --uid 10001 appuser \
	&& chown -R appuser:appuser /app /database
USER appuser

EXPOSE 5000

CMD ["python", "api.py"]
