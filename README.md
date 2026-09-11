# Trading API

API REST para gestionar trades de trading.

## Tecnologías
- Python 3.12
- FastAPI
- SQLite

## Endpoints

### Trades
- `POST /trades/` - Crear un nuevo trade
- `GET /trades/` - Listar trades (con filtros)
- `GET /trades/{id}` - Obtener un trade específico
- `PATCH /trades/{id}` - Actualizar un trade
- `DELETE /trades/{id}` - Eliminar un trade

### Análisis
- `GET /trades/resumen/pnl` - Calcular P&L total
- `GET /trades/estadisticas` - Estadísticas generales

## Instalación

1. Clonar el repositorio
2. Crear entorno virtual: `python -m venv venv`
3. Activar: `venv\Scripts\activate` (Windows) o `source venv/bin/activate` (Linux/Mac)
4. Instalar dependencias: `pip install -r requirements.txt`
5. Ejecutar: `uvicorn app.main:app --reload`
6. Documentación: http://127.0.0.1:8000/docs

## Ejemplo de uso

### Crear un trade
```json
POST /trades/
{
    "tipo": "compra",
    "activo": "BTC",
    "precio": 50000,
    "cantidad": 0.5
}