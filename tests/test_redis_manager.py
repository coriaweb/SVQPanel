"""
Tests del Redis por dominio (config/unit generadas) y de la protección del
Redis de Rspamd. No tocan el sistema; solo verifican la generación.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import redis_manager as rm


def test_conf_socket_unix_sin_tcp():
    c = rm.render_instance_conf("cliente1", "ejemplo.com", 64)
    # Sin puerto TCP: solo socket unix dentro del dominio, permisos solo-owner
    assert "port 0" in c
    assert "unixsocket /home/cliente1/web/ejemplo.com/private/redis.sock" in c
    assert "unixsocketperm 700" in c


def test_conf_memoria_acotada_y_volatil():
    c = rm.render_instance_conf("cliente1", "ejemplo.com", 64)
    assert "maxmemory 64mb" in c
    assert "maxmemory-policy allkeys-lru" in c
    # Es una caché: sin persistencia (ni RDB ni AOF)
    assert 'save ""' in c
    assert "appendonly no" in c


def test_conf_clamp_del_maxmemory():
    # Por debajo del mínimo → mínimo; por encima del techo → techo
    assert f"maxmemory {rm.MIN_MAXMEMORY_MB}mb" in rm.render_instance_conf("u", "d.com", 1)
    assert f"maxmemory {rm.MAXMEMORY_CAP_MB}mb" in rm.render_instance_conf("u", "d.com", 999999)
    # Valor inválido → default
    assert f"maxmemory {rm.DEFAULT_MAXMEMORY_MB}mb" in rm.render_instance_conf("u", "d.com", "no-num")


def test_unit_corre_como_el_usuario_del_dominio():
    u = rm.render_instance_unit("cliente1", "ejemplo.com", 64)
    assert "User=cliente1" in u
    assert "Group=cliente1" in u
    assert "ExecStart=/usr/bin/redis-server /etc/svqpanel/redis/ejemplo.com.conf" in u


def test_unit_con_techo_de_memoria_y_hardening():
    u = rm.render_instance_unit("cliente1", "ejemplo.com", 64)
    # Segunda capa de contención: MemoryMax = maxmemory + margen de overhead
    assert "MemoryMax=128M" in u
    assert "NoNewPrivileges=true" in u
    # ProtectHome read-only pero con escritura SOLO en el private del dominio
    assert "ProtectHome=read-only" in u
    assert "ReadWritePaths=/home/cliente1/web/ejemplo.com/private" in u


def test_upsert_block_inserta_y_actualiza():
    base = "bind 127.0.0.1 ::1\nprotected-mode yes\n"
    v1 = rm._upsert_block(base, "requirepass clave1")
    assert "requirepass clave1" in v1
    assert v1.startswith(base)  # no toca la config existente
    # Re-aplicar con otra clave debe REEMPLAZAR el bloque, no duplicarlo
    v2 = rm._upsert_block(v1, "requirepass clave2")
    assert "requirepass clave2" in v2
    assert "clave1" not in v2
    assert v2.count(rm._BLOCK_BEGIN) == 1
