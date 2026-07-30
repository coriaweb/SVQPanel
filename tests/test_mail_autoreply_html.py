"""
Auto-respuesta en HTML (scripts/mail_manager.py).

Contexto: la auto-respuesta generaba SIEMPRE texto plano con la extensión
'vacation' de Sieve, metiendo el cuerpo en una cadena entrecomillada y
escapando solo las comillas dobles. Al añadir HTML eso se rompe por dos vías:

  1. El escapado no cubría la barra invertida. Un cuerpo con '\\' generaba un
     Sieve inválido; Dovecot NO ejecuta un script que no compila, así que la
     auto-respuesta quedaba muerta EN SILENCIO (el panel la mostraba activa).
  2. Un cuerpo HTML en text/plain llega al destinatario como código en crudo.

La solución usa el formato multi-line de Sieve (`text:` … `.`), que no necesita
escapar comillas pero SÍ *dot-stuffing* (RFC 5228 §8.1): una línea que empiece
por '.' cierra el bloque y parte el script en dos.

Además, el HTML lo escribe el cliente pero el correo sale firmado con DKIM por
NUESTRA IP: un <script> o un onerror= en una auto-respuesta es phishing servido
por nosotros, y se paga con la reputación de la IP del servidor.

Verificado en el servidor de test (Dovecot 2.4.1): los Sieve que genera este
código compilan con `sievec` y la respuesta llega como multipart/alternative.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.mail_manager import MailManager


sanitize = MailManager.sanitize_autoreply_html
to_text = MailManager._html_to_text
multiline = MailManager._sieve_multiline


# ───────────────────────── saneado: lo peligroso fuera ───────────────────────

@pytest.mark.parametrize("payload", [
    '<script>alert(1)</script>',
    '<SCRIPT>alert(1)</SCRIPT>',
    '<script\n type="text/javascript">alert(1)</script>',
    '<iframe src="http://malo.example"></iframe>',
    '<object data="x.swf"></object>',
    '<embed src="x.swf">',
    '<form action="http://malo.example"><input name="pass"></form>',
    '<meta http-equiv="refresh" content="0;url=http://malo.example">',
    '<base href="http://malo.example/">',
])
def test_elimina_elementos_peligrosos(payload):
    out = sanitize(f"<p>hola</p>{payload}")
    for tag in ("script", "iframe", "object", "embed", "form", "meta", "base"):
        assert f"<{tag}" not in out.lower()
    assert "alert(1)" not in out
    assert "malo.example" not in out
    assert "hola" in out          # el contenido legítimo sobrevive


@pytest.mark.parametrize("attr", [
    '<img src="x" onerror="alert(1)">',
    "<img src='x' onerror='alert(1)'>",
    '<img src="x" onerror=alert(1)>',
    '<div onclick="robar()">texto</div>',
    '<body onload="malo()">texto</body>',
])
def test_elimina_manejadores_de_eventos(attr):
    out = sanitize(attr)
    assert "onerror" not in out.lower()
    assert "onclick" not in out.lower()
    assert "onload" not in out.lower()
    assert "alert(1)" not in out


@pytest.mark.parametrize("html", [
    '<a href="javascript:alert(1)">click</a>',
    '<a href=javascript:alert(1)>click</a>',
    "<a href='vbscript:msgbox(1)'>click</a>",
])
def test_neutraliza_urls_ejecutables(html):
    out = sanitize(html)
    assert "javascript:" not in out.lower()
    assert "vbscript:" not in out.lower()
    assert "click" in out          # el enlace sigue, sin el payload


def test_elimina_comentarios_condicionales_ie():
    out = sanitize('<p>ok</p><!--[if IE]><script>alert(1)</script><![endif]-->')
    assert "alert(1)" not in out
    assert "ok" in out


# ──────────────── saneado: lo legítimo NO se puede destrozar ─────────────────
# El HTML de correo real son tablas anidadas con estilos inline. Si el saneado
# se los come, la plantilla del cliente se ve rota: peor que no tener HTML.

PLANTILLA_REAL = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>Vacaciones de verano</title>
</head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:Arial,Helvetica,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#f5f5f5">
<tr><td align="center" style="padding:40px 15px;">
  <table width="640" style="max-width:640px;background:#ffffff;">
    <tr><td align="center" style="font-size:18px;color:#333333;">
      Nuestras oficinas permanecerán cerradas por
      <strong>vacaciones de verano</strong> del <strong>3 al 14 de agosto.</strong>
    </td></tr>
    <tr><td align="center"><img src="https://ejemplo.com/logo.png" alt="LOGO"
        width="190" style="display:block;border:0;"></td></tr>
    <tr><td bgcolor="#d3dc33" align="center" style="padding:30px 25px;color:#222222;">
      <strong><a href="tel:+34943667987" style="color:#222222;">Tlf.: +34 943 667 987</a></strong>
      <br><br>
      <a href="mailto:info@ejemplo.com" style="font-weight:bold;">info@ejemplo.com</a>
    </td></tr>
  </table>
</td></tr>
</table>
</body>
</html>"""


def test_conserva_el_diseno_de_una_plantilla_real():
    out = sanitize(PLANTILLA_REAL)
    # Maquetación y estilo intactos
    assert out.count("<table") == 2
    assert "bgcolor=\"#d3dc33\"" in out
    assert "max-width:640px" in out
    assert out.count("<strong") == 3
    assert "<br><br>" in out
    # Imagen y enlaces legítimos intactos
    assert 'src="https://ejemplo.com/logo.png"' in out
    assert 'href="tel:+34943667987"' in out
    assert 'href="mailto:info@ejemplo.com"' in out
    # Texto con acentos intacto
    assert "permanecerán" in out


def test_quita_la_estructura_de_documento_pero_conserva_el_estilo_del_body():
    """Dentro de una parte MIME text/html no debe ir <!DOCTYPE>/<html>/<head>.

    El estilo del <body> (fondo, tipografía) sí debe sobrevivir, movido a un
    <div> envolvente: si se pierde, la plantilla se ve sin fondo ni fuente.
    """
    out = sanitize(PLANTILLA_REAL)
    for marca in ("<!doctype", "<html", "<head", "<body", "</body>", "</html>", "<title"):
        assert marca not in out.lower(), f"{marca} no debería sobrevivir"
    assert out.startswith("<div style=")
    assert "background:#f5f5f5" in out
    assert "font-family:Arial" in out


def test_fragmento_sin_body_se_conserva_tal_cual():
    out = sanitize("<p>Estoy de <b>vacaciones</b></p>")
    assert out == "<p>Estoy de <b>vacaciones</b></p>"


# ───────────────────────── fallback en texto plano ──────────────────────────

def test_texto_plano_derivado_del_html():
    txt = to_text(sanitize(PLANTILLA_REAL))
    assert "<" not in txt and ">" not in txt      # sin etiquetas
    assert "permanecerán" in txt
    assert "vacaciones de verano" in txt
    assert "info@ejemplo.com" in txt
    assert "LOGO" in txt                          # el alt de la imagen


def test_texto_plano_no_arrastra_el_title():
    """El <title> de la plantilla no puede acabar siendo la primera línea."""
    txt = to_text(sanitize(PLANTILLA_REAL))
    assert "Vacaciones de verano" not in txt.split("\n")[0]


def test_texto_plano_traduce_entidades():
    txt = to_text("<p>Uno&nbsp;&amp;&nbsp;dos &lt;tres&gt; &quot;cuatro&quot;</p>")
    assert "&nbsp;" not in txt and "&amp;" not in txt
    assert "&" in txt and "<tres>" in txt and '"cuatro"' in txt


# ─────────────────── formato multi-line de Sieve (dot-stuffing) ──────────────

def test_dot_stuffing_de_lineas_que_empiezan_por_punto():
    """Sin esto, una línea con '.' al inicio cierra el bloque y parte el script."""
    out = multiline("linea uno\n.linea peligrosa\nlinea tres")
    assert "\n..linea peligrosa\n" in out
    assert out.split("\n")[0] == "linea uno"      # las demás no se tocan


def test_dot_stuffing_solo_al_inicio_de_linea():
    out = multiline("un.punto.en.medio")
    assert out == "un.punto.en.medio"


def test_normaliza_saltos_de_linea_windows():
    """Un cuerpo pegado desde Windows trae CRLF; el Sieve debe quedar con LF."""
    assert "\r" not in multiline("uno\r\ndos\rtres")


def test_las_comillas_no_necesitan_escape_en_multiline():
    """Es la razón de usar `text:` en vez de una cadena entrecomillada."""
    out = multiline('style="color:#222" y \\ruta\\windows')
    assert out == 'style="color:#222" y \\ruta\\windows'


# ─────────────────────────── casos límite y vacíos ──────────────────────────

@pytest.mark.parametrize("vacio", ["", None])
def test_entradas_vacias_no_revientan(vacio):
    assert sanitize(vacio) == ""
    assert to_text(vacio) == ""


def test_html_que_solo_contiene_payload_no_queda_vacio_sin_control():
    """Si el cliente pega solo un <script>, el saneado deja cadena vacía y el
    generador debe sustituirla por el texto por defecto (no enviar un hueco)."""
    assert sanitize("<script>alert(1)</script>").strip() == ""
