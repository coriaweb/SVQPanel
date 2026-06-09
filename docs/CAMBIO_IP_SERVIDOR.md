# Cambiar la IP principal del servidor

Herramienta para migrar la IPv4 principal del servidor cuando, por ejemplo, tu
proveedor te asigna una IP nueva. Propaga el cambio en cascada por todo el panel
y (opcionalmente) reconfigura la red del sistema operativo.

> ⚠️ **OPERACIÓN DE RIESGO.** Solo por SSH como root. Lee TODO antes de ejecutar.

## ⚠️ Riesgos (léelos)

- Si reconfiguras la red del SO y la IP nueva **NO está enrutada por tu
  proveedor**, el servidor queda **INCOMUNICADO** (pierdes SSH).
- Los dominios **dejan de resolver** hasta que propague el DNS (depende del TTL
  de cada registro: minutos u horas).
- El **correo** puede verse afectado: el PTR (DNS inverso) lo gestiona tu
  proveedor, y el SPF apunta a la IP.
- **TEN A MANO la consola KVM/VNC de tu proveedor** como plan B para recuperar
  acceso si algo sale mal.
- Hazlo en una **ventana de mantenimiento**.

## Red de seguridad

- Antes de tocar nada se hace **backup** de: config de red del SO, tablas de la
  BD (settings/domains/dns_records) y zonas BIND. En `/var/lib/svqpanel/ip-migration/`.
- Si reconfiguras la red del SO, se programa una **auto-reversión**: si no
  ejecutas `--confirm` en N minutos (10 por defecto), el servidor vuelve solo a
  la IP vieja. Así, si pierdes acceso, lo recuperas esperando.

## Casos de uso

### Caso A — El proveedor YA cambió la IP (solo propagar) — RECOMENDADO
La red del SO ya tiene la IP nueva; solo hay que propagarla al panel/DNS/vhosts.
**Sin riesgo de incomunicar** (no toca la red):

```bash
python -m api.cli change_server_ip <IP_vieja> <IP_nueva> --no-os-network
```

### Caso B — Cambiar también la red del SO
El panel reconfigura Netplan con la IP nueva (PELIGROSO):

```bash
python -m api.cli change_server_ip <IP_vieja> <IP_nueva>
# … aplica, y programa auto-reversión en 10 min …
# COMPRUEBA que sigues teniendo acceso por la IP nueva y entonces:
python -m api.cli change_server_ip --confirm
```

Si algo va mal: **no confirmes** (volverá sola), o fuerza el rollback:

```bash
python -m api.cli change_server_ip --rollback
```

## Opciones

| Opción | Qué hace |
|--------|----------|
| `--dry-run` | Muestra qué cambiaría (conteo de registros) sin tocar nada |
| `--no-os-network` | Propaga BD/DNS/vhosts pero NO toca la red del SO (seguro) |
| `--revert-timeout N` | Minutos para la auto-reversión de red (default 10) |
| `--confirm` | Hace firme un cambio en curso (cancela la auto-reversión) |
| `--rollback` | Revierte el último cambio (red + BD + zonas) desde el backup |
| `--yes` | No preguntar (automatización). MUY peligroso, evítalo |

## Qué se actualiza

- `settings.server_ipv4` (la IP global del panel)
- `domains.ipv4` (IP por dominio)
- `dns_records` (registros A cuyo valor era la IP vieja)
- Zonas BIND (se regeneran desde la BD, con el serial subido para que propague)
- vhosts nginx (se regeneran)
- Red del SO (Netplan `99-svqpanel-ip.yaml`, prioridad sobre cloud-init) — solo
  sin `--no-os-network`

## Notas

- **Cluster DNS:** si tienes master/slave, las zonas se propagan por AXFR. La IP
  de los propios nameservers se reconfigura aparte (no la toca esta herramienta).
- **DNSSEC / PTR:** el registro inverso (PTR) lo gestiona tu proveedor, no el
  panel — pídeselo para la IP nueva.
- El campo "IP pública del servidor" de Configuración es **solo informativo**
  (no editable): refleja esta IP, pero el cambio se hace con este comando.
