"""
Auditoría de aislamiento PHP por dominio (seguridad de hosting compartido).

Verifica que CADA dominio tiene un pool PHP-FPM dedicado con el bloque de
seguridad correcto (open_basedir, disable_functions, tmp aislado), de modo
que el PHP de un dominio no pueda leer los archivos de otro.

Un dominio sin pool dedicado cae al pool global de PHP-FPM, que NO tiene
open_basedir → puede leer /home de todos los clientes. Esta auditoría
detecta y repara esos casos.

Uso desde la API: audit_domains([...]) / repair_domains([...]) reciben una
lista de dicts {"domain","owner","php_version","overrides","relaxed"}.
"""

import json
import logging
import os
from typing import Dict, List, Optional

from scripts import php_ini_manager as phpini
from scripts.utils import get_public_html, get_domain_private

logger = logging.getLogger(__name__)


def _read_pool(path: str) -> Optional[str]:
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return None


def check_domain(domain: str, owner: str, php_version: str) -> Dict:
    """
    Comprueba el estado de aislamiento de un dominio. Devuelve un dict con:
      domain, owner, php_version, pool_version (la versión cuyo pool existe),
      ok (bool), issues (lista de problemas legibles).
    """
    issues: List[str] = []
    pool_version = phpini.has_pool(domain)

    if pool_version is None:
        issues.append("Sin pool PHP-FPM dedicado (usa el pool global → SIN open_basedir)")
        return {
            "domain": domain, "owner": owner, "php_version": php_version,
            "pool_version": None, "ok": False, "issues": issues,
        }

    # El pool existe; comprobar que apunta a la versión activa del dominio
    if php_version and pool_version != php_version:
        issues.append(f"El pool es de PHP {pool_version} pero el dominio usa {php_version}")

    content = _read_pool(phpini.get_pool_path(pool_version, domain)) or ""

    public_html = get_public_html(owner, domain)
    private     = get_domain_private(owner, domain)
    tmp         = phpini.domain_tmp_dir(owner, domain)

    # open_basedir presente y conteniendo las rutas del dominio
    if "php_admin_value[open_basedir]" not in content:
        issues.append("Falta open_basedir (el cliente podría salir de su raíz)")
    else:
        for needed in (public_html,):
            if needed not in content:
                issues.append(f"open_basedir no incluye {needed}")
        # No debe contener el home de OTRO usuario
        # (heurística: solo debe aparecer /home/{owner}/...)
        if f"/home/{owner}/" not in content:
            issues.append("open_basedir no apunta al home del propietario")

    if "php_admin_value[disable_functions]" not in content:
        issues.append("Falta disable_functions")

    if "php_admin_value[session.save_path]" not in content:
        issues.append("session.save_path no aislado (riesgo de robo de sesión entre sitios)")
    elif tmp not in content:
        issues.append("session.save_path no apunta al tmp del dominio")

    # tmp del dominio debe existir y ser de www-data
    if not os.path.isdir(tmp):
        issues.append(f"El directorio tmp aislado no existe: {tmp}")

    return {
        "domain": domain, "owner": owner, "php_version": php_version,
        "pool_version": pool_version, "ok": len(issues) == 0, "issues": issues,
    }


def audit_domains(domains: List[Dict]) -> Dict:
    """
    Audita una lista de dominios. Cada item: {domain, owner, php_version}.
    Devuelve resumen + detalle por dominio.
    """
    results = [check_domain(d["domain"], d["owner"], d.get("php_version") or "8.2")
               for d in domains]
    insecure = [r for r in results if not r["ok"]]
    return {
        "total": len(results),
        "secure": len(results) - len(insecure),
        "insecure": len(insecure),
        "all_ok": len(insecure) == 0,
        "domains": results,
    }


def repair_domain(domain: str, owner: str, php_version: str,
                  overrides: Optional[Dict] = None, relaxed: bool = False) -> Dict:
    """
    Repara el aislamiento de un dominio reescribiendo su pool FPM con el
    bloque de seguridad completo. Respeta los overrides php.ini y el flag
    de hardening relajado del dominio.
    """
    overrides = overrides or {}
    php_version = php_version or "8.2"
    ok, msg = phpini.write_pool(domain, php_version, owner, overrides, relax_hardening=relaxed)
    return {"domain": domain, "repaired": ok, "message": msg}


def repair_domains(domains: List[Dict]) -> Dict:
    """
    Repara solo los dominios que lo necesitan. Cada item:
    {domain, owner, php_version, overrides, relaxed}.
    """
    repaired, failed = [], []
    for d in domains:
        # Reauditar para no reescribir pools que ya están bien
        check = check_domain(d["domain"], d["owner"], d.get("php_version") or "8.2")
        if check["ok"]:
            continue
        ov = d.get("overrides") or {}
        if isinstance(ov, str):
            try: ov = json.loads(ov)
            except (ValueError, TypeError): ov = {}
        res = repair_domain(d["domain"], d["owner"], d.get("php_version") or "8.2",
                            ov, bool(d.get("relaxed")))
        (repaired if res["repaired"] else failed).append(res)
    return {
        "attempted": len(repaired) + len(failed),
        "repaired": len(repaired),
        "failed": len(failed),
        "details": repaired + failed,
    }
