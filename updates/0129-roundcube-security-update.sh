#!/bin/bash
# 0129-roundcube-security-update.sh
#
# Actualiza Roundcube (webmail) a la última versión estable.
#
# POR QUÉ: Roundcube NO viene de apt — el install lo baja como tarball de GitHub
# a /var/www/roundcube. Ni `apt upgrade` ni el update.sh del panel lo tocan, así
# que un servidor instalado hace meses se queda clavado en aquella versión.
# Roundcube 1.7.2 / 1.6.17 (2026-07-05) arreglan, entre otras:
#   · CVE-2026-54433 — XSS almacenado ZERO-CLICK en el render de texto plano
#     (basta con que el cliente ABRA un correo malicioso).
#   · CVE-2026-54432 — XSS almacenado vía MIME type de adjunto sin escapar.
#   · Inyección de sesión en el plugin password, bypass SSRF y un DoS por bucle
#     infinito en el decoder TNEF (winmail.dat, que Outlook manda a diario).
#
# NO reimplementa la lógica aquí: delega en scripts/roundcube_updater.py (el
# mismo módulo que usa el botón del panel), que hace backup + `installto.sh -y`
# oficial + verificación HTTP + reversión automática si el webmail se cae.
#
# Idempotente (si ya está en la última, sale sin tocar nada) y no interactivo.

set -u

echo "→ 0129: actualizar Roundcube (webmail) a la última versión estable…"

RC=/var/www/roundcube

if [ ! -f "$RC/program/include/iniset.php" ]; then
    echo "  · Roundcube no está instalado en $RC; nada que hacer"
    exit 0
fi

PANEL_DIR=/opt/svqpanel
PY="$PANEL_DIR/venv/bin/python"
[ -x "$PY" ] || PY=python3

cd "$PANEL_DIR" || { echo "  ✗ no existe $PANEL_DIR"; exit 1; }

BEFORE=$(grep -oP "RCMAIL_VERSION'\s*,\s*'\K[0-9.]+" "$RC/program/include/iniset.php" 2>/dev/null || echo "?")
echo "  · versión actual: $BEFORE"

# El módulo devuelve rc=0 si actualizó o si ya estaba al día; rc!=0 si falló
# (en cuyo caso él mismo ya revirtió el backup y el webmail sigue sirviendo).
if "$PY" -m scripts.roundcube_updater; then
    AFTER=$(grep -oP "RCMAIL_VERSION'\s*,\s*'\K[0-9.]+" "$RC/program/include/iniset.php" 2>/dev/null || echo "?")
    if [ "$BEFORE" = "$AFTER" ]; then
        echo "✓ 0129: Roundcube ya estaba al día ($AFTER)"
    else
        echo "✓ 0129: Roundcube actualizado $BEFORE → $AFTER"
    fi
    exit 0
fi

# Fallo: el updater ya intentó revertir. No detenemos la cadena de updates por
# esto (el resto de updates no dependen del webmail), pero lo dejamos MUY claro
# en el log para que se revise a mano.
echo "  ✗ 0129: la actualización de Roundcube FALLÓ (se intentó revertir al backup)."
echo "    Revisa /var/log/svqpanel-update.log y /var/backups/svqpanel/roundcube/"
echo "    Reintento manual:  cd $PANEL_DIR && $PY -m scripts.roundcube_updater"
exit 0
