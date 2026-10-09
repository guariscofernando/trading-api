# app/dao/UserDAO.py
from sqlalchemy import select
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
