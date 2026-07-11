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
| 0090 | Instala la colección crowdsecurity/wordpress en CrowdSec: solo había http-wordpress-scan (escaneo de rutas), faltaba el escenario de fuerza bruta de LOGIN (http-bf-wordpress_bf) + user-enum + wpconfig. Sin él, el flood distribuido a wp-login no se baneaba aunque CrowdSec ya viera los logs (0089) | 2026-07-01 |
| 0091 | Escenario crowdsecurity/http-bf-wordpress_bf_xmlrpc (fuerza bruta vía XML-RPC): NO viene en la colección wordpress, hay que instalarlo aparte. Complementa el bloqueo de xmlrpc en nginx. (Laravel/PHP a medida no tienen colección propia; los cubren los escenarios genéricos generic-bf/sqli/xss/probing/traversal ya activos) | 2026-07-01 |
| 0092 | CrowdSec ahora lee también los ERROR.log de los dominios (nginx+apache), no solo los access.log (0089). Los 429 del rate-limit (wp-login) quedan en el error.log, no en el access → el escenario nginx-req-limit-exceeded estaba activo pero ciego. Ahora banea al que dispara el rate-limit repetidamente (visto: >1000 hits de 1 IP frenados por 429 pero sin ban) | 2026-07-01 |
| 0093 | memory_limit: php.ini global sube a 256M (techo máximo permitido por override); cada pool de dominio nace con 128M explícito (consumo contenido, solo lo sube quien lo necesite — p.ej. WooCommerce que agotaba los 128M → 500). Regenera pools + recarga FPM | 2026-07-01 |
| 0094 | message_size_limit (tamaño máx. por mensaje de Postfix) sube de 10 MB (default) a 25 MB, como Gmail. Evita rechazos "552 5.3.4 Message size exceeds fixed limit" en correos con adjuntos. Respetuoso: no baja el valor si el admin ya lo subió por encima; ajustable desde el panel (Configuración → Email). Recarga Postfix | 2026-07-01 |
| 0095 | FALLO GRAVE silencioso: /etc/nftables.conf empezaba con `flush ruleset` (borra TODAS las tablas), que destruía la tabla del firewall-bouncer de CrowdSec (ip crowdsec) en cada recarga → el bouncer entraba en bucle netlink y CrowdSec DEJABA de aplicar baneos al firewall (detectaba pero no bloqueaba; llevaba todo el día roto). Fix: flush selectivo (table+delete de inet svqpanel, sin tocar crowdsec) + reinicia el bouncer. + health-check en metrics_scheduler que detecta la desincronización y reinicia el bouncer (cada 10 min) | 2026-07-01 |
| 0096 | La CACHE de página NO funcionaba en modo Apache: nginx hace proxy_pass a Apache:8181 y el generador solo aplicaba fastcgi_cache (que NO funciona con proxy, necesita proxy_cache) → dominios con caché activada no cacheaban (WooCommerce/WP pesado → picos CPU). Fix: proxy_cache_key global + zona proxy_cache_path en modo Apache + directivas proxy_cache en el location de proxy (mismas exclusiones $skip_cache). Y BUG: regenerate_all_vhosts apagaba la caché (fastcgi_cache_enabled default False→None=lee BD, igual que xmlrpc). Regenera vhosts | 2026-07-01 |
| 0097 | SEGURIDAD: el Redis global (backend de Rspamd: Bayes/greylist/ratelimit de correo) escuchaba en 127.0.0.1:6379 SIN contraseña y disable_functions no bloquea sockets → el PHP de cualquier cliente podía hacer FLUSHALL (borrar el Bayes entrenado o vaciar su rate-limit de envío). requirepass (clave en /etc/svqpanel/redis_rspamd.pass) propagado a Rspamd, con verificación | 2026-07-02 |
| 0098 | Redis por dominio (caché de objetos WP/WooCommerce/Laravel): instala phpredis en todas las versiones PHP + garantiza el binario redis-server (sin correo, instancia global apagada). Las instancias se crean desde el panel (tab PHP): unidad systemd propia como el usuario del dominio, socket unix en private/ (0700, solo su PHP), maxmemory acotado, sin persistencia | 2026-07-02 |
| 0099 | Correo IPv6 y PTR: (a) fija la IPv6 de salida GLOBAL (smtp_bind_address6) a la del hostname (con PTR), no una del /64 que elige `ip route get` sin PTR → Gmail rechaza 550 5.7.25; (b) IPv6 dedicada por dominio ahora es OPT-IN: con pref=ipv4 (default) NO se declara el bind6 en master.cf (evita rebotes por IPv6 sin PTR); solo los dominios que eligen ipv6 explícitamente la usan. Reaplica IPs de salida de todos los dominios | 2026-07-02 |
| 0100 | SPF: añade la IPv6 GLOBAL del servidor (por la que sale el correo, con PTR) al registro SPF de las zonas existentes. Antes el SPF solo listaba la IPv6 dedicada del dominio (o ninguna) → el correo que salía por la IPv6 global daba SPF fail en Gmail. Vía backfill_dns_ipv6 | 2026-07-02 |
| 0101 | FIX del 0100: el SPF debe listar la IPv6 por la que SALE el correo (global del servidor, con PTR), NO la IPv6 dedicada/web del dominio (sin PTR → SPF fail). sync_aaaa ya no toca el SPF; lo gobierna la preferencia de salida de correo. Re-ejecuta el backfill corregido | 2026-07-02 |
| 0102 | Bad-bots: bloquea scrapers de IA/SEO agresivos que pasaban sin bloquear (meta-externalagent, PerplexityBot, DataForSeoBot, Scrapy, Timpibot, Bytedance). NO toca Applebot ni facebookexternalhit (SEO Apple + previews WhatsApp/FB/IG). Vía ensure_catalog_bots_blocked (preserva lo que el admin ya tuviera) | 2026-07-02 |
| 0103 | Anti-webshell WordPress: bloquea ejecución de PHP en wp-content/uploads en TODOS los vhosts (nginx Y Apache, en el vhost no en .htaccess que nginx ignora). Regenera los vhosts existentes | 2026-07-03 |
| 0104 | wp-cron de la flota como CronJob del panel (visible en /crons, no crontab crudo): CLI optimize_all_wp_cron limpia crons viejos y los recrea como CronJob por dominio; DISABLE_WP_CRON + cron 5min. Baja picos de CPU. 5 wp-config sin ancla pendientes | 2026-07-03 |
| 0105 | wrapper svq-cron-run silencia la salida de EXITO (solo reemite si exit!=0): un job correcto que imprime (wp-cli "Success:...") generaba un email por ejecucion via MAILTO del cron -> miles de correos del usuario a si mismo, frenados por ratelimit y apilados en cola. El historial del panel sigue registrando todo. Reinstala wrapper + purga cola de correos de cron | 2026-07-04 |
| 0106 | Limpia vhosts de webmail huérfanos: al eliminar un dominio de correo entero quedaba el vhost webmail.{dominio} como placeholder 503 para siempre (llamaba a remove() en vez de destroy()). Código corregido + este update pasa el saneador clean_orphan_vhosts en servidores ya instalados | 2026-07-04 |
| 0107 | HELO propio en transportes de salida con IP dedicada: saludaban con el hostname del servidor → SPF_HELO_SOFTFAIL y PTR↔HELO roto; ahora smtp_helo_name=mail.{dominio} cuando el bind ≠ IP global. Regenera la sección SVQPANEL_SMTP_BIND | 2026-07-04 |
| 0108 | Normaliza los TXT importados de backups (comillas dentro del contenido, trozos "a" "b", \; escapados) que rompían silenciosamente los buscadores del panel (ip6 en SPF al cambiar preferencia, detector de SPF duplicado); resincroniza las zonas afectadas. El importador ya normaliza al importar | 2026-07-04 |
| 0109 | Escalona los wp-cron de la flota: estaban todos en '*/5' → los N WordPress arrancaban su wp-cron en el MISMO minuto (thundering herd) y el load subía a >5. Ahora cada dominio usa un minuto repartido por su id (cada 10 min), sin pico. CLI restagger_wp_cron reescribe CronJob + crontab | 2026-07-04 |
| 0110 | Sube mail_max_userip_connections de Dovecot de 10 a 50 (drop-in 99-svqpanel-limits.conf): el cupo es por buzón+IP y en oficinas tras NAT todos los PCs comparten IP — con 3-4 equipos usando el mismo buzón el default se agota ("Maximum number of connections from user+IP exceeded") | 2026-07-06 |
| 0111 | El correo ya no se duplica en /var/log/syslog (rsyslog mail fuera del catch-all): CrowdSec leía cada fallo de login DOS veces (mail.log + syslog) y baneaba con la mitad de los fallos reales — una oficina entera caía con 2 intentos de un equipo con contraseña caducada | 2026-07-06 |
| 0112 | Los adjuntos por webmail (Roundcube) fallaban con límite ~2 MB aunque el correo admitiera 25 MB: el adjunto pasa por nginx→PHP antes de Postfix y esas capas seguían en su default (PHP upload_max_filesize=2M, nginx client_max_body_size 1 MB). Ahora las 3 capas (nginx+PHP+Roundcube) acompañan al message_size_limit de Postfix + margen base64. CLI sync_webmail_upload_limit | 2026-07-08 |
| 0113 | CrowdSec baneaba al admin legítimo de un WordPress mientras editaba con Elementor: los plugins disparan ráfagas de GET a /wp-json/ que dan 404 (p.ej. Elementor Pro pidiendo rutas de licencia inexistentes) y el escenario http-probing lo cuenta como sondeo. Parser de whitelist que exime /wp-json/ del probing; probes reales (.env, .git, /vendor, /wp-admin/xxx) siguen baneándose (verificado con cscli explain) | 2026-07-08 |
| 0114 | Techo global de memory_limit de PHP 256M→512M (todas las versiones FPM+CLI). Es el cap que el panel permite pedir por dominio; Elementor agota los 128M por defecto al abrir el editor (PHP Fatal: memory exhausted → 500 en admin-ajax.php) y con el cap en 256M no se podía subir más. No baja el valor si ya era mayor. Idempotente | 2026-07-08 |
| 0115 | Techo global de max_execution_time (y max_input_time) de PHP 30s→120s (todas las versiones FPM). El editor de Elementor con packs de widgets tarda >30s en cargar y el default mataba el proceso a mitad → el editor se queda "cargando" y ofrece "modo seguro". nginx (300) y Apache (300) ya cubrían el margen. Es el cap para overrides por dominio. No baja si ya era mayor. Idempotente | 2026-07-08 |
| 0116 | Subidas >1MB fallaban con "Respuesta inesperada del servidor": los vhosts nginx del panel no ponían client_max_body_size → nginx cortaba con 413 (default 1MB) antes de llegar a PHP; el 413 no es JSON y WP mostraba ese mensaje. Además upload_max_filesize/post_max_size global en 2M/8M. Ahora el generador de vhosts inyecta client_max_body_size 64m (regenera todos) + cap PHP a 64M. En Hestia no pasaba porque sí lo ponía | 2026-07-08 |
| 0117 | Los subdominios importados de HestiaCP quedaban con `Domain.ipv6` NULL aunque el importador SÍ les publicaba un AAAA en la zona del padre: el panel los mostraba "sin IPv6" mientras respondían por IPv6. Si la IPv6 del padre cambiara, el panel no actualizaría ese AAAA (cree que no tiene IPv6) y quedaría apuntando a una IP inexistente. `hestia_import.py` ahora guarda `d.ipv6` al publicar el AAAA; este update sincroniza los ya importados copiando el AAAA existente. No inventa registros DNS ni toca BIND/nginx | 2026-07-09 |
| 0118 | Escenario CrowdSec propio (svqpanel/http-444-flood): el catálogo bad-bots de nginx corta a los bots conocidos con 444 (cierra sin responder, no llega a PHP), pero los escenarios http-* de CrowdSec miran 200/403/404, NO el 444 → un bot cortado reconectaba ~1/seg sin fin (visto: IP de AWS con ~2000 hits 444 a /robots.txt). Ahora una IP que acumula muchos 444 se escala a ban de firewall (nftables). Aplica a toda la flota | 2026-07-10 |
| 0119 | En Debian 13 (Dovecot 2.4) el webmail/IMAP daba error SOLO en la bandeja de entrada ("Failed to autocreate mailbox: Permission denied"), mientras Enviados/Archive sí funcionaban. Causa: el paquete Dovecot 2.4 de Debian deja su config MBOX por defecto activa (`mail_driver=mbox`, `mail_inbox_path=/var/mail/%{user}`) conviviendo con la de SVQPanel (maildir): las subcarpetas se leen de `~/` pero el INBOX se busca en `/var/mail/` (inexistente). Comenta la config mbox de Debian en 10-mail.conf. Solo Debian 13+ | 2026-07-11 |
| 0120 | La tarjeta "Antivirus de correo (ClamAV)" salía como "ClamAV no está disponible": el install.sh nunca instalaba el paquete, aunque el panel tiene toda la lógica (antivirus_manager.py). Instala clamav + clamav-daemon + clamav-milter + clamav-freshclam y descarga las firmas. Solo si hay correo (Postfix) | 2026-07-11 |
| 0121 | El correo saliente por IPv6 usaba una IPv6 SLAAC aleatoria del /64 (Postfix sin smtp_bind_address6) sin PTR ni en el SPF → Gmail spf=fail / riesgo de rechazo. NO se apaga IPv6: se FIJA smtp_bind_address6 a la IPv6 del panel (panel_ipv6, la ::1 del rango, la misma que va al SPF). Ahora activar IPv6 en el panel lo fija solo; este update lo aplica a los que ya la tienen. La vista Salud de correo avisa si falta el PTR de esa IPv6 | 2026-07-11 |
