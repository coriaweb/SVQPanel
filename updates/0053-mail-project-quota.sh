#!/bin/bash
# 0053-mail-project-quota.sh
#
# El disco por usuario NO contaba el correo: los maildirs viven en
# /home/{u}/mail con owner vmail, y la cuota de USUARIO va por owner. Activa la
# PROJECT quota de ext4 (project id = uid del usuario) para que el correo cuente,
# y migra los maildirs existentes para que hereden el project. Idempotente.
#
# NOTA: activar el feature 'project'/'quota' interno de ext4 requiere el FS
# DESMONTADO → se hace vía un hook del initramfs en el PRÓXIMO reinicio. Este
# update deja todo preparado e instala el hook; tras reiniciar, las cuotas
# internas (user/group/project) quedan activas y se migran los maildirs.

set -euo pipefail

echo "→ 0053: project quota para que el correo cuente en el disco…"

DEV="$(findmnt -no SOURCE / 2>/dev/null)"
[ -n "$DEV" ] || { echo "  No pude resolver el device de / — abortando."; exit 0; }

# 1) ¿Ya tiene las cuotas internas (User quota inode)? Entonces solo migrar mail.
if tune2fs -l "$DEV" 2>/dev/null | grep -q "User quota inode"; then
    echo "  Cuotas internas ya activas."
else
    echo "  Preparando cuotas internas (se activan en el próximo reinicio)…"
    cp -a /etc/fstab "/etc/fstab.bak.0053.$(date +%s)" 2>/dev/null || true
    # fstab: prjquota (modo interno); quitar usrquota,grpquota externos.
    sed -i -E '/[[:space:]]\/[[:space:]].*ext4/ {s/usrquota,grpquota,prjquota/prjquota/; s/usrquota,grpquota/prjquota/; }' /etc/fstab
    grep -qE '[[:space:]]/[[:space:]].*prjquota' /etc/fstab || \
        sed -i -E '/[[:space:]]\/[[:space:]].*ext4/ s/(defaults|rw)/\1,prjquota/' /etc/fstab

    # Hook initramfs que activa los features con el FS desmontado.
    cat > /etc/initramfs-tools/scripts/init-premount/svq-quota <<'HOOKEOF'
#!/bin/sh
PREREQ=""; prereqs() { echo "$PREREQ"; }
case "$1" in prereqs) prereqs; exit 0;; esac
. /scripts/functions
ROOTDEV=""
for x in $(cat /proc/cmdline); do case "$x" in root=*) ROOTDEV="${x#root=}";; esac; done
case "$ROOTDEV" in PARTUUID=*|UUID=*) ROOTDEV="$(blkid -l -t "$ROOTDEV" -o device 2>/dev/null)";; esac
[ -b "$ROOTDEV" ] || exit 0
tune2fs -l "$ROOTDEV" 2>/dev/null | grep -q "User quota inode" && exit 0
log_begin_msg "SVQPanel: activando cuotas ext4 internas (user/group/project)"
e2fsck -f -y "$ROOTDEV" >/dev/null 2>&1
tune2fs -O ^quota "$ROOTDEV" >/dev/null 2>&1
tune2fs -Q usrquota,grpquota,prjquota "$ROOTDEV" >/dev/null 2>&1
e2fsck -f -y "$ROOTDEV" >/dev/null 2>&1
log_end_msg
exit 0
HOOKEOF
    chmod +x /etc/initramfs-tools/scripts/init-premount/svq-quota
    cat > /etc/initramfs-tools/hooks/svq-quota-bins <<'HOOKEOF'
#!/bin/sh
PREREQ=""; prereqs() { echo "$PREREQ"; }
case "$1" in prereqs) prereqs; exit 0;; esac
. /usr/share/initramfs-tools/hook-functions
copy_exec /usr/sbin/tune2fs /sbin
copy_exec /usr/sbin/e2fsck /sbin
copy_exec /usr/sbin/blkid /sbin
HOOKEOF
    chmod +x /etc/initramfs-tools/hooks/svq-quota-bins
    update-initramfs -u >/dev/null 2>&1 || true
    echo "  ⚠ REINICIO NECESARIO para activar las cuotas (hook initramfs listo)."
    echo "✓ 0053: preparado (reinicia para activar)."
    exit 0
fi

# 2) Cuotas activas → marcar maildirs con el project del usuario (los nuevos
#    heredan; los existentes se reescriben para que cuenten). Idempotente.
systemctl stop dovecot 2>/dev/null || true
for h in /home/*/mail; do
    [ -d "$h" ] || continue
    u=$(basename "$(dirname "$h")")
    uid=$(id -u "$u" 2>/dev/null) || continue
    cd "/home/$u" || continue
    smp=$(find mail -type f 2>/dev/null | head -1)
    if [ -n "$smp" ] && lsattr -p "$smp" 2>/dev/null | grep -qE "^ *$uid "; then
        continue   # ya migrado
    fi
    [ -d mail_rebuild ] && rm -rf mail_rebuild
    mkdir mail_rebuild
    chattr -p "$uid" +P mail_rebuild 2>/dev/null || true
    if rsync -aHAX --numeric-ids mail/ mail_rebuild/ 2>/dev/null; then
        mv mail "mail_old_pjq_$$" && mv mail_rebuild mail
        chown -R vmail:vmail mail 2>/dev/null || true
        rm -rf "mail_old_pjq_$$" 2>/dev/null || true
        echo "  ✓ correo de $u marcado en project quota"
    else
        rm -rf mail_rebuild
        echo "  ⚠ no se pudo migrar el correo de $u"
    fi
done
systemctl start dovecot 2>/dev/null || true

echo "✓ 0053: correo contabilizado en el disco"
exit 0
