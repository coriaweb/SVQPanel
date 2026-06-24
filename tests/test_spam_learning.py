"""
Tests de la config generada para el aprendizaje de spam (constantes del manager).
No tocan el sistema; solo verifican que la configuración es correcta.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import spam_learning as sl


def test_imapsieve_apunta_a_junk():
    c = sl._IMAP_SIEVE_CONF
    assert "imapsieve_mailbox1_name = Junk" in c
    # learn-spam al entrar en Junk, learn-ham al salir
    assert "learn-spam.sieve" in c
    assert "learn-ham.sieve" in c
    assert "imap_sieve" in c


def test_wrappers_llaman_a_rspamc_learn():
    assert "learn_spam" in sl._PIPE_LEARN_SPAM
    assert "learn_ham" in sl._PIPE_LEARN_HAM
    # vía el controller en localhost (secure_ip), no socket inexistente
    assert "localhost:11334" in sl._PIPE_LEARN_SPAM
    assert "localhost:11334" in sl._PIPE_LEARN_HAM


def test_sieve_scripts_usan_pipe():
    assert "pipe" in sl._SIEVE_LEARN_SPAM
    assert "rspamd-learn-spam.sh" in sl._SIEVE_LEARN_SPAM
    assert "rspamd-learn-ham.sh" in sl._SIEVE_LEARN_HAM


def test_classifier_global_con_autolearn():
    c = sl._RSPAMD_CLASSIFIER
    assert 'backend = "redis"' in c
    assert "autolearn" in c
    # GLOBAL: no debe activar el modo per-user (esas directivas Rspamd).
    assert "per_user = true" not in c
    assert "users {" not in c


def test_milter_headers_incluye_diagnostico():
    c = sl._MILTER_HEADERS
    assert "x-spamd-result" in c   # detalle de reglas (por qué es spam)
    assert "x-spam-level" in c


_RSPAMC_SAMPLE = """Results for command: stat (0.048 seconds)
Messages scanned: 137
Messages with action reject: 1, 0.73%
Messages with action soft reject: 57, 41.61%
Messages with action add header: 12, 8.76%
Messages with action greylist: 7, 5.11%
Messages with action no action: 60, 43.80%
Messages treated as spam: 70, 51.09%
Messages treated as ham: 67, 48.91%
Messages learned: 4
Statfile: BAYES_SPAM type: redis; learned: 4; users: 1
Statfile: BAYES_HAM type: redis; learned: 2; users: 1
"""


def test_parse_rspamc_stat():
    d = sl.parse_rspamc_stat(_RSPAMC_SAMPLE)
    assert d["scanned"] == 137
    assert d["spam"] == 70 and d["ham"] == 67
    assert d["learned_spam"] == 4 and d["learned_ham"] == 2
    assert d["act_reject"] == 1
    assert d["act_soft_reject"] == 57
    assert d["act_add_header"] == 12
    assert d["act_greylist"] == 7
    assert d["act_no_action"] == 60


def test_parse_rspamc_stat_vacio_no_rompe():
    d = sl.parse_rspamc_stat("")
    assert d["scanned"] == 0 and d["learned_spam"] == 0
