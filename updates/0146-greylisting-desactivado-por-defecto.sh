#!/bin/bash
# 0146-greylisting-desactivado-por-defecto.sh
#
# Desactiva el greylisting de Rspamd globalmente. Pasa a ser OPT-IN: quien lo
# quiera lo activa (global desde Ajustes, o por dominio desde Correo).
#
# ── POR QUÉ ────────────────────────────────────────────────────────────────────
# La teoría dice que una lista gris "solo retrasa" el mensaje: se difiere con un
# 4.7.1 y el emisor legítimo reintenta a los minutos. Medido en producción durante
# un mes (svq1coriahosting), eso NO es lo que pasa. De los 23 correos difundidos:
#
#   cofund.solutions        12 greylist → 0 entregas
#   preciosbajos.store       8 greylist → 0 entregas
#   mail.shiply-office.com   4 greylist → 0 entregas
#   facoan.es                2 greylist → 0 entregas
#   mcdlv.net (Mailchimp)    2 greylist → 0 entregas
#   digimobil.es             1 greylist → 0 entregas
#
# NINGUNO llegó a entregarse jamás. Un retraso que no termina no es un retraso:
# es un bloqueo silencioso. Y como el código es 4.7.1 (temporal), el remitente
# nunca recibe un rebote: cree que lo envió y nadie se entera de nada. El caso
# que lo destapó fue un despacho respondiendo a un cliente: el cliente se enteró
# dos días después y por casualidad.
#
# ── Y ADEMÁS NO APORTABA DETECCIÓN ────────────────────────────────────────────
# De los 23 casos, 22 eran spam real... pero con puntuaciones de 6.5 a 7.9, o sea
# que YA iban a Junk por su propio score (umbral "add header" = 4.00). El
# greylisting no frenó nada que el antispam no frenara solo.
#
# En cambio sí atrapó correo legítimo:
#   facoan.es               score 4.33
#   digimobil.es            score 4.37
#   mail.shiply-office.com  score 4.02 — y otra vez con score 0.00 (limpio del todo)
#
# ── CONTEXTO ──────────────────────────────────────────────────────────────────
# El greylisting es una técnica de 2003, anterior a Bayes y a SPF/DKIM/DMARC.
# Este servidor ya tiene 19 RBLs, Bayes, fuzzy (Pyzor/Razor), SPF/DKIM/DMARC,
# antivirus y CrowdSec. cPanel y Plesk tampoco lo traen activado de serie.
#
# ── QUÉ HACE ESTE UPDATE ──────────────────────────────────────────────────────
# 1) greylist.conf → enabled = false  (efecto inmediato en Rspamd)
# 2) settings.greylisting_enabled → false en la BD del panel, para que la UI
#    refleje la realidad y el estado sobreviva a un reload del panel.
# NO toca los ajustes POR DOMINIO (MailDomain.greylist_enabled): si alguien lo
# tenía desactivado en su dominio, sigue igual. Y quien quiera greylisting puede
# volver a activarlo desde el panel cuando quiera.
#
# Idempotente y no interactivo.
set -e

GREY=/etc/rspamd/local.d/greylist.conf

echo "→ 0146: greylisting desactivado por defecto (pasa a opt-in)…"

if [ ! -d /etc/rspamd ]; then
    echo "  · Rspamd no instalado; nada que hacer"
    exit 0
fi

# ── 1) Fichero de Rspamd ──────────────────────────────────────────────────────
if [ -f "$GREY" ] && grep -qE '^\s*enabled\s*=\s*false' "$GREY"; then
    echo "  · greylist.conf ya estaba en false"
else
    [ -f "$GREY" ] && cp -a "$GREY" "${GREY}.bak-0146-$(date +%Y%m%d%H%M%S)"
    mkdir -p "$(dirname "$GREY")"
    cat > "$GREY" << 'GREYEOF'
# SVQPanel — greylisting global. NO editar manualmente.
enabled = false;
GREYEOF
    chmod 644 "$GREY"
    echo "  · greylist.conf → enabled = false"

    if systemctl is-active --quiet rspamd 2>/dev/null; then
        systemctl reload rspamd 2>/dev/null || systemctl restart rspamd 2>/dev/null || true
        sleep 1
        if systemctl is-active --quiet rspamd; then
            echo "  · Rspamd recargado"
        else
            echo "  ✗ Rspamd no quedó activo tras recargar"
            exit 1
        fi
    fi
fi

# ── 2) Estado en la BD del panel (para que la UI no mienta) ───────────────────
# Si algo falla aquí NO abortamos: lo que protege el correo es el paso 1, y el
# update no debe romper la cadena por no poder tocar la BD.
if [ -f /opt/svqpanel/.env ] && command -v psql >/dev/null 2>&1; then
    SQL="UPDATE settings SET greylisting_enabled = FALSE WHERE id = 1;"
    if su postgres -c "psql -d panel_db -tAc \"$SQL\"" >/dev/null 2>&1; then
        echo "  · settings.greylisting_enabled = false (BD del panel)"
    else
        echo "  ⚠ no se pudo actualizar la BD del panel; desactívalo desde Ajustes"
    fi
fi

echo "  ✓ greylisting apagado. Quien lo quiera, lo activa en Ajustes o por dominio."
echo "✓ 0146: greylisting es ahora opt-in"
exit 0
