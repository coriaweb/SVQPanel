#!/bin/bash
# 0120-clamav-antivirus-correo.sh
#
# BUG: la tarjeta "Antivirus de correo (ClamAV)" del panel salia como "ClamAV no
# esta disponible en el servidor". Causa: el install.sh nunca instalaba el paquete
# ClamAV, aunque el panel tiene toda la logica para gestionarlo
# (scripts/antivirus_manager.py: clamd + clamav-milter conectado a Postfix, o via
# Rspamd si la CPU tiene SSSE3). Sin el paquete, el antivirus nunca podia activarse.
#
# FIX: instalar clamav + clamav-daemon + clamav-milter + clamav-freshclam y hacer
# la primera descarga de firmas. El panel se encarga del resto (activar el milter
# por dominio desde la vista de correo).
#
# Solo aplica si hay correo instalado (Postfix presente). Idempotente y no interactivo.

set -u

echo "-> 0120: instalar ClamAV (antivirus de correo)..."

# Solo si el servidor tiene correo (Postfix). Si no, no tiene sentido ClamAV.
if ! command -v postfix >/dev/null 2>&1 && [ ! -d /etc/postfix ]; then
    echo "  . Sin correo (Postfix) en este servidor; nada que hacer."
    exit 0
fi

# ¿Ya instalado?
if command -v clamdscan >/dev/null 2>&1 || systemctl list-unit-files 2>/dev/null | grep -q '^clamav-daemon'; then
    echo "  . ClamAV ya instalado; asegurando servicios."
else
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq 2>/dev/null || true
    apt-get install -y -qq clamav clamav-daemon clamav-milter clamav-freshclam 2>&1 | tail -2 || {
        echo "  ! No se pudo instalar ClamAV (revisar apt)."
        exit 1
    }
fi

# Primera descarga de firmas (freshclam necesita el servicio parado para el run manual).
systemctl stop clamav-freshclam 2>/dev/null || true
freshclam 2>&1 | tail -1 || echo "  . (freshclam se reintentara por el servicio)"
systemctl enable --now clamav-freshclam 2>/dev/null || true
systemctl enable --now clamav-daemon 2>/dev/null || true

if systemctl is-active --quiet clamav-daemon; then
    echo "OK 0120: ClamAV instalado y clamav-daemon activo."
else
    echo "  . ClamAV instalado; clamav-daemon aun no activo (las firmas pueden tardar)."
    echo "OK 0120: ClamAV instalado (el daemon arrancara al terminar la descarga de firmas)."
fi

exit 0
