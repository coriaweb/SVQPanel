"""
CLI utilitario para SVQPanel.

Uso típico (desde systemd timer):
    /opt/svqpanel/venv/bin/python -m api.cli refresh_ip_lists
"""

import sys
import argparse
import logging
from datetime import datetime, timedelta

from api.models.database import SessionLocal
from api.models.models_security import IpList, SecurityAuditLog
from api.utils import ip_list_fetcher, nftables_helper as nft

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("svqpanel-cli")


def cmd_refresh_ip_lists(force: bool = False) -> int:
    """
    Refresca TODAS las IpList habilitadas (fetch + parse), actualiza estado
    en BD, regenera svqpanel-iplists.nft con todas las activas y recarga
    nftables una sola vez al final.

    El flag --force solo afecta a si imprimimos "no tocaba aún"; siempre
    refetcheamos todas porque necesitamos las entradas para regenerar
    el archivo entero. Si una lista falla, conservamos su última versión
    aceptada en BD (sha256_last) pero queda fuera del archivo regenerado
    esta corrida — la siguiente ejecución reintentará.
    """
    db = SessionLocal()
    try:
        enabled = db.query(IpList).filter(IpList.enabled.is_(True)).all()
        if not enabled:
            logger.info("No hay listas IP habilitadas.")
            content = ip_list_fetcher.regenerate_iplists_nft([])
            ip_list_fetcher.write_iplists_nft(content)
            ok, msg = nft.reload_nftables()
            return 0 if ok else 1

        logger.info(f"Listas habilitadas: {len(enabled)}")

        active_tuples = []
        now = datetime.utcnow()

        for il in enabled:
            due = (
                force
                or il.last_success_at is None
                or now >= il.last_success_at + timedelta(hours=il.refresh_interval_hours)
            )
            logger.info(f"  - {il.name}  due={due}  url={il.url}")

            v4, v6, err = ip_list_fetcher.refresh_one(il)
            db.commit()

            if err == "unchanged":
                logger.info(f"      sha256 sin cambios → refetch para incluir en regeneración")
                # Necesitamos las entradas igualmente; refetch puro sin tocar estado:
                try:
                    text, _ = ip_list_fetcher.fetch_url(il.url)
                    v4, v6, _ = ip_list_fetcher.parse_list_content(text, il.max_entries)
                except Exception as e:
                    logger.warning(f"      refetch falló: {e}; omitiendo de regen esta vuelta")
                    continue
            elif err:
                logger.warning(f"      ERROR: {err}")
                continue

            logger.info(f"      v4={len(v4)} v6={len(v6)}")
            active_tuples.append((il, v4, v6))

        # Regen + reload
        content = ip_list_fetcher.regenerate_iplists_nft(active_tuples)
        ip_list_fetcher.write_iplists_nft(content)

        ok, msg = nft.reload_nftables()
        if not ok:
            logger.error(f"Reload nftables falló: {msg}")
        else:
            logger.info(f"nftables recargado OK ({len(active_tuples)} listas activas)")

        # Audit
        entry = SecurityAuditLog(
            user_label = "cron",
            category   = "iplist",
            action     = "refresh_all",
            target     = f"{len(active_tuples)}/{len(enabled)} listas regeneradas",
            success    = ok,
            error      = None if ok else msg,
        )
        db.add(entry)
        db.commit()
        return 0 if ok else 1

    except Exception as e:
        logger.exception(f"refresh_ip_lists falló: {e}")
        return 2
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(prog="api.cli", description="SVQPanel CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_refresh = sub.add_parser("refresh_ip_lists", help="Refresca listas IP vencidas")
    p_refresh.add_argument("--force", action="store_true", help="Refresca todas, ignorar interval")

    args = parser.parse_args()
    if args.cmd == "refresh_ip_lists":
        sys.exit(cmd_refresh_ip_lists(force=args.force))


if __name__ == "__main__":
    main()
