<template>
  <div v-if="visibleAlerts.length" class="mail-alerts">
    <div
      v-for="a in visibleAlerts"
      :key="a.id"
      class="mail-alert"
      :class="a.kind">
      <div class="ma-icon">
        <i class="bi" :class="a.kind === 'wrong_username' ? 'bi-person-x' : 'bi-shield-lock'"></i>
      </div>

      <div class="ma-body">
        <div class="ma-title">
          <template v-if="a.kind === 'wrong_username'">
            Una cuenta inexistente está intentando conectarse:
            <strong>{{ a.account }}</strong>
          </template>
          <template v-else>
            Posible contraseña incorrecta en
            <strong>{{ a.account }}</strong>
          </template>
        </div>

        <p class="ma-text">
          <template v-if="a.kind === 'wrong_username'">
            Un dispositivo intenta entrar por {{ a.protocol_label }} con un usuario
            que <strong>no existe</strong> en tu dominio
            ({{ a.failures }} intentos). Seguramente tienes mal escrito el nombre
            de usuario en algún programa de correo.
            <template v-if="a.suggestions && a.suggestions.length">
              Cuentas reales: <strong>{{ fullAccounts(a) }}</strong>.
            </template>
          </template>
          <template v-else>
            Uno de tus dispositivos está fallando el acceso por {{ a.protocol_label }}
            de forma repetida ({{ a.failures }} intentos). Suele pasar tras cambiar
            la contraseña y no actualizarla en el móvil u ordenador.
          </template>
        </p>

        <div class="ma-devices" v-if="a.devices && a.devices.length">
          <span class="ma-devices-lbl">Origen:</span>
          <span v-for="(d, i) in a.devices" :key="i" class="ma-device" :title="d.ip">
            <i class="bi bi-router"></i>
            {{ d.geo || d.ip }}<span class="ma-hits"> · {{ d.hits }} intentos</span>
          </span>
        </div>

        <div class="ma-foot">
          <span v-if="a.at_risk" class="ma-risk">
            <i class="bi bi-exclamation-triangle-fill"></i>
            Puede provocar el bloqueo temporal del acceso desde ese dispositivo.
          </span>
          <span v-if="a.last_attempt" class="ma-last">Último intento: {{ a.last_attempt }}</span>
        </div>
      </div>

      <button class="ma-dismiss" title="Descartar" @click="dismiss(a)">
        <i class="bi bi-x-lg"></i>
      </button>
    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import api from '../services/api'

const LS_KEY = 'svq_mail_alert_dismissed'

export default {
  name: 'MailAuthAlert',
  setup() {
    const alerts = ref([])
    // Mapa { alertId: 'YYYY-MM-DD' } de lo descartado HOY (si vuelve otro día,
    // reaparece porque el problema persiste).
    const dismissed = ref(loadDismissed())

    function today() {
      return new Date().toISOString().slice(0, 10)
    }
    function loadDismissed() {
      try {
        const raw = JSON.parse(localStorage.getItem(LS_KEY) || '{}')
        const t = new Date().toISOString().slice(0, 10)
        // Limpiar entradas de días anteriores.
        const out = {}
        for (const [k, v] of Object.entries(raw)) if (v === t) out[k] = v
        return out
      } catch { return {} }
    }
    function dismiss(a) {
      dismissed.value = { ...dismissed.value, [a.id]: today() }
      localStorage.setItem(LS_KEY, JSON.stringify(dismissed.value))
    }

    const visibleAlerts = computed(() =>
      alerts.value.filter(a => dismissed.value[a.id] !== today())
    )

    function fullAccounts(a) {
      return (a.suggestions || []).map(s => `${s}@${a.domain}`).join(', ')
    }

    onMounted(async () => {
      try {
        const r = await api.mailAccountAlerts()
        alerts.value = r?.alerts || []
      } catch { /* silencioso: es un aviso, no debe romper el dashboard */ }
    })

    return { alerts, visibleAlerts, dismiss, fullAccounts }
  },
}
</script>

<style scoped>
.mail-alerts {
  display: flex;
  flex-direction: column;
  gap: var(--space-3, 12px);
  margin-bottom: var(--space-4, 16px);
}
.mail-alert {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3, 12px);
  padding: var(--space-4, 16px);
  border-radius: var(--radius-lg, 12px);
  border: 1px solid var(--color-warning-border, #f0c36d);
  background: var(--color-warning-soft, #fff8ec);
  position: relative;
}
.mail-alert.wrong_username {
  border-color: var(--color-info-border, #9ec5fe);
  background: var(--color-info-soft, #eff6ff);
}
.ma-icon {
  flex: 0 0 auto;
  font-size: 1.4rem;
  line-height: 1;
  color: var(--color-warning, #b8860b);
}
.mail-alert.wrong_username .ma-icon { color: var(--color-info, #2563eb); }
.ma-body { flex: 1 1 auto; min-width: 0; }
.ma-title { font-weight: 600; margin-bottom: 4px; }
.ma-text {
  margin: 0 0 8px;
  font-size: 0.9rem;
  color: var(--color-text-soft, #555);
  line-height: 1.45;
}
.ma-devices {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  font-size: 0.82rem;
  margin-bottom: 6px;
}
.ma-devices-lbl { color: var(--color-text-soft, #777); }
.ma-device {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--color-surface-2, rgba(0,0,0,.05));
  white-space: nowrap;
}
.ma-hits { color: var(--color-text-soft, #888); }
.ma-foot {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
  font-size: 0.8rem;
}
.ma-risk { color: var(--color-danger, #c0392b); font-weight: 500; }
.ma-last { color: var(--color-text-soft, #999); margin-left: auto; }
.ma-dismiss {
  flex: 0 0 auto;
  background: transparent;
  border: 0;
  cursor: pointer;
  color: var(--color-text-soft, #999);
  padding: 4px;
  border-radius: 6px;
  line-height: 1;
}
.ma-dismiss:hover { background: var(--color-surface-2, rgba(0,0,0,.08)); }
</style>
