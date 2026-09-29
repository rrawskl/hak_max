FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir -r /app/requirements.lock
COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./alembic.ini
COPY data /app/data-source
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
