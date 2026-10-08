"""Certificado propio (validación + rutas) y comodines; validación DNS-01 (wildcard)."""
import json
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from scripts import ssl_paths, custom_ssl


# ── utilidades: una CA → intermedio → certificado, como un proveedor real ──
def _key():
    return ec.generate_private_key(ec.SECP256R1())


def _cert(subject_cn, issuer_cert, issuer_key, key, names=None, ca=False, days=(-1, 90)):
    now = datetime.now(timezone.utc)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject_cn)])
    b = (x509.CertificateBuilder()
         .subject_name(subject)
         .issuer_name(issuer_cert.subject if issuer_cert else subject)
         .public_key(key.public_key())
         .serial_number(x509.random_serial_number())
         .not_valid_before(now + timedelta(days=days[0]))
         .not_valid_after(now + timedelta(days=days[1]))
         .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True))
    if names:
        b = b.add_extension(x509.SubjectAlternativeName([x509.DNSName(n) for n in names]), critical=False)
    return b.sign(issuer_key or key, hashes.SHA256())


def _pem(c):
    return c.public_bytes(serialization.Encoding.PEM).decode()


def _kpem(k, password=None):
    enc = (serialization.BestAvailableEncryption(password) if password
           else serialization.NoEncryption())
    return k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, enc).decode()


@pytest.fixture(scope="module")
def pki():
    ca_k = _key(); ca = _cert("CA raíz", None, None, ca_k, ca=True)
    im_k = _key(); im = _cert("Intermedio", ca, ca_k, im_k, ca=True)
    leaf_k = _key()
    leaf = _cert("mi-web.com", im, im_k, leaf_k, names=["mi-web.com", "www.mi-web.com"])
    return {"ca": ca, "ca_k": ca_k, "im": im, "im_k": im_k, "leaf": leaf, "leaf_k": leaf_k}


def test_covers_comodin():
    assert ssl_paths.covers(["*.mi-web.com"], "mail.mi-web.com")
    assert ssl_paths.covers(["*.MI-WEB.com."], "WEBMAIL.mi-web.com")
    assert not ssl_paths.covers(["*.mi-web.com"], "mi-web.com")
    assert not ssl_paths.covers(["*.mi-web.com"], "a.b.mi-web.com")
    assert ssl_paths.covers(["mi-web.com"], "mi-web.com")


def test_valido_con_cadena(pki):
    info = custom_ssl.validate("mi-web.com", _pem(pki["leaf"]), _kpem(pki["leaf_k"]), _pem(pki["im"]))
    assert info["warnings"] == []
    assert info["fullchain"].count("BEGIN CERTIFICATE") == 2
    assert info["fullchain"].startswith(_pem(pki["leaf"]))
    # La cadena también puede venir pegada detrás del certificado
    info2 = custom_ssl.validate("mi-web.com", _pem(pki["leaf"]) + _pem(pki["im"]), _kpem(pki["leaf_k"]))
    assert info2["fullchain"] == info["fullchain"]


@pytest.mark.parametrize("caso,msg", [
    ("clave_ajena", "no corresponde"),
    ("caducado", "caducó"),
    ("futuro", "aún no es válido"),
    ("otro_dominio", "no cubre"),
    ("sin_cadena", "cadena intermedia"),
    ("cadena_mala", "no corresponde a este certificado"),
    ("clave_con_pass", "contraseña"),
    ("basura", "PEM válido"),
])
def test_rechazos(pki, caso, msg):
    leaf, k, chain, dom = _pem(pki["leaf"]), _kpem(pki["leaf_k"]), _pem(pki["im"]), "mi-web.com"
    if caso == "clave_ajena":
        k = _kpem(_key())
    elif caso == "caducado":
        leaf = _pem(_cert("mi-web.com", pki["im"], pki["im_k"], pki["leaf_k"], ["mi-web.com"], days=(-90, -1)))
    elif caso == "futuro":
        leaf = _pem(_cert("mi-web.com", pki["im"], pki["im_k"], pki["leaf_k"], ["mi-web.com"], days=(5, 90)))
    elif caso == "otro_dominio":
        dom = "otra.com"
    elif caso == "sin_cadena":
        chain = ""
    elif caso == "cadena_mala":
        chain = _pem(pki["ca"])        # la raíz no es quien firmó el certificado
    elif caso == "clave_con_pass":
        k = _kpem(pki["leaf_k"], password=b"secreto")
    elif caso == "basura":
        leaf = "esto no es un certificado"
    with pytest.raises(custom_ssl.CertError) as e:
        custom_ssl.validate(dom, leaf, k, chain)
    assert msg in str(e.value)


def test_avisos(pki):
    k = _key()
    sin_www = _cert("mi-web.com", pki["im"], pki["im_k"], k, ["mi-web.com"])
    info = custom_ssl.validate("mi-web.com", _pem(sin_www), _kpem(k), _pem(pki["im"]))
    assert any("www.mi-web.com" in w for w in info["warnings"])
    # Subdominio: el www no aplica
    sub = _cert("tienda.mi-web.com", pki["im"], pki["im_k"], k, ["tienda.mi-web.com"])
    assert custom_ssl.validate("tienda.mi-web.com", _pem(sub), _kpem(k), _pem(pki["im"]),
                               is_subdomain=True)["warnings"] == []
    # Comodín cubre el dominio solo si además lleva el apex
    wc = _cert("*.mi-web.com", pki["im"], pki["im_k"], k, ["*.mi-web.com", "mi-web.com"])
    assert custom_ssl.validate("mi-web.com", _pem(wc), _kpem(k), _pem(pki["im"]))["warnings"] == []
    # Autofirmado: se acepta con aviso (no hay cadena que pedir)
    sk = _key(); ss = _cert("mi-web.com", None, None, sk, ["mi-web.com", "www.mi-web.com"])
    info = custom_ssl.validate("mi-web.com", _pem(ss), _kpem(sk))
    assert info["self_signed"] and any("autofirmado" in w for w in info["warnings"])


def test_resolver_prefiere_el_propio_y_vuelve_a_lets_encrypt(tmp_path, monkeypatch, pki):
    monkeypatch.setattr(ssl_paths, "CUSTOM_ROOT", str(tmp_path / "custom"))
    monkeypatch.setattr(ssl_paths, "LE_ROOT", str(tmp_path / "le"))
    le = tmp_path / "le" / "mi-web.com"
    le.mkdir(parents=True)
    (le / "fullchain.pem").write_text(_pem(pki["leaf"]))
    (le / "privkey.pem").write_text("k")
    assert ssl_paths.source("mi-web.com") == "letsencrypt"

    info = custom_ssl.validate("mi-web.com", _pem(pki["leaf"]), _kpem(pki["leaf_k"]), _pem(pki["im"]))
    custom_ssl.install("mi-web.com", info)
    assert ssl_paths.source("mi-web.com") == "custom"
    assert ssl_paths.cert_paths("mi-web.com")[0].startswith(str(tmp_path / "custom"))
    assert ssl_paths.names_of("mi-web.com") == ["mi-web.com", "www.mi-web.com"]

    from scripts.utils import generate_nginx_config
    v = generate_nginx_config("mi-web.com", "u", "8.4", ssl_enabled=True)
    assert f"ssl_certificate {tmp_path / 'custom' / 'mi-web.com' / 'fullchain.pem'};" in v

    custom_ssl.restore_previous("mi-web.com")    # deshacer: no había propio antes
    assert ssl_paths.source("mi-web.com") == "letsencrypt"
    custom_ssl.install("mi-web.com", info)
    assert custom_ssl.remove("mi-web.com") and ssl_paths.source("mi-web.com") == "letsencrypt"


# ── Rutas ──────────────────────────────────────────────────────────────────
from tests.test_user_admin_protection import db, _add  # noqa: E402,F401


def test_rutas_certificado_propio(db, monkeypatch, tmp_path, pki):
    from fastapi import HTTPException
    from api.models.models_domain import Domain
    from api.routes import ssl as R
    monkeypatch.setattr(ssl_paths, "CUSTOM_ROOT", str(tmp_path / "custom"))
    monkeypatch.setattr(ssl_paths, "LE_ROOT", str(tmp_path / "le"))
    c1 = _add(db, 5, "c1"); c2 = _add(db, 6, "c2")
    db.add(Domain(id=1, user_id=5, domain_name="mi-web.com", php_version="8.4", public_html="/p"))
    db.commit()
    regen = []
    monkeypatch.setattr(R, "_regenerate", lambda d, db: regen.append(d.ssl_enabled))
    monkeypatch.setattr(R, "_rebuild_mail_tls", lambda db: None)

    class _Mgr:
        def get_cert_info(self, name):
            return None
    monkeypatch.setattr(R, "SSLManager", _Mgr)
    body = R.CustomCertRequest(certificate=_pem(pki["leaf"]), private_key=_kpem(pki["leaf_k"]),
                               chain=_pem(pki["im"]))
    with pytest.raises(HTTPException) as e:                      # dominio ajeno
        R.upload_custom_cert(1, body, current_user=c2, db=db)
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:                      # clave que no es
        R.upload_custom_cert(1, R.CustomCertRequest(certificate=body.certificate,
                             private_key=_kpem(_key()), chain=body.chain), current_user=c1, db=db)
    assert e.value.status_code == 400 and not ssl_paths.has_custom("mi-web.com")

    R.upload_custom_cert(1, body, current_user=c1, db=db)
    d = db.get(Domain, 1)
    assert d.ssl_enabled and d.ssl_certificate == "Propio" and ssl_paths.has_custom("mi-web.com")
    assert abs((d.ssl_expires - (datetime.utcnow() + timedelta(days=90))).total_seconds()) < 172800
    with pytest.raises(HTTPException) as e:                      # no se "renueva"
        R.renew_ssl(1, current_user=c1, db=db)
    assert e.value.status_code == 400

    # Si nginx no lo acepta, se deja todo como estaba
    def _falla(d, db):
        if d.ssl_certificate == "Propio":
            raise RuntimeError("nginx -t")
    custom_ssl.remove("mi-web.com"); d.ssl_enabled = False; d.ssl_certificate = None; db.commit()
    monkeypatch.setattr(R, "_regenerate", _falla)
    with pytest.raises(HTTPException) as e:
        R.upload_custom_cert(1, body, current_user=c1, db=db)
    assert e.value.status_code == 422 and not ssl_paths.has_custom("mi-web.com") and not d.ssl_enabled

    # Quitarlo sin Let's Encrypt detrás → sin HTTPS
    monkeypatch.setattr(R, "_regenerate", lambda d, db: None)
    R.upload_custom_cert(1, body, current_user=c1, db=db)
    R.remove_custom_cert(1, current_user=c1, db=db)
    assert not d.ssl_enabled and not d.force_https and not ssl_paths.has_custom("mi-web.com")


# ── Wildcard: reto DNS en la zona del panel ────────────────────────────────
def test_reto_dns_en_la_zona(db, monkeypatch):
    from api.models.models_dns import DnsZone, DnsRecord
    import api.models.database as database
    import api.routes.dns as D
    from scripts import acme_dns
    db.add(DnsZone(id=1, domain_name="mi-web.com", serial=2026100801, is_active=True))
    db.commit()
    monkeypatch.setattr(database, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    pushed = []
    monkeypatch.setattr(D, "_sync_zone_to_bind", lambda z, db: pushed.append(z.serial))
    monkeypatch.setattr(acme_dns, "_served_by_all", lambda db, fqdn, v: True)
    monkeypatch.setattr(acme_dns.time, "sleep", lambda s: None)

    assert acme_dns.can_validate(db, "mi-web.com") and acme_dns.can_validate(db, "*.mi-web.com")
    assert acme_dns.can_validate(db, "tienda.mi-web.com")
    assert not acme_dns.can_validate(db, "otro.com")
    # dominio y *.dominio: dos valores en el MISMO nombre a la vez
    acme_dns.add_challenge("mi-web.com", "valor-A")
    acme_dns.add_challenge("*.mi-web.com", "valor-B")
    txt = lambda: sorted(r.content for r in db.query(DnsRecord).filter(DnsRecord.name == "_acme-challenge"))
    assert txt() == ["valor-A", "valor-B"]
    assert len(pushed) == 2 and pushed[1] > pushed[0]            # serial sube y se publica
    acme_dns.remove_challenge("mi-web.com", "valor-A")
    assert txt() == ["valor-B"]
    acme_dns.remove_challenge("*.mi-web.com", "valor-B")
    assert txt() == []
    with pytest.raises(RuntimeError):
        acme_dns.add_challenge("otro.com", "x")


def test_hook_args():
    from scripts import acme_dns
    a = acme_dns.hook_args()
    assert a[:3] == ["--manual", "--preferred-challenges", "dns"]
    assert "bash /opt/svqpanel/scripts/certbot-dns-hook.sh auth" in a
