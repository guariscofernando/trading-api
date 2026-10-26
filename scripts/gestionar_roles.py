"""
Gestiona el rol de un usuario. Es la ÚNICA vía para crear administradores: la API pública
(registro, login) nunca asigna ni acepta roles.

    python scripts/gestionar_roles.py promover <username>   # -> admin
    python scripts/gestionar_roles.py degradar <username>   # -> usuario
    python scripts/gestionar_roles.py listar                # muestra los administradores

Usa la DATABASE_URL del entorno (.env). En Docker/Render/Railway, ejecútalo en una shell de la
instancia (p. ej. `docker compose exec api python scripts/gestionar_roles.py promover ana`).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from sqlalchemy import select  # noqa: E402

from app.dao.UserDAO import UserDAO  # noqa: E402
from app.database import session_scope  # noqa: E402
from app.models import Usuario  # noqa: E402


def main(argv) -> int:
    if not argv or argv[0] not in ("promover", "degradar", "listar"):
        print(__doc__)
        return 2
    accion = argv[0]
    if accion == "listar":
        with session_scope() as sesion:
            admins = sesion.execute(select(Usuario.username).where(Usuario.rol == "admin")).scalars().all()
        print("Administradores:", ", ".join(admins) if admins else "(ninguno)")
        return 0
    if len(argv) != 2:
        print(__doc__)
        return 2
    username = argv[1].strip().lower()      # el registro guarda los usernames en minúsculas
    rol = "admin" if accion == "promover" else "usuario"
    if not UserDAO().cambiar_rol(username, rol):
        print(f"No existe el usuario '{username}'. Debe registrarse primero.")
        return 1
    print(f"'{username}' ahora tiene el rol '{rol}'.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
