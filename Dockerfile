# Dockerfile

# Usar imagen oficial de Python
FROM python:3.12-slim

# Establecer directorio de trabajo
WORKDIR /app

# Instalar dependencias del sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements primero (para aprovechar caché de Docker)
COPY requirements.txt .

# Instalar dependencias
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el resto del código
COPY . .

# Crear carpeta para datos
RUN mkdir -p data static

# Crear usuario no-root por seguridad
RUN useradd -m appuser
USER appuser

# Exponer el puerto
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://localhost:%s/health' % os.environ.get('PORT', '8000'))"

# Comando para ejecutar la aplicación
# El puerto lo da la plataforma en $PORT (Render, Railway...); en local es 8000.
# --workers: 1 por defecto. Con WEB_CONCURRENCY > 1 hace falta REDIS_URL (la app no arranca sin él): el chat, las
# notificaciones y el caché se sincronizan entre procesos por Redis (app/services/bus.py).
# Aplica las migraciones y luego arranca. Si la migración falla, el contenedor termina con error
# (el despliegue se marca como fallido) en lugar de servir tráfico con un esquema a medias.
# Con varias instancias a la vez, Alembic las serializa con un bloqueo de PostgreSQL.
# --no-proxy-headers: uvicorn NO debe reescribir la IP del cliente a partir de X-Forwarded-For. Si alguien define
# FORWARDED_ALLOW_IPS='*' (algo que recomiendan algunas guías de PaaS), uvicorn tomaría la entrada MÁS A LA IZQUIERDA
# de la cabecera, que escribe el propio cliente, y el rate limit y el bloqueo del login se evadirían cambiando una
# cabecera. La IP real la calcula la aplicación (TRUSTED_PROXY_COUNT, ver README).
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WEB_CONCURRENCY:-1} --no-proxy-headers"]