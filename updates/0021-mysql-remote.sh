#!/bin/bash
# 0021-mysql-remote.sh
#
# Acceso remoto a MySQL por allowlist de IPs (modelo cPanel). Deja preparado el
# set nftables `mysql_remote_allow` y la regla que abre el 3306 SOLO a las IPs de
# ese set (vacío al inicio → 3306 cerrado a internet). El panel añade/quita IPs
# cuando un cliente autoriza el acceso remoto a su BD.
#
# El esquema de BD (tabla db_remote_hosts) lo crea el panel al arrancar (CREATE
# TABLE IF NOT EXISTS en main.py). Aquí solo el firewall. Idempotente.

set -euo pipefail

echo "→ 0021: Acceso remoto MySQL (set nftables + regla 3306)..."

if ! command -v nft >/dev/null 2>&1; then
    echo "  nft no disponible — nada que hacer."
    exit 0
fi
if ! nft list table inet svqpanel >/dev/null 2>&1; then
    echo "  Tabla nftables del panel no cargada — el panel la crea al autorizar la 1ª IP."
    exit 0
fi

# Crear el set si no existe
if ! nft list set inet svqpanel mysql_remote_allow >/dev/null 2>&1; then
    nft add set inet svqpanel mysql_remote_allow '{ type ipv4_addr; flags interval; }'
    echo "  set mysql_remote_allow creado"
fi

# Crear la regla si no está (acepta 3306 solo desde IPs del set)
if ! nft list chain inet svqpanel input 2>/dev/null | grep -q 'mysql_remote_allow'; then
    nft add rule inet svqpanel input tcp dport 3306 ip saddr @mysql_remote_allow accept
    echo "  regla 3306 (allowlist) añadida"
fi

echo "✓ 0021: acceso remoto MySQL preparado (3306 cerrado hasta autorizar IPs)"
exit 0
