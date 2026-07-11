#!/bin/bash
# 0124-ffmpeg-previews-video.sh
#
# BUG: ffmpeg no se instalaba nunca. Sin el, NINGUN Nextcloud alojado en el panel
# puede generar la miniatura de un video: la app Fotos pide
# /apps/photos/api/v1/preview/{id} y responde 404 para cada MP4/MOV/MKV. El
# usuario ve su galeria con las fotos bien y todos los videos en gris.
#
# ffmpeg lo usan tambien otras apps PHP (WordPress con plugins de video,
# conversores, etc.), asi que va como dependencia base del servidor.
#
# ⚠️ OJO — LA MITAD QUE NO ARREGLA ESTE UPDATE:
# El proveedor de previews de video de Nextcloud (OC\Preview\Movie) invoca ffmpeg
# via exec(), y los pools del panel bloquean exec/system/shell_exec por politica
# (disable_functions, ver scripts/php_ini_manager.py). Es decir: con ffmpeg
# instalado pero el hardening COMPLETO, el video SIGUE sin miniatura.
#
# Para que un Nextcloud tenga miniaturas de video hay que relajar el hardening
# de ESE dominio (Domain.php_hardening_relaxed = True → DISABLE_FUNCTIONS_RELAXED,
# que mantiene pcntl_* bloqueado pero permite exec). Es una decision consciente
# por dominio: NO se toca la politica global (un WordPress comprometido en otro
# dominio no debe poder ejecutar comandos del SO).
#
# Las miniaturas de IMAGEN (jpeg/png/HEIC/TIFF) funcionan siempre, con o sin
# hardening: las resuelve imagick/GD dentro de PHP, sin exec.
#
# Reflejado tambien en install.sh (ffmpeg en las dependencias base).
# Idempotente y no interactivo.

set -u

echo "-> 0124: ffmpeg (miniaturas de video en Nextcloud y similares)..."

if command -v ffmpeg >/dev/null 2>&1; then
    echo "  . ffmpeg ya instalado ($(ffmpeg -version 2>/dev/null | head -1 | awk '{print $3}'))"
    echo "OK 0124: sin cambios."
    exit 0
fi

export DEBIAN_FRONTEND=noninteractive
if apt-get install -y -qq ffmpeg >/dev/null 2>&1; then
    echo "  . ffmpeg instalado ($(ffmpeg -version 2>/dev/null | head -1 | awk '{print $3}'))"
else
    # No es critico: sin ffmpeg el resto del panel funciona, solo faltan las
    # miniaturas de video. No tumbamos la cadena de updates por esto.
    echo "  . AVISO: no se pudo instalar ffmpeg (sin miniaturas de video)"
fi

echo "OK 0124: ffmpeg listo."
exit 0
