# Tests de SVQPanel

Tests unitarios de las **validaciones y parsers críticos** (seguridad y
configuración). No requieren BD ni servidor: son funciones puras.

## Ejecutar

```bash
# Desde la raíz del repo
pytest
```

## Qué se cubre

| Fichero | Qué valida |
|---------|-----------|
| `test_whitelist.py`  | Parseo de IPs/CIDR de la whitelist del panel (IPv4/IPv6, rangos, entradas inválidas) |
| `test_backup.py`     | Parseo de `DATABASE_URL` para el backup del panel (user/pass/host/puerto/db) |
| `test_validators.py` | Validación de email para Let's Encrypt ACME (rechaza dominios de ejemplo/locales) |

## Cómo añadir más

1. Crea `tests/test_<algo>.py`.
2. Importa la función a probar (añade el `sys.path.insert` del inicio si hace falta).
3. Escribe funciones `test_*` con `assert` o `pytest.raises(...)`.

**Criterio**: prueba funciones puras de validación/parseo, sobre todo las de
seguridad. Evita tests que dependan de root, nginx o la BD real (frágiles y
lentos). Para esos casos, prueba en el servidor con los comandos del CLI.
