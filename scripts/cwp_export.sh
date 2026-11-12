#!/bin/bash
# SVQPanel — exportador de una cuenta de CWP (CentOS Web Panel) para el importador.
#
# Corre EN EL SERVIDOR CWP como root. El panel lo envía por SSH (`bash -s -- USUARIO
# [--config-only] < cwp_export.sh`) y recoge el .tar por la salida estándar: no
# deja ningún fichero en el CWP (los volcados de BD van a un temporal que se borra
# al salir). Solo LEE: no modifica nada del CWP.
#
# Estructura del .tar (la lee scripts/cwp_import.py):
#   cwpmove-USUARIO/
#     cwp/*.tsv            consultas a root_cwp y postfix (salida de `mysql -B`)
#     cwp/shadow           hash del usuario del sistema (SFTP)
#     cwp/dkim/DOM.SEL.key claves privadas de opendkim
#     cwp/sieve/EMAIL/     scripts Sieve del buzón + fichero `active`
#     mysql/DB.create|.sql y mysql.sql (GRANTs con el hash nativo)  ← formato cPanel
#     dnszones/DOM.db      zonas de /var/named                       ← formato cPanel
#     cron/USUARIO         crontab
#     homedir/<docroot>    archivos de cada web (ruta relativa al home)
#     homedir/mail/DOM/ACC maildir de cada buzón
#
# --config-only: sin datos ni volcados (para el análisis; segundos). Los
# directorios se crean vacíos para que el análisis vea qué hay.
# Mensajes y avisos van a stderr (SVQWARN …); por stdout SOLO el tar.

set -u
U="${1:-}"
MODE="${2:-}"
if ! [[ "$U" =~ ^[a-z0-9][a-z0-9_-]{0,31}$ ]]; then
    echo "SVQERR usuario no válido: $U" >&2; exit 2
fi
command -v mysql >/dev/null 2>&1 || { echo "SVQERR no hay cliente mysql" >&2; exit 2; }

Q()  { mysql -N -B -e "$1"; }        # sin cabecera (root vía /root/.my.cnf)
QH() { mysql -B -e "$1"; }           # con cabecera (la lee el importador)
warn() { echo "SVQWARN $*" >&2; }

if [ -z "$(Q "SELECT username FROM root_cwp.user WHERE username='$U'" 2>/dev/null)" ]; then
    echo "SVQNOUSER" >&2; exit 3
fi

HOME_DIR=$(getent passwd "$U" | cut -d: -f6)
[ -n "$HOME_DIR" ] && [ -d "$HOME_DIR" ] || HOME_DIR="/home/$U"

STAGE=$(mktemp -d /root/.svq-cwp-export.XXXXXX) || { echo "SVQERR mktemp" >&2; exit 2; }
trap 'rm -rf "$STAGE"' EXIT
R="$STAGE/cwpmove-$U"
mkdir -p "$R/cwp/dkim" "$R/cwp/sieve" "$R/mysql" "$R/dnszones" "$R/cron" "$R/homedir/mail"

# ── Cuenta, dominios y subdominios ───────────────────────────────────────────
QH "SELECT * FROM root_cwp.user WHERE username='$U'" > "$R/cwp/user.tsv"
QH "SELECT * FROM root_cwp.packages WHERE id=(SELECT package FROM root_cwp.user WHERE username='$U')" \
    > "$R/cwp/package.tsv" 2>/dev/null
QH "SELECT domain, path FROM root_cwp.domains WHERE user='$U'" > "$R/cwp/domains.tsv"
QH "SELECT subdomain, domain, path FROM root_cwp.subdomains WHERE user='$U'" > "$R/cwp/subdomains.tsv"

MAIN=$(Q "SELECT domain FROM root_cwp.user WHERE username='$U'")
DOMS="$MAIN"
DOMS="$DOMS $(Q "SELECT domain FROM root_cwp.domains WHERE user='$U'" | tr '\n' ' ')"
DOMS="$DOMS $(Q "SELECT CONCAT(subdomain,'.',domain) FROM root_cwp.subdomains WHERE user='$U'" | tr '\n' ' ')"
OKDOMS=""
for d in $DOMS; do
    d=$(echo "$d" | tr 'A-Z' 'a-z')
    if [[ "$d" =~ ^[a-z0-9.-]+\.[a-z0-9-]+$ ]]; then OKDOMS="$OKDOMS $d"; else warn "dominio ignorado: $d"; fi
done
IN=$(for d in $OKDOMS; do printf "'%s'," "$d"; done); IN="${IN%,}"
[ -n "$IN" ] || IN="''"

# ── PHP y docroot de cada web (de los vhosts de Apache) + SSL ────────────────
printf "domain\tphp\tdocroot\n" > "$R/cwp/php.tsv"
printf "domain\n" > "$R/cwp/ssl.tsv"
for d in $OKDOMS; do
    conf="/usr/local/apache/conf.d/vhosts/$d.conf"
    ver=""; dr=""
    if [ -f "$conf" ]; then
        ver=$(grep -o 'php-fpm[0-9][0-9]' "$conf" | head -1 | grep -o '[0-9][0-9]')
        dr=$(awk 'tolower($1)=="documentroot"{gsub(/"/,"",$2); print $2; exit}' "$conf")
    fi
    printf "%s\t%s\t%s\n" "$d" "$ver" "$dr" >> "$R/cwp/php.tsv"
    [ -f "/etc/pki/tls/certs/$d.cert" ] && printf "%s\n" "$d" >> "$R/cwp/ssl.tsv"
done

# Docroots a copiar: los del home, sin los anidados (ya van dentro del padre).
DOCROOTS=$( { echo "$HOME_DIR/public_html"; tail -n +2 "$R/cwp/php.tsv" | cut -f3;
              tail -n +2 "$R/cwp/domains.tsv" | cut -f2; tail -n +2 "$R/cwp/subdomains.tsv" | cut -f3; } \
            | sed 's,/*$,,' | grep "^$HOME_DIR/" | sort -u )
TOPROOTS=""
for dr in $DOCROOTS; do
    nested=0
    for t in $TOPROOTS; do case "$dr/" in "$t"/*) nested=1;; esac; done
    [ $nested = 0 ] && [ -d "$dr" ] && TOPROOTS="$TOPROOTS $dr"
done

# Lo que hay en el home FUERA de las webs no se migra: se lista para avisar.
printf "name\tkb\n" > "$R/cwp/extra_dirs.tsv"
for e in "$HOME_DIR"/* "$HOME_DIR"/.[!.]*; do
    [ -e "$e" ] && [ ! -L "$e" ] || continue      # www → public_html es un enlace
    b=$(basename "$e")
    # Restos de CWP/cPanel y del sistema que no son datos del cliente.
    case "$b" in logs|tmp|cache|.cache|.trash|backupcwp|mail|cwp_stats|dnszones|etc|ftp|public_ftp|ssl|\
        .bash*|.cl.selector|.cagefs|.config|.local|.ssh|.pki|.wp-cli|.composer|.npm|.lesshst|.mysql_history|\
        .viminfo|.zshrc|.conf|.contactemail|.cpanel|.cphorde|.htpasswds|.php|.quota-check|.razor|\
        .spamassassin*|.subaccounts) continue;; esac
    inside=0
    for t in $TOPROOTS; do [ "$e" = "$t" ] && inside=1; done
    [ $inside = 1 ] && continue
    printf "%s\t%s\n" "$b" "$(du -sk "$e" 2>/dev/null | cut -f1)" >> "$R/cwp/extra_dirs.tsv"
done

# ── Correo ───────────────────────────────────────────────────────────────────
QH "SELECT domain FROM postfix.domain WHERE domain IN ($IN)" > "$R/cwp/maildomains.tsv"
QH "SELECT username, password, quota, active, domain, local_part, maildir FROM postfix.mailbox WHERE domain IN ($IN)" \
    > "$R/cwp/mailbox.tsv"
QH "SELECT address, goto, active, domain FROM postfix.alias WHERE domain IN ($IN)" > "$R/cwp/alias.tsv"
QH "SELECT alias_domain, target_domain, active FROM postfix.alias_domain WHERE target_domain IN ($IN)" \
    > "$R/cwp/alias_domain.tsv" 2>/dev/null
QH "SELECT * FROM postfix.vacation WHERE domain IN ($IN)" > "$R/cwp/vacation.tsv" 2>/dev/null

MAIL_REL=""
# Solo columnas que nunca van vacías: con IFS=tab, bash junta tabuladores
# seguidos y un campo vacío desplazaría el resto.
while IFS=$'\t' read -r email dom local mdir; do
    src="/var/vmail/${mdir%/}"
    if [ "${mdir%/}" != "$dom/$local" ]; then
        warn "buzón $email: maildir «$mdir» no es $dom/$local; no se copian sus correos"
        continue
    fi
    [ -d "$src" ] || continue
    mkdir -p "$R/homedir/mail/$dom/$local"
    MAIL_REL="$MAIL_REL var/vmail/$dom/$local"
    # Sieve: van FUERA del maildir en SVQPanel; se exportan aparte.
    if [ -d "$src/sieve" ] || [ -e "$src/.dovecot.sieve" ]; then
        sd="$R/cwp/sieve/$email"; mkdir -p "$sd"
        [ -d "$src/sieve" ] && cp -p "$src"/sieve/*.sieve "$sd"/ 2>/dev/null
        if [ -L "$src/.dovecot.sieve" ]; then
            basename "$(readlink "$src/.dovecot.sieve")" > "$sd/active"
        elif [ -f "$src/.dovecot.sieve" ]; then
            cp -p "$src/.dovecot.sieve" "$sd/dovecot.sieve"; echo dovecot.sieve > "$sd/active"
        fi
    fi
done < <(Q "SELECT username, domain, local_part, maildir FROM postfix.mailbox WHERE domain IN ($IN)")

# DKIM (opendkim): KeyTable → "sel._domainkey.dom dom:sel:/ruta/clave.private"
if [ -r /etc/opendkim/KeyTable ]; then
    while read -r _name spec; do
        kd="${spec%%:*}"; rest="${spec#*:}"; sel="${rest%%:*}"; kf="${rest#*:}"
        case " $OKDOMS " in *" $kd "*) [ -r "$kf" ] && cp "$kf" "$R/cwp/dkim/$kd.$sel.key";; esac
    done < <(grep -v '^\s*#' /etc/opendkim/KeyTable)
fi

# ── Bases de datos (prefijo USUARIO_) ────────────────────────────────────────
DBS=$(Q "SHOW DATABASES" | grep -E "^${U}_")
: > "$R/mysql.sql"
# '-' en vez de hash vacío: con IFS=tab un campo vacío desplazaría las columnas.
Q "SELECT User, Host, IF(authentication_string<>'', authentication_string, IF(Password<>'', Password, '-'))
   FROM mysql.user WHERE User LIKE '${U}\\_%' OR User='$U'" |
while IFS=$'\t' read -r du dh dhash; do
    [ "$dhash" = "-" ] && { warn "usuario MySQL $du@$dh sin contraseña"; continue; }
    printf "GRANT USAGE ON *.* TO '%s'@'%s' IDENTIFIED BY PASSWORD '%s';\n" "$du" "$dh" "$dhash" >> "$R/mysql.sql"
done
Q "SELECT User, Host, Db FROM mysql.db WHERE User LIKE '${U}\\_%' OR User='$U'" |
while IFS=$'\t' read -r du dh ddb; do
    ddb=$(printf "%s" "$ddb" | sed 's/\\_/_/g; s/\\%/%/g')
    printf "GRANT ALL PRIVILEGES ON \`%s\`.* TO '%s'@'%s';\n" "$ddb" "$du" "$dh" >> "$R/mysql.sql"
done
for db in $DBS; do
    printf 'CREATE DATABASE `%s`;\n' "$db" > "$R/mysql/$db.create"
    if [ "$MODE" != "--config-only" ]; then
        if ! mysqldump --single-transaction --quick --routines --triggers --events \
                --default-character-set=utf8mb4 --max-allowed-packet=1G "$db" > "$R/mysql/$db.sql" 2>"$STAGE/dump.err"; then
            warn "volcado de $db con errores: $(tail -c 300 "$STAGE/dump.err" | tr '\n' ' ')"
        fi
    fi
done

# ── DNS, cron, contraseña del sistema, tamaños ──────────────────────────────
for d in $OKDOMS; do
    [ -f "/var/named/$d.db" ] && cp "/var/named/$d.db" "$R/dnszones/$d.db"
done
[ -f "/var/spool/cron/$U" ] && cp "/var/spool/cron/$U" "$R/cron/$U"
getent shadow "$U" | cut -d: -f2 > "$R/cwp/shadow"

printf "kind\tname\tkb\n" > "$R/cwp/sizes.tsv"
for t in $TOPROOTS; do printf "web\t%s\t%s\n" "$t" "$(du -sk "$t" 2>/dev/null | cut -f1)" >> "$R/cwp/sizes.tsv"; done
for m in $MAIL_REL; do printf "mail\t%s\t%s\n" "$m" "$(du -sk "/$m" 2>/dev/null | cut -f1)" >> "$R/cwp/sizes.tsv"; done
for db in $DBS; do
    printf "db\t%s\t%s\n" "$db" "$(Q "SELECT COALESCE(ROUND(SUM(data_length+index_length)/1024),0) FROM information_schema.tables WHERE table_schema='$db'")" >> "$R/cwp/sizes.tsv"
done

# Esqueleto (también en modo completo: el tar de datos se superpone).
for t in $DOCROOTS; do [ -d "$t" ] && mkdir -p "$R/homedir/${t#$HOME_DIR/}"; done

# ── Empaquetar a stdout ──────────────────────────────────────────────────────
H="${HOME_DIR#/}"
# Array explícito: en bash 4.2 (CentOS 7) "${vacío[@]}" con set -u da error.
ARGS=(--numeric-owner --ignore-failed-read -cf -
      --transform "s,^${H}/,cwpmove-$U/homedir/,S"
      --transform "s,^var/vmail/,cwpmove-$U/homedir/mail/,S"
      --exclude='var/vmail/*/*/sieve' --exclude='var/vmail/*/*/.dovecot.sieve'
      --exclude='var/vmail/*/*/.dovecot.svbin' --exclude='var/vmail/*/*/.dovecot.lda-dupes'
      --exclude='dovecot.index*' --exclude='dovecot.list.index*' --exclude='dovecot.mailbox.log'
      --exclude='maildirsize' --exclude='dovecot-quota'
      -C "$STAGE" "cwpmove-$U")
if [ "$MODE" != "--config-only" ]; then
    ARGS+=(-C /)
    for t in $TOPROOTS; do ARGS+=("${t#/}"); done
    for m in $MAIL_REL; do ARGS+=("$m"); done
fi
tar "${ARGS[@]}"
rc=$?
# 1 = "un fichero cambió mientras se leía" (correo entrando): no es un fallo.
[ $rc -le 1 ] || { echo "SVQERR tar terminó con código $rc" >&2; exit $rc; }
echo "SVQDONE" >&2
exit 0
