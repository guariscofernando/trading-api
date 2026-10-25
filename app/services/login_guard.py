# app/services/login_guard.py
"""
Protección del login contra fuerza bruta y relleno de credenciales (credential stuffing).

Se cuentan los intentos FALLIDOS en tres cubos y basta con que uno llegue a su tope para que
el login responda 429 (con Retry-After) hasta que su ventana termine:

  cubo                tope (con LOGIN_MAX_FAILURES = 5)   qué frena
  (IP, usuario)       5                                   a alguien probando contraseñas de una cuenta
  usuario             20  (x4)                            un ataque repartido entre muchas IPs
  IP                  30  (x6)                            a alguien probando muchos usuarios desde una IP

Detalles pensados para no regalar información ni permitir abusos:
  * Se cuentan igual los fallos de usuarios que NO existen: el 429 no revela qué cuentas existen.
  * Durante un bloqueo, ni la contraseña correcta entra (si no, el bloqueo no frena nada).
  * Un login correcto solo reinicia el cubo (IP, usuario): el del usuario no, para que
    un atacante no pueda "limpiar" el contador intercalando accesos válidos.
  * Compromiso conocido: el cubo "usuario" permite que alguien con muchas IPs bloquee a la víctima
    durante la ventana (LOGIN_LOCKOUT_SECONDS). Es el precio de frenar ataques distribuidos;
    el cubo (IP, usuario) nunca puede bloquearle desde su propia IP.
"""
import logging
from typing import List, Tuple

from app.config import config
from app.services.ratelimit import limitador

logger = logging.getLogger("trading-api")

MAX_LARGO_USUARIO = 64    # el usuario forma parte de la clave: se acota para no guardar texto arbitrario


def _cubos(ip: str, username: str) -> List[Tuple[str, int, str]]:
    """(clave, tope, nombre) de los tres cubos."""
    usuario = (username or "").strip().lower()[:MAX_LARGO_USUARIO]
    base = config.LOGIN_MAX_FAILURES
    return [
        (f"lf:iu:{ip}|{usuario}", base, "IP+usuario"),
        (f"lf:u:{usuario}", base * 4, "usuario"),
        (f"lf:i:{ip}", base * 6, "IP"),
    ]


def segundos_de_bloqueo(ip: str, username: str) -> int:
    """Segundos que faltan para poder reintentar, o 0 si el login no está bloqueado."""
    espera = 0
    for clave, tope, _ in _cubos(ip, username):
        fallos, restante = limitador.leer(clave)
        if fallos >= tope:
            espera = max(espera, restante)
    return espera


def registrar_fallo(ip: str, username: str) -> None:
    for clave, tope, nombre in _cubos(ip, username):
        fallos, _ = limitador.contar(clave, config.LOGIN_LOCKOUT_SECONDS)
        if fallos == tope:       # solo al cruzar el umbral: un aviso por bloqueo, no uno por intento
            logger.warning("Login bloqueado por %d fallos (%s): ip=%s", fallos, nombre, ip)


def registrar_exito(ip: str, username: str) -> None:
    limitador.olvidar(_cubos(ip, username)[0][0])
