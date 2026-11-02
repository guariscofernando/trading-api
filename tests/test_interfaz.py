"""Fase 17: la interfaz web (/app) se sirve con una CSP estricta y no abre agujeros nuevos."""
import re
from pathlib import Path

CARPETA = Path(__file__).resolve().parent.parent / "static" / "app"


def test_la_interfaz_se_sirve_en_app(client):
    r = client.get("/app/")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert "Mesa de práctica" in r.text
    assert client.get("/app/app.js").status_code == 200 and client.get("/app/app.css").status_code == 200


def test_app_sin_barra_final_redirige_a_la_interfaz(client):
    r = client.get("/app", follow_redirects=False)
    assert r.status_code in (301, 307, 308) and r.headers["location"].endswith("/app/")


def test_la_interfaz_lleva_una_csp_estricta_sin_codigo_en_linea(client):
    for ruta in ("/app/", "/app/app.js", "/app/app.css"):
        h = client.get(ruta).headers
        csp = h["content-security-policy"]
        assert "script-src 'self'" in csp and "style-src 'self'" in csp and "connect-src 'self'" in csp
        assert "unsafe-inline" not in csp and "unsafe-eval" not in csp and "*" not in csp
        assert "frame-ancestors 'none'" in csp and "base-uri 'none'" in csp
        assert h["x-frame-options"] == "DENY" and h["x-content-type-options"] == "nosniff"
        assert h["cache-control"] == "no-cache"


def test_la_csp_de_la_api_no_se_relaja_por_existir_la_interfaz(client):
    h = client.get("/health").headers
    assert h["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
    assert h["cache-control"] == "no-store"
    # un prefijo parecido no hereda la política de la interfaz
    assert client.get("/apple").headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"


def test_el_html_no_tiene_scripts_estilos_ni_manejadores_en_linea():
    html = (CARPETA / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"<script(?![^>]*\bsrc=)", html), "script en línea"
    assert not re.search(r"<style", html, re.I) and not re.search(r"\sstyle\s*=", html, re.I)
    assert not re.search(r"\son[a-z]+\s*=", html, re.I), "manejador en línea (onclick...)"
    assert not re.search(r"(src|href)=[\"']https?://", html), "recurso externo"


def test_el_js_nunca_construye_html_con_datos_ni_evalua_codigo():
    js = (CARPETA / "app.js").read_text(encoding="utf-8")
    for prohibido in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function", "localStorage"):
        assert prohibido not in js, prohibido
    assert not re.search(r"https?://", js), "el cliente solo habla con su propio origen"


def test_el_css_no_carga_nada_externo():
    css = (CARPETA / "app.css").read_text(encoding="utf-8")
    assert "@import" not in css and not re.search(r"url\(\s*[\"']?https?:", css)


def test_no_se_puede_salir_de_la_carpeta_de_la_interfaz(client):
    for ruta in ("/app/../app/main.py", "/app/%2e%2e/app/main.py", "/app/..%2fREADME.md", "/app/../../.env"):
        assert client.get(ruta).status_code in (400, 404)


def test_la_portada_de_la_api_anuncia_la_interfaz(client):
    assert client.get("/").json()["endpoints"]["interfaz"] == "/app/"
