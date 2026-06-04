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
