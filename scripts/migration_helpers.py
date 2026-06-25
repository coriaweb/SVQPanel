"""
Helpers puros del importador de migraciones (sin dependencias de FastAPI),
para que sean fáciles de testear.
"""


def explain_backup_error(stderr: str, stdout: str, hestia_user: str) -> str:
    """Convierte el error crudo de v-backup-user en un mensaje claro y accionable.

    Limpia el ruido de SSH (el típico "Warning: Permanently added ... known
    hosts") y reconoce los fallos más comunes para decir QUÉ hacer.
    """
    raw = ((stderr or "") + "\n" + (stdout or "")).strip()
    lines = [l for l in raw.splitlines()
             if l.strip() and "Permanently added" not in l
             and not l.lower().startswith("warning:")]
    msg = " ".join(lines).strip()
    low = msg.lower()

    if "backup is disabled" in low or "backups are disabled" in low:
        return (f"El usuario «{hestia_user}» tiene los BACKUPS DESHABILITADOS en "
                "el servidor Hestia de origen. Actívalos allí: edita el usuario en "
                "el panel de Hestia y habilita la opción «Backups» (o ejecuta en "
                f"el servidor: v-add-user-backup {hestia_user}). Luego reintenta.")
    if "command not found" in low or "no such file" in low:
        return ("No se encontró v-backup-user en el servidor remoto. "
                "¿Es realmente un servidor HestiaCP o VestaCP?")
    if "doesn't exist" in low or "does not exist" in low or "user does not exist" in low:
        return (f"El usuario «{hestia_user}» no existe en el servidor Hestia de "
                "origen. Revisa el nombre del usuario a exportar.")
    if not msg:
        return ("v-backup-user falló en el remoto sin un mensaje claro. Revisa que "
                f"el usuario «{hestia_user}» existe y tiene backups habilitados en Hestia.")
    return f"v-backup-user falló en el remoto: {msg[:300]}"
