# Brief para la web (motor Laravel) — Ventajas diferenciales de SVQPanel

> **Objetivo:** generar/actualizar la sección de "Características" o "Por qué SVQPanel"
> de la web. Tono **comercial pero técnico** (el público entiende de hosting:
> revendedores, agencias, desarrolladores). Español. El gancho: **mostrar que
> SVQPanel trae de serie cosas que cPanel/Plesk/Hestia/CWP no traen o cobran aparte**.
>
> Cómo usar este documento: cada bloque trae **(a)** el titular sugerido, **(b)** el
> beneficio para el cliente en 1-2 frases (esto es lo que va en la web), y **(c)** el
> detalle técnico (para tooltips, "leer más" o la tabla comparativa). No copiar el
> detalle técnico tal cual en el hero: usarlo para dar credibilidad.

---

## 0. Mensaje principal (hero)

**Titular:** El panel de hosting que nace seguro, rápido y listo para el futuro.

**Subtítulo:** IPv6 nativo, antispam que aprende solo, aislamiento real entre clientes
y blindaje anti-abuso de serie. Sin módulos de pago, sin sorpresas.

**Tres claims cortos para destacar arriba:**
- 🛡️ **Seguridad por defecto** — cada web aislada, antispam que aprende, anti-hackeo.
- ⚡ **Rendimiento moderno** — HTTP/3, FastCGI cache, Brotli/gzip, PHP afinado por sitio.
- 🌐 **Preparado para el futuro** — IPv6 de verdad en web, correo y DNS.

---

## 1. Correo: antispam que de verdad para el spam

### 1.1 Antispam con aprendizaje automático (Bayes + autolearn)
- **Beneficio:** El filtro **aprende de tus correos**: cuando tú o un cliente movéis un
  mensaje a la carpeta de spam, el sistema lo recuerda y empieza a frenar correos
  parecidos. Cuanto más se usa, mejor protege. Adiós a la bandeja llena de spam.
- **Técnico:** Rspamd con clasificador Bayes (backend Redis) + autolearn automático.
  Entrena vía IMAPSieve: mover a/desde la carpeta *Junk* dispara `learn_spam`/`learn_ham`.
  Funciona desde **cualquier cliente** (Roundcube, Thunderbird, Apple Mail) y tanto al
  **mover** el correo como al **marcarlo** con el botón de basura. Bayes global del
  servidor: lo que aprende de un buzón mejora el filtro para todos. Panel de salud del
  antispam en el admin (escaneados, spam/ham, aprendidos, acciones).
- **Diferencial:** cPanel/Hestia/CWP traen SpamAssassin/Rspamd pero **sin entrenamiento
  configurado** — el Bayes viene vacío y nunca aprende salvo que un experto lo monte. En
  SVQPanel funciona desde el primer día.

### 1.2 Blindaje anti-abuso: límite de envío no autenticado
- **Beneficio:** Si una web de un cliente es hackeada, **no podrá mandar miles de spam**
  desde tu servidor. Esto protege la reputación de tu IP y evita que acabes en listas
  negras por culpa de un sitio comprometido de un tercero.
- **Técnico:** Límite estricto (por defecto 10 correos/hora) al correo NO autenticado
  que sale de scripts PHP/`mail()` o localhost, por usuario de sistema, aplicado en
  Rspamd. El correo autenticado real (clientes con SMTP) tiene su límite normal por
  buzón. Estrategia: empujar a los clientes a configurar SMTP correctamente.
- **Diferencial:** la mayoría de paneles dejan `mail()` de PHP sin tope → un solo
  WordPress hackeado tumba la reputación de todo el servidor. Nosotros lo cerramos de serie.

### 1.3 IP de salida por dominio (IPv4 e IPv6)
- **Beneficio:** Cada dominio puede enviar correo desde **su propia IP**, igual que los
  grandes paneles, para máxima entregabilidad y reputación independiente.
- **Técnico:** `sender_dependent` en Postfix + `smtp_bind_address`/`smtp_bind_address6`.
  Toggle por dominio para elegir IPv4 o IPv6 de salida, con preferencia IPv6.

### 1.4 Correo seguro y compatible de fábrica
- **Beneficio:** Tus clientes configuran el correo en 2 clics y todo va cifrado.
- **Técnico:** SMTPS (465, SSL/TLS directo) **y** submission (587, STARTTLS); IMAP 993/143;
  TLS por dominio con SNI (cada `mail.dominio` presenta su propio certificado);
  autoconfiguración limpia en Thunderbird (carpetas Enviados/Borradores/Spam/Papelera
  visibles con sus roles correctos); DKIM automático por dominio; webmail por dominio.

### 1.5 Rate-limit y herramientas de correo del admin
- **Beneficio:** Control total: ves la cola de correo, quién envía cuánto, y frenas abusos.
- **Técnico:** Límite de envío por buzón/dominio configurable; gestor de cola de correo
  (ver/reencolar/borrar); vista de correo saliente por hora y por buzón; SMTP relay
  (smarthost) global y override por dominio; TLS por SNI; antivirus por dominio (ClamAV).

---

## 2. IPv6 nativo de verdad

### 2.1 IPv6 en web, correo y DNS
- **Beneficio:** Tu hosting está **preparado para el internet actual**. Las webs cargan
  por IPv6 (con preferencia sobre IPv4), el correo viaja por IPv6 y las zonas DNS publican
  los registros IPv6 automáticamente. Muchos ISP ya son IPv6-first: tus webs serán más
  rápidas y accesibles para esos usuarios.
- **Técnico:** Al activar IPv6 en un dominio, el panel añade automáticamente los registros
  **AAAA**, mete la `ip6` en el **SPF**, y los vhosts escuchan en IPv4+IPv6. DNS cluster con
  glue AAAA. Preferencia IPv6 en Postfix. Todo gestionado, sin tocar zonas a mano.
- **Diferencial:** la mayoría de paneles tratan IPv6 como un añadido manual y parcial. En
  SVQPanel es de primera clase y automático en las tres capas (web/correo/DNS).

---

## 3. Aislamiento y seguridad entre clientes

### 3.1 Aislamiento PHP real por dominio
- **Beneficio:** Un cliente **no puede leer los archivos de otro**, ni sus temporales, ni
  ejecutar comandos peligrosos. Si un sitio cae, los demás siguen seguros.
- **Técnico:** Pool PHP-FPM dedicado por dominio (socket propio), corriendo como el usuario
  dueño. `open_basedir` cerrado a su `public_html` + private + tmp propio (**sin `/tmp`
  global compartido**). `disable_functions` (exec/system/…). `upload_tmp_dir`,
  `session.save_path` y `sys_temp_dir` aislados por dominio. Inyectado siempre como
  `php_admin_value` (el cliente no puede sobreescribirlo). Auditoría y reparación desde el panel.

### 3.2 Terminal web con jaula (chroot) por cliente
- **Beneficio:** Acceso a terminal desde el navegador, pero cada cliente **encerrado en su
  propia jaula** — no ve el resto del sistema.
- **Técnico:** ttyd tras nginx en localhost; token de un solo uso (30s); admin como root,
  cliente en jaula chroot por usuario (`su -s /bin/bash`); `/proc hidepid` (no ve procesos
  de otros).

### 3.3 Hardening de TLS y cabeceras
- **Beneficio:** Tus webs sacan **A/A+** en los tests de seguridad SSL de fábrica.
- **Técnico:** Cifrados AEAD con orden de preferencia del servidor, TLS 1.3, algoritmos de
  firma SHA-256+, HSTS, CAA en DNS (issue/issuewild Let's Encrypt), cabeceras de seguridad
  (X-Frame-Options, X-Content-Type-Options, CSP…), bloqueo de bots maliciosos.

### 3.4 Borrado completo y sin huérfanos
- **Beneficio:** Al borrar un cliente, **no queda basura** que comprometa seguridad o consuma
  recursos.
- **Técnico:** Purga total (vhosts, symlinks, pools FPM, zonas DNS, webmail, buzones, BD).
  Saneador de vhosts huérfanos. Recuperación de acceso admin por CLI.

---

## 4. Rendimiento moderno

### 4.1 Stack rápido por defecto
- **Beneficio:** Las webs cargan rápido sin que tengas que configurar nada.
- **Técnico:** HTTP/3 (QUIC), gzip global + cache de navegador para estáticos, FastCGI cache
  por dominio con TTL configurable, nginx desde repo oficial. (Brotli en hoja de ruta.)

### 4.2 Afinado de recursos por dominio y de la base de datos
- **Beneficio:** Ajustas el consumo de RAM/CPU de cada cliente y optimizas la BD sin ser DBA.
- **Técnico:** PHP-FPM por dominio con presets (low/medium/high) y caps del servidor;
  php.ini propio por dominio. Tuner de MariaDB/MySQL (recomendaciones tipo mysqltuner +
  drop-in reversible). Acceso remoto a MySQL por allowlist de IPs (modelo cPanel).

### 4.3 Doble webserver: Nginx solo o Apache+Nginx
- **Beneficio:** Compatibilidad total — soporta `.htaccess` legacy (Apache) o máxima
  velocidad (Nginx puro), tú eliges.
- **Técnico:** Modo Nginx (recomendado) o Apache+Nginx con feature parity (headers, bad bots,
  SSL, IPv6, readonly). Detección automática al crear dominios.

---

## 5. Funciones que enamoran a revendedores y agencias

### 5.1 Autoinstalador de aplicaciones (1 clic)
- **Beneficio:** WordPress, Laravel, Nextcloud, PrestaShop instalados en un clic.
- **Técnico:** Precheck de requisitos PHP antes de instalar. WP Toolkit que detecta y
  gestiona WordPress (plugins/temas, mantenimiento, accesos) vía wp-cli.

### 5.2 Despliegue Git por dominio
- **Beneficio:** Tus clientes despliegan desde Git como en los PaaS modernos.
- **Técnico:** Clone + webhook + releases con rollback + deploy keys. Build aislado por usuario.

### 5.3 Backups serios (incremental + cifrado)
- **Beneficio:** Copias de seguridad reales, eficientes y cifradas, a donde quieras.
- **Técnico:** Motor restic (incremental + deduplicación + cifrado). Destinos local, SFTP o
  S3 (AWS/Backblaze/Wasabi). Password de cifrado por job.

### 5.4 Migración desde HestiaCP
- **Beneficio:** Cámbiate sin perder nada: importa tus backups de Hestia (web, BD, correo, DNS).
- **Técnico:** Importador con preflight + job en background; reutiliza los hashes de contraseña
  (los clientes no tienen que cambiarlas).

### 5.5 DNS en cluster (master/slave)
- **Beneficio:** DNS redundante y profesional para tus dominios.
- **Técnico:** BIND9 master/slave por SSH + TSIG + AXFR; auto-resincronización de zonas
  desfasadas; vista de salud del cluster en vivo.

### 5.6 API + tokens de acceso
- **Beneficio:** Automatiza e integra el panel con tus sistemas.
- **Técnico:** API documentada (Swagger/ReDoc/OpenAPI). Tokens con allowlist de IPs que heredan
  el rol del dueño.

### 5.7 Auto-actualización del panel
- **Beneficio:** El panel se mantiene solo, siempre al día y seguro, sin tu intervención.
- **Técnico:** git pull + migraciones idempotentes (`updates/NNNN`) + rebuild solo si cambió +
  restart. Botón manual o cron diario. Registro de updates aplicados por servidor.

### 5.8 Cambio de IP del servidor sin drama
- **Beneficio:** ¿Migras de IP? Un comando propaga el cambio a todo (BD, DNS, vhosts) con
  backup y reversión automática.
- **Técnico:** CLI `change_server_ip` con backup + auto-reversión por confirmación.

### 5.9 Interfaz moderna (2026)
- **Beneficio:** Un panel bonito y rápido, modo claro/oscuro, que da gusto usar — no la típica
  interfaz de los 2000.
- **Técnico:** Vue 3 + Vite, design tokens, sidebar agrupado y colapsable, code-splitting.

---

## 6. TABLA COMPARATIVA (para la sección "vs otros paneles")

> Marcar con ✅ (incluido de serie), ⚠️ (parcial/manual/de pago) o ❌ (no).
> Ajustar las columnas de la competencia a tu criterio comercial; lo importante es la
> columna de SVQPanel.

| Característica | SVQPanel | cPanel | Plesk | HestiaCP | CWP |
|---|---|---|---|---|---|
| Antispam con **aprendizaje automático** activo de serie | ✅ | ⚠️ | ⚠️ | ⚠️ | ⚠️ |
| **Límite anti-abuso** de `mail()` PHP (web hackeada) | ✅ | ❌ | ⚠️ | ❌ | ❌ |
| **IPv6 nativo** en web + correo + DNS (automático) | ✅ | ⚠️ | ⚠️ | ⚠️ | ⚠️ |
| **Aislamiento PHP** real por dominio (sin /tmp global) | ✅ | ⚠️ | ✅ | ⚠️ | ⚠️ |
| IP de salida de correo **por dominio** (IPv4/IPv6) | ✅ | ✅ | ✅ | ✅ | ⚠️ |
| **HTTP/3** + FastCGI cache + gzip de serie | ✅ | ⚠️ | ⚠️ | ⚠️ | ⚠️ |
| Terminal web **en jaula** por cliente | ✅ | ⚠️ | ⚠️ | ❌ | ❌ |
| Backups **restic** (incremental + cifrado) a S3/SFTP | ✅ | ⚠️ | ⚠️ | ⚠️ | ⚠️ |
| Despliegue **Git** por dominio (releases + rollback) | ✅ | ⚠️ | ✅ | ❌ | ❌ |
| **Migración desde HestiaCP** integrada | ✅ | ❌ | ⚠️ | — | ❌ |
| Tuner de **MariaDB/MySQL** integrado | ✅ | ❌ | ⚠️ | ❌ | ⚠️ |
| Hardening TLS A/A+ + CAA + cabeceras de serie | ✅ | ⚠️ | ⚠️ | ⚠️ | ⚠️ |
| **Auto-actualización** del panel | ✅ | ✅ | ✅ | ⚠️ | ⚠️ |
| Interfaz moderna (Vue 3, claro/oscuro) | ✅ | ⚠️ | ✅ | ⚠️ | ❌ |
| API documentada + tokens con allowlist IP | ✅ | ✅ | ✅ | ⚠️ | ⚠️ |
| **Sin coste de licencia por cuenta** | ✅ | ❌ | ❌ | ✅ | ⚠️ |

> Nota legal/comercial: revisa los ✅/⚠️/❌ de la competencia antes de publicar, porque
> cambian con versiones y planes. Lo verificable y defendible al 100% es la columna de
> SVQPanel. Evita afirmaciones absolutas sobre terceros que no puedas demostrar.

---

## 7. Bloques de cierre (CTA y confianza)

- **Frase de cierre:** "Todo esto, incluido. Sin módulos de pago, sin trucos. Un panel que se
  actualiza solo y nace seguro."
- **Micro-features para iconitos:** PHP 7.4–8.3 · PostgreSQL para el panel · MariaDB para
  clientes · Debian 12/13 · Let's Encrypt automático · DKIM/SPF/DMARC · Fail2ban · WAF de bots.
- **Para revendedores:** límites por usuario, multi-rol (admin/reseller/cliente), una sola API.

---

## 8. Notas para el motor que genere la página

- Priorizar en el "above the fold": **antispam que aprende**, **límite anti-hackeo de correo**,
  **IPv6 nativo** y **aislamiento PHP** — son los 4 que más diferencian y más "duelen" en otros
  paneles.
- Usar el patrón **beneficio primero, tecnicismo en "leer más"**: el titular vende, el detalle
  da credibilidad.
- La tabla comparativa va en su propia sección con ancla (#comparativa), enlazada desde el hero.
- Mantener el tono del proyecto: profesional, directo, sin hipérboles vacías. Cada claim debe
  ser defendible (todos lo son: están implementados y verificados en producción).
