# SVQPanel — Sistema de Updates

Cada archivo `NNNN-descripcion.sh` es una migración numerada que `update.sh`
aplica una sola vez en cada servidor instalado.

## Reglas para crear un update

1. **Nombre**: `NNNN-descripcion-corta.sh` — NNNN es el siguiente número libre (4 dígitos, con ceros)
2. **Idempotente**: debe ser seguro de re-ejecutar si falla a mitad. Usa `|| true`, `if ! ...`, `--force`, etc.
3. **`exit 0`** al final si todo fue bien. Cualquier otro exit code detiene la cadena.
4. **No interactivo**: sin `read`, sin prompts. Se ejecuta a las 3am sin terminal.
5. **Loguea lo que hace**: usa `echo` para dejar rastro en `/var/log/svqpanel-update.log`.
6. Haz **commit + push** — los servidores lo descargan en la próxima ejecución del cron.

## Ejemplo de update

```bash
#!/bin/bash
# 0002-ejemplo-cambio.sh
# Descripción: qué hace y por qué

echo "→ Aplicando 0002: ejemplo de cambio..."

# Idempotente: comprueba antes de actuar
if ! grep -q "nueva_directiva" /etc/nginx/nginx.conf; then
    echo "nueva_directiva on;" >> /etc/nginx/nginx.conf
    nginx -t && systemctl reload nginx
    echo "✓ Directiva añadida"
else
    echo "  Ya estaba aplicado, nada que hacer."
fi

exit 0
```

## Historial de updates

| ID   | Descripción                          | Fecha      |
|------|--------------------------------------|------------|
| 0001 | Nginx desde repo oficial + HTTP/3    | 2026-06-04 |
| 0002 | PostgreSQL PGDG (PG15 → PG18)        | 2026-06-04 |
| 0003 | Terminal web — jaula chroot clientes | 2026-06-08 |
| 0004 | Terminal web — fix jaula (pts/binarios) | 2026-06-08 |
| 0005 | Terminal web — jaula por usuario        | 2026-06-08 |
| 0006 | Terminal web — prompt + bienvenida      | 2026-06-08 |
| 0007 | Terminal web — /proc hidepid (procesos) | 2026-06-08 |
| 0008 | Backup scheduler interno (sin timer 1/min) | 2026-06-08 |
| 0009 | Backups con restic (incremental+cifrado)   | 2026-06-09 |
| 0010 | Fix planificador backups (TZ + no morir)   | 2026-06-09 |
| 0011 | Zona horaria → reiniciar servicios de logs | 2026-06-09 |
| 0012 | Métricas: hilo interno (sin timer 5 min)   | 2026-06-09 |
| 0013 | Salud DNS: hilo interno (sin timer 10 min) | 2026-06-09 |
| 0014 | Fix jail Fail2ban postfix-sasl (login SMTP) | 2026-06-09 |
| 0015 | Sistema de licencias del panel             | 2026-06-09 |
| 0016 | Rspamd usa resolver DNS local (DNSBL)      | 2026-06-09 |
| 0017 | named modo IPv4 si no hay IPv6 (auto-rev.) | 2026-06-09 |
| 0018 | nginx listen genérico (enrutado vhosts)    | 2026-06-09 |
| 0019 | nginx max_headers (mitiga HTTP/2 Bomb)     | 2026-06-09 |
| 0020 | Web: gzip global + cache de estáticos     | 2026-06-09 |
| 0021 | Acceso remoto MySQL (allowlist IPs 3306)  | 2026-06-09 |
| 0022 | Exponer docs API (Swagger/ReDoc/OpenAPI)  | 2026-06-10 |
| 0023 | Sincronizar estado SSL del panel en la BD  | 2026-06-11 |
