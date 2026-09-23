# Comandos Docker Útiles

## Construcción
docker build -t trading-api .

## Ejecución
docker run -d -p 8000:8000 trading-api
docker-compose up -d
docker-compose down

## Logs
docker logs <container_id>
docker-compose logs -f api

## Debugging
docker exec -it <container_id> /bin/bash
docker-compose exec api python -c "print('Hola desde Docker')"

## Limpieza
docker system prune -f
docker volume prune -f
docker images prune -f

## Ver uso de recursos
docker stats