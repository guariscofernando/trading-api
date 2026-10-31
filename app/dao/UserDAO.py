# app/dao/UserDAO.py
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.database import session_scope
from app.models import Usuario, a_dict


class UserDAO:

    def crear_usuario_db(self, username, email, password_hash):
        """Devuelve el id nuevo, o None si el username o el email ya existen."""
        try:
            with session_scope() as sesion:
                usuario = Usuario(username=username, email=email, password_hash=password_hash)
                sesion.add(usuario)
                sesion.flush()          # aquí salta la violación de UNIQUE, no al confirmar
                return usuario.id
        except IntegrityError:
            return None

    def _uno(self, condicion):
        with session_scope() as sesion:
            usuario = sesion.execute(select(Usuario).where(condicion)).scalar_one_or_none()
            return a_dict(usuario) if usuario else None

    def obtener_usuario_por_username(self, username):
        return self._uno(Usuario.username == username)

    def obtener_usuario_por_email(self, email):
        return self._uno(Usuario.email == email)

    def obtener_usuario_por_id(self, user_id):
        return self._uno(Usuario.id == user_id)

    def cambiar_rol(self, username, rol):
        """Cambia el rol de un usuario existente. Devuelve True si lo encontró."""
        with session_scope() as sesion:
            usuario = sesion.execute(select(Usuario).where(Usuario.username == username)).scalar_one_or_none()
            if usuario is None:
                return False
            usuario.rol = rol
            return True

    def revocar_sesiones(self, user_id):
        """Sube la versión de token del usuario: todos sus tokens actuales dejan de valer. Devuelve la nueva versión."""
        with session_scope() as sesion:
            return sesion.execute(
                update(Usuario).where(Usuario.id == user_id)
                .values(token_version=Usuario.token_version + 1).returning(Usuario.token_version)
            ).scalar_one_or_none()

    def cambiar_password(self, user_id, hash_actual, hash_nuevo):
        """
        Cambia la contraseña y revoca las sesiones, en un solo UPDATE condicionado a que el hash siga siendo el que
        se verificó (si otra petición la cambió entremedias no se pisa). Devuelve la nueva versión, o None si no aplicó.
        """
        with session_scope() as sesion:
            return sesion.execute(
                update(Usuario).where(Usuario.id == user_id, Usuario.password_hash == hash_actual)
                .values(password_hash=hash_nuevo, token_version=Usuario.token_version + 1)
                .returning(Usuario.token_version)
            ).scalar_one_or_none()
