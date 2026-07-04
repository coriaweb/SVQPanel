"""
Un dominio importado SOLO como correo y/o DNS (sin el ámbito web) debe quedar
registrado en Dominios como «solo correo/DNS» (mail_dns_only=True, sin vhost ni
pool), igual que el alta manual con esa opción. Si el Domain ya existe (web
importada en la misma pasada, o previa), el helper no debe tocar nada.
"""
import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.models.database import load_all_models
load_all_models()   # resuelve los relationship() en string (User, etc.)

import scripts.hestia_import as hi


def test_registra_dominio_solo_correo_dns():
    owner = MagicMock(id=7)
    db = MagicMock()
    # Ni Domain previo ni MailDomain que enlazar.
    db.query.return_value.filter.return_value.first.return_value = None
    report = hi.ImportReport()

    hi._ensure_mail_dns_only_domain("solo-mail.com", owner, db, report, "1.2.3.4")

    added = db.add.call_args[0][0]
    assert added.domain_name == "solo-mail.com"
    assert added.mail_dns_only is True
    assert added.public_html == ""          # sin web
    assert added.user_id == 7
    assert any(c["type"] == "domain" for c in report.created), \
        "debe reflejarse en el informe de la importación"


def test_no_pisa_un_dominio_existente():
    owner = MagicMock(id=7)
    db = MagicMock()
    # El Domain ya existe (p. ej. importado como web en esta misma pasada).
    db.query.return_value.filter.return_value.first.return_value = MagicMock()
    report = hi.ImportReport()

    hi._ensure_mail_dns_only_domain("con-web.com", owner, db, report, "1.2.3.4")

    db.add.assert_not_called()
    assert report.created == []
