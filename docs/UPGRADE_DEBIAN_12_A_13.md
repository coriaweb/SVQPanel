# Actualizar Debian 12 → Debian 13 sin romper SVQPanel

Procedimiento para subir el **sistema operativo** de un servidor SVQPanel ya
instalado de **Debian 12 (bookworm)** a **Debian 13 (trixie)**.

> ⚠️ Esto NO es una actualización del panel (`update.sh`). Es un **dist-upgrade
> del SO completo**, una operación delicada y potencialmente irreversible. Se
> hace **a mano por SSH**, nunca por cron ni desde el botón del panel.

## Instalaciones nuevas

No necesitan nada de esto: `install.sh` ya detecta Debian 13 y elige los repos
`trixie` automáticamente. A partir de ahora, **exige Debian 13 para nuevos
servidores** (Debian 12 queda solo como origen de upgrade).

## Antes de empezar (innegociable)

1. **Snapshot del VPS** desde el panel de tu proveedor. Es el único "deshacer"
   real si el dist-upgrade falla a mitad.
2. Ten a mano el **acceso a consola/rescate** del VPS (si se cae la red SSH).
3. Avisa a los clientes: habrá **unos minutos de corte** de servicios.

## Cómo se ejecuta

```bash
# Por SSH, como root, en el servidor:
bash /opt/svqpanel/scripts/dist_upgrade_debian13.sh
```

El script va por **7 fases** y es **reanudable**: si se corta (o reinicias el
server a mitad), vuelve a lanzarlo y retoma desde la última fase completada.
Para forzar desde una fase concreta:

```bash
bash /opt/svqpanel/scripts/dist_upgrade_debian13.sh --from 4
```

Recomendado lanzarlo dentro de `tmux`/`screen` para que no se corte si se cae el
SSH:

```bash
tmux new -s upgrade
bash /opt/svqpanel/scripts/dist_upgrade_debian13.sh
# (Ctrl-b d para desconectar; 'tmux attach -t upgrade' para volver)
```

## Qué hace cada fase

| Fase | Acción |
|------|--------|
| **0** | Pre-flight: comprueba Debian 12, ≥5GB libres, panel sano. Exige confirmar el snapshot. |
| **1** | Backup completo: `pg_dumpall` (PostgreSQL) + `mariadb-dump` (clientes) + tar de `/etc/svqpanel`, nginx, apache, php, postfix, dovecot, bind, nftables, fail2ban y los `sources.list`. Queda en `/root/svqpanel-distupgrade-backup/<fecha>/`. |
| **2** | Pone Debian 12 al día (`full-upgrade` dentro de bookworm) antes de saltar. |
| **3** | Reapunta **todos** los repos propios `bookworm → trixie`: Debian base, PGDG (PostgreSQL), Sury (PHP), nginx.org, MariaDB y Rspamd (este se queda en bookworm si trixie aún no existe, igual que en `install.sh`). |
| **4** | El salto: `apt full-upgrade` a trixie con `--force-confold` (conserva nuestras configs ante conflictos). Pide confirmación. |
| **5** | **Recrea el venv** de `/opt/svqpanel/venv` contra el Python de trixie (el venv viejo apunta a un intérprete que ya no existe) y reinstala `requirements.txt`. |
| **6** | Reinstala los pools PHP-FPM (`python -m api.cli migrate_php_pools --force`) y reinicia la pila de servicios. |
| **7** | Post-flight: valida que el SO es 13, que `panel_db` es accesible, que svqpanel/nginx/postgresql están activos, que la API responde en `:8001` y que PHP-FPM corre. |

Al terminar sin incidencias, recomienda un `reboot` para cargar el kernel nuevo.

## Por qué PostgreSQL NO es un problema en este upgrade

Aunque PostgreSQL es lo más sensible en un dist-upgrade, en SVQPanel ya usamos
el **repo PGDG** con el metapaquete `postgresql` (PG18). Ese cluster es
independiente del codename de Debian: el dist-upgrade **no lo toca**. El script
solo reapunta el `.list` a `trixie-pgdg` para futuras actualizaciones de
paquetes. Si en el futuro PGDG saltara de major, se migraría con
`pg_upgradecluster` (ver el patrón en `updates/0002-postgresql-pgdg-18.sh`).

## Incidencias reales encontradas (upgrade del 2026-06-27)

El primer upgrade real (servidor de producción con 10 dominios) destapó tres
cosas que el script ahora maneja solo:

1. **Dovecot 2.4 (cambio mayor de sintaxis).** trixie trae Dovecot 2.4, que
   renombró/eliminó ajustes de 2.3. Su post-install **aborta el full-upgrade** si
   la config vieja no arranca. El script ahora migra la config **antes** de que
   apt configure dovecot-core (`migrate_dovecot_24_config`):
   - `disable_plaintext_auth = no` → `auth_allow_cleartext = yes`
   - `passdb {}/userdb {}` → `passdb passwd-file {}` / `userdb passwd-file {}`
     con `passwd_file_path` y `default_password_scheme`
   - `mail_location = maildir:~/` → `mail_driver = maildir` + `mail_path = ~/`
   - SNI por dominio: `ssl_cert = <` / `ssl_key = <` →
     `ssl_server_cert_file` / `ssl_server_key_file`
   - Los dropins con bloques `plugin {}` (quota, spam-learn, spam-junk) se
     **neutralizan** (`.disabled-trixie`): el correo básico (IMAP/POP3/SMTP/SNI)
     funciona; quota y auto-aprendizaje de spam se readaptan aparte a 2.4.

2. **Rspamd.** En la fase 3 se deja en bookworm por precaución, pero sus paquetes
   bookworm **chocan** con las libs de trixie (`libicu72`, `libbinutils`) y el
   full-upgrade lo **elimina**. Tras el salto, el script reapunta Rspamd a
   **trixie** (sí tiene repo trixie) y lo reinstala si falta.

3. **PHP.** Sury en trixie ya no trae 8.3 y añade 8.5. Verifica que ningún
   dominio quede en una versión ausente: `migrate_php_pools --force` (fase 6)
   regenera los pools. En el upgrade real los dominios usaban 7.4/8.2/8.4/8.5,
   todas presentes — sin huérfanos.

> ✅ **RESUELTO** (v0.143.x): los generadores de config del panel detectan la
> versión de Dovecot (`scripts/dovecot_version.py`) y emiten la sintaxis 2.3 o
> 2.4 según corresponda — `install_mail.sh` (passdb/userdb, auth_allow_cleartext,
> mail_driver/mail_path, quota driver=count), `spam_learning.py` (IMAPSieve con
> `mailbox{}`/`imapsieve_from{}`/`sieve_script{}`), `dovecot_spam_sieve.py`
> (spam→Junk con `sieve_script type=before`) y `mail_tls_manager.py` (SNI con
> `ssl_server_cert_file/key_file`). El `updates/0062-dovecot-24-config.sh`
> regenera la config a 2.4 en servidores ya actualizados (no-op en Dovecot 2.3).
> Quota de correo y aprendizaje de spam quedan **reactivados**.

## Si algo va mal

- Revisa el log: `/var/log/svqpanel-distupgrade.log`.
- El backup de datos está en `/root/svqpanel-distupgrade-backup/<fecha>/`.
- Si un servicio concreto no arranca, mira su `journalctl -u <servicio>`.
- Si el sistema queda inservible: **restaura el snapshot** del proveedor. Es la
  razón por la que la fase 0 lo exige.

## Notas

- Rspamd: si tras reapuntar a trixie `apt update` se queja, vuelve a poner
  `bookworm` en `/etc/apt/sources.list.d/rspamd.list` (es compatible).
- `certbot` no se ve afectado: va por snap (inmune al dist-upgrade).
- Las versiones de Dovecot/Postfix/BIND9 cambian de major en trixie; el
  `--force-confold` conserva nuestras configs, pero conviene revisar los logs de
  correo y DNS tras el upgrade.
