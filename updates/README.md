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
| 0024 | Limpiar vhosts huérfanos nginx/Apache       | 2026-06-23 |
| 0025 | Dominio canónico: forzar www (defensivo DNS) | 2026-06-23 |
| 0026 | Backfill DNS: ip_address + AAAA/ip6 en SPF   | 2026-06-23 |
| 0027 | Endurecer cifrados TLS (AEAD + prefer order) | 2026-06-23 |
| 0028 | Fix listen atado a IP en vhosts webmail/mail | 2026-06-23 |
| 0029 | TLS: algoritmos de firma SHA-256+ (sin SHA-224) | 2026-06-23 |
| 0030 | CAA Let's Encrypt en zonas DNS (issue+issuewild) | 2026-06-23 |
| 0031 | IP de salida SMTP por dominio con IPv6 (pref)  | 2026-06-23 |
| 0032 | Fix permisos home 750→711 (403 Forbidden web)  | 2026-06-23 |
| 0033 | Límite correo no autenticado (sitios hackeados) | 2026-06-24 |
| 0034 | Bajar límite no-auth a 10/h (empujar a SMTP)    | 2026-06-24 |
| 0035 | Aprendizaje de spam (Bayes + IMAPSieve Junk)   | 2026-06-24 |
| 0036 | Aprendizaje spam también por flag (Thunderbird) | 2026-06-24 |
| 0037 | SMTPS puerto 465 (SSL/TLS directo, además de 587) | 2026-06-24 |
| 0038 | Carpetas correo visibles en Thunderbird (auto-sub) | 2026-06-24 |
| 0039 | Auto-actualizaciones de seguridad del SO (unattended)| 2026-06-24 |
| 0040 | Endurecer servicios (banner SMTP/VRFY, BIND version)| 2026-06-24 |
| 0041 | Protección anti zip-bomb del antispam (Rspamd)      | 2026-06-24 |
| 0042 | Fix IPv6: netplan→networkd + ruta persistente (red rota al reiniciar) | 2026-06-25 |
| 0043 | Apache DirectoryIndex: index.php antes que index.html  | 2026-06-25 |
| 0044 | Página de suspensión escucha en IPv6 (cert válido)    | 2026-06-25 |
| 0045 | proxy_read_timeout /api/ a 1800s (504 en migraciones) | 2026-06-25 |
| 0046 | Carpeta de staging de migraciones (reutilizar backup) | 2026-06-25 |
| 0047 | GeoIP (países) en estadísticas de dominio + cron mensual | 2026-06-25 |
| 0048 | Informes de GoAccess en español (locale es_ES.UTF-8)   | 2026-06-26 |
| 0049 | Fix cluster DNS: declarar zonas nuevas en el slave     | 2026-06-26 |
| 0050 | Seguridad: cerrar recursión DNS (open resolver/DDoS)  | 2026-06-26 |
| 0051 | Instalar daemon cron (no corría ningún cronjob)       | 2026-06-26 |
| 0052 | Historial de ejecuciones de cron (wrapper + cola)     | 2026-06-26 |
| 0053 | Project quota: el correo cuenta en el disco del user  | 2026-06-26 |
| 0054 | Control de greylisting (global + por dominio)         | 2026-06-26 |
| 0055 | fail2ban: arreglar jail dovecot (aggressive) + jail postfix relay | 2026-06-26 |
| 0056 | Mover el spam marcado (X-Spam: Yes) a la carpeta Junk (Sieve global) | 2026-06-26 |
| 0057 | Unificar carpeta de spam en 'Junk' (Roundcube + migrar Spam→Junk + reentrenar) | 2026-06-26 |
| 0058 | Antispam: Bayes autoequilibrado (autolearn ham 0.5) + overrides admin (pesos/umbrales/reglas) | 2026-06-27 |
| 0059 | Umbral antispam por dominio hereda el global del admin (NULL = no personalizado) | 2026-06-27 |
| 0060 | Reglas antispam del admin a multimap.conf (un .conf aparte se ignoraba) + fix escape '/' y modo exacto/contiene | 2026-06-27 |
| 0061 | Resolver DNS propio (unbound localhost:5353) para Rspamd: reactiva SPF/DKIM/DMARC/RBL (el named del cluster los rechazaba) | 2026-06-27 |
| 0062 | Regenera config de correo de Dovecot en sintaxis 2.4 (quota + spam-learn + spam-junk + SNI) tras upgrade a Debian 13; no-op en Dovecot 2.3 | 2026-06-27 |
| 0063 | Reenvíos seguros: SRS (postsrsd) reescribe el envelope-from a @mydomain + fija la IP de salida del servidor (smtp_bind_address/6) + genera DKIM del dominio del servidor. Evita rebotes/blacklist al reenviar a Gmail/Outlook | 2026-06-27 |
| 0064 | SRS solo reescribe reenvíos: excluye los dominios locales (SRS_EXCLUDE_DOMAINS) para no tocar el correo propio (formularios PHP, buzón→buzón). Se mantiene sincronizado al crear/borrar dominios | 2026-06-27 |
| 0065 | fail2ban: jail para bots "lentos" de relay (Relay access denied, ventana 6h) que esquivan la jail postfix normal | 2026-06-29 |
| 0068 | Fix journalmatch Postfix en fail2ban (D13 usa postfix.service, no postfix@-.service): las jails de correo estaban ciegas | 2026-06-29 |
| 0069 | Antispam: marcar correo con cuerpo en cirílico → Junk (spam de formularios web ES y spam ruso) | 2026-06-29 |
| 0066 | Importación de backups en subproceso aislado + tar en streaming (no OOM); marca como fallidas las migraciones zombie en 'running' de la versión anterior | 2026-06-29 |
| 0067 | Temporales de migración a /var/lib/svqpanel/migration-tmp (disco real, no /tmp/tmpfs que se llenaba con backups grandes) + limpia huérfanos de varios GB de migraciones muertas por OOM | 2026-06-29 |
| 0070 | Fix HTTP/3: quitar `reuseport` del listen quic (rompía nginx con "duplicate listen options for 0.0.0.0:443" al 2º dominio con HTTP/3 → bloqueaba reloads y migraciones); regenera todos los vhosts | 2026-06-30 |
| 0071 | Subir límite de subida del gestor de archivos (100→2048 MB) y de extracción (500→5120 MB); demasiado bajo para un WordPress. Solo toca filas en el default viejo | 2026-06-30 |
| 0072 | Geo-bloqueo también cubre IPv6 (ipdeny v4+v6); refresca las listas geo_* existentes para que bloquear un país filtre además sus rangos IPv6 | 2026-06-30 |
| 0073 | Bloquear bots de robo de credenciales cloud (Silvy X Ran) + escáneres (LeakIX/Censys/Expanse) en el catálogo de bad-bots; respeta la selección del admin | 2026-06-30 |
| 0074 | Fix bad-bots.conf: entrecomillar patrones con espacios ("Silvy X Ran") que rompían el map de nginx (nginx -t fallaba → no recargaba); regenera y recarga | 2026-06-30 |
| 0075 | El catálogo global de bots ahora SÍ aplica a los vhosts nginx (antes el map $bad_bot no lo leía nadie): if ($bad_bot) return 444 en cada server + crea bad-bots.conf base + regenera vhosts | 2026-06-30 |
| 0076 | Fix: cmd_regenerate_all_vhosts generaba vhost web a dominios solo-correo/DNS (mail_dns_only) → public_html inexistente → configtest Apache fallaba y tumbaba la regeneración de TODOS. Limpia los vhosts ya creados | 2026-06-30 |
| 0077 | Cachear peso en disco de los dominios en BD (la lista hacía du en vivo por cada uno → lenta); refresco 2/día en background + botón por dominio. Primer cálculo | 2026-06-30 |
| 0078 | Quitar jail fail2ban relay redundante: el relay denied es spam distribuido (fail2ban no puede); ya lo cubre CrowdSec (postfix-relay-denied) | 2026-07-01 |
| 0079 | SSH + fail2ban estricto: bantime.increment global (baneo escalado x2 hasta 4 semanas para reincidentes) + jail sshd maxretry 3/findtime 30m/bantime 12h + sshd MaxAuthTries 3/LoginGraceTime 20 | 2026-07-01 |
| 0080 | fail2ban dbpurgeage = 5w (fail2ban.local): el historial de reincidencias se purgaba cada 1d y el escalado de 0079 nunca llegaba a semanas; ahora persiste > maxtime | 2026-07-01 |
| 0081 | Protección anti fuerza bruta WordPress por dominio (xmlrpc 444 + rate-limit wp-login 3/min); crea columnas + protege los dominios bajo ataque (deja cronicasliterarias.es sin proteger para validar el aviso) | 2026-07-01 |
| 0082 | Cache de ataques WP en BD (wp_xmlrpc_hits/wp_wplogin_hits, ventana 24h, cron 3h) para la tabla admin del tab WordPress en Seguridad; primer análisis al aplicar | 2026-07-01 |
| 0083 | postscreen (portero anti-bot) en SMTP 25: corta bots por comportamiento (pregreet/pipelining/basura) antes de sondear buzones; sin DNSBL (RBL las hace Rspamd vía unbound); validación+auto-reversión | 2026-07-01 |
| 0085 | Plugins webmail Roundcube: markasjunk (botón Spam/No-spam, mueve a Junk→lo aprende el imapsieve), zipdownload, archive, attachment_reminder | 2026-07-01 |
| 0084 | uvicorn --limit-max-requests 500→50000 y RestartSec 10→2 en svqpanel.service: el worker se reciclaba cada pocos minutos por el polling del dashboard y el corte de ~14s hacía que el frontend mostrara "la API no responde (no es JSON)" sin motivo | 2026-07-01 |
| 0086 | Zona horaria por defecto del webmail (Roundcube) = Europe/Madrid: sin esto usaba 'auto' (UTC) y las fechas salían 1-2h atrasadas; el usuario puede sobreescribirla en Ajustes | 2026-07-01 |
| 0087 | real_ip de Cloudflare en nginx (set_real_ip_from + CF-Connecting-IP): sin esto nginx veía la IP de CF y no la real → el rate-limit por IP (fuerza bruta wp-login) era esquivable y daba falsos positivos, y fail2ban/CrowdSec baneaban a Cloudflare. Escribe conf.d global + cron mensual de rangos | 2026-07-01 |
| 0088 | Cierra el bypass //xmlrpc.php (el bloqueo `location = /xmlrpc.php` era match exacto y NO normaliza barras: //xmlrpc.php se colaba y arrancaba WordPress, ~18k hits/min tumbando la CPU) → regex `~ ^/+xmlrpc\.php` y `~ ^/+wp-login\.php`; regenera todos los vhosts. Y activa la jail fail2ban nginx-limit-req (estaba enabled=false) para banear al que floodea wp-login (429) | 2026-07-01 |
| 0089 | CrowdSec estaba CIEGO ante las webs de clientes (solo leía /var/log/nginx|apache2, no /home/*/web/*/logs) → no paraba la fuerza bruta DISTRIBUIDA a wp-login (decenas de IPs bajo el umbral del rate-limit por IP). Añade acquisition con los access.log de los dominios → sus escenarios http-* banean por reputación. Y bloquea /.git/ /.env /.svn en el generador de vhosts (regenera todos) | 2026-07-01 |
