"""El wrapper svq-cron-run no debe solapar ejecuciones del mismo cron."""
from scripts.cron_manager import _WRAPPER_CONTENT


def test_wrapper_compila():
    compile(_WRAPPER_CONTENT, "svq-cron-run", "exec")


def test_wrapper_usa_cerrojo_no_bloqueante_por_cron():
    assert "fcntl.LOCK_EX | fcntl.LOCK_NB" in _WRAPPER_CONTENT
    assert "svq-cron-%d-%s.lock" in _WRAPPER_CONTENT
    # Con el cerrojo cogido no se lanza el comando y no se manda correo (exit 0)
    assert 'code, out = 0, "[svq-cron] omitido' in _WRAPPER_CONTENT
