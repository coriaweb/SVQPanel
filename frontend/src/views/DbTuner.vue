<template>
  <div class="sv-view">
    <div class="dbt-head">
      <div>
        <h2 class="dbt-title"><i class="bi bi-speedometer"></i> Optimización de base de datos</h2>
        <p class="dbt-subtitle">Diagnóstico de MariaDB/MySQL y ajuste de la configuración del servidor</p>
      </div>
      <BaseButton variant="ghost" size="sm" :loading="loading" @click="load">
        <i class="bi bi-arrow-clockwise"></i> Actualizar
      </BaseButton>
    </div>

    <div v-if="loading" class="dbt-loading"><div class="spinner-border spinner-border-sm"></div></div>

    <div v-else-if="!enabled" class="dbt-empty">
      <i class="bi bi-database-x"></i>
      <p>MariaDB no está habilitado en este servidor.</p>
      <small>Instálalo y configura <code>MARIADB_ENABLED=true</code> en el .env del panel.</small>
    </div>

    <div v-else>
      <!-- Resumen de estado -->
      <BaseCard class="dbt-summary" :class="`dbt-summary--${overall}`">
        <div class="dbt-summary-row">
          <div class="dbt-summary-icon">
            <i class="bi" :class="overallIcon"></i>
          </div>
          <div>
            <div class="dbt-summary-title">{{ overallTitle }}</div>
            <div class="dbt-summary-sub">{{ serverVersion }} · {{ recommendations.length }} recomendación(es)</div>
          </div>
        </div>
      </BaseCard>

      <!-- Métricas clave -->
      <div class="dbt-metrics">
        <div v-for="m in metricCards" :key="m.label" class="dbt-metric">
          <div class="dbt-metric-label">{{ m.label }}</div>
          <div class="dbt-metric-value" :class="m.cls">{{ m.value }}</div>
        </div>
      </div>

      <!-- Recomendaciones -->
      <BaseCard title="Recomendaciones" icon="lightbulb">
        <div v-if="!recommendations.length" class="dbt-allok">
          <i class="bi bi-check-circle-fill"></i> Todo en orden. No hay ajustes recomendados ahora mismo.
        </div>
        <div v-else class="dbt-recs">
          <div v-for="(r, i) in recommendations" :key="i" class="dbt-rec" :class="`dbt-rec--${r.level}`">
            <i class="bi dbt-rec-icon" :class="recIcon(r.level)"></i>
            <div class="dbt-rec-body">
              <div class="dbt-rec-title">{{ r.title }}</div>
              <div class="dbt-rec-detail">{{ r.detail }}</div>
              <div v-if="r.directive && r.suggested" class="dbt-rec-action">
                <code>{{ r.directive }} = {{ r.suggested }}</code>
                <BaseButton variant="ghost" size="sm" @click="applySuggestion(r)">
                  <i class="bi bi-magic"></i> Usar este valor
                </BaseButton>
              </div>
            </div>
          </div>
        </div>
      </BaseCard>

      <!-- Editor de directivas -->
      <BaseCard title="Configuración (my.cnf)" icon="sliders">
        <p class="dbt-muted">
          Edita las directivas clave. Se escriben en un archivo propio del panel
          (<code>{{ dropinPath || '99-svqpanel-tuner.cnf' }}</code>), sin tocar la config base.
          Vacío = valor por defecto del servidor.
        </p>
        <div class="dbt-directives">
          <div v-for="(spec, key) in directives" :key="key" class="dbt-dir">
            <div class="dbt-dir-info">
              <div class="dbt-dir-label">{{ spec.label }}</div>
              <code class="dbt-dir-key">{{ key }}</code>
              <div class="dbt-dir-help">{{ spec.help }}</div>
            </div>
            <div class="dbt-dir-input">
              <input class="svq-input" v-model="form[key]" :placeholder="current[key] ?? '(servidor)'" />
              <small class="dbt-muted">Actual: {{ current[key] ?? '—' }}</small>
            </div>
          </div>
        </div>
        <div class="dbt-foot">
          <small class="dbt-muted">
            <i class="bi bi-exclamation-triangle"></i>
            Algunos cambios requieren reiniciar MariaDB para aplicarse.
          </small>
          <div class="dbt-foot-actions">
            <BaseButton variant="ghost" size="sm" :loading="restarting" @click="restart">
              <i class="bi bi-arrow-repeat"></i> Reiniciar MariaDB
            </BaseButton>
            <BaseButton variant="primary" size="sm" :loading="saving" @click="save">
              Guardar configuración
            </BaseButton>
          </div>
        </div>
      </BaseCard>
    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import { useMainStore } from '../stores/useMainStore'
import api from '../services/api'
import BaseCard from '../components/ui/BaseCard.vue'
import BaseButton from '../components/ui/BaseButton.vue'

export default {
  name: 'DbTuner',
  components: { BaseCard, BaseButton },
  setup() {
    const store = useMainStore()
    const loading = ref(true), saving = ref(false), restarting = ref(false)
    const enabled = ref(false), overall = ref('ok')
    const metrics = ref({}), recommendations = ref([]), directives = ref({})
    const current = ref({}), dropin = ref({}), dropinPath = ref(''), serverVersion = ref('')
    const form = ref({})

    const load = async () => {
      loading.value = true
      try {
        const data = await api.getDbTunerStatus()
        enabled.value = data.enabled
        overall.value = data.overall
        metrics.value = data.metrics || {}
        recommendations.value = data.recommendations || []
        directives.value = data.directives || {}
        current.value = data.current || {}
        dropin.value = data.dropin || {}
        dropinPath.value = data.dropin_path || ''
        serverVersion.value = 'MariaDB ' + (data.server_version || '')
        // El form arranca con lo que el panel ya tiene escrito (drop-in)
        const f = {}
        for (const key of Object.keys(directives.value)) f[key] = dropin.value[key] ?? ''
        form.value = f
      } catch (e) {
        if (e.status === 503) { enabled.value = false }
        else store.showNotification('Error: ' + e.message, 'danger')
      } finally { loading.value = false }
    }

    const applySuggestion = (r) => {
      form.value[r.directive] = r.suggested
      store.showNotification(`${r.directive} = ${r.suggested} cargado. Revisa y guarda.`, 'info')
    }

    const save = async () => {
      const directivesToSend = {}
      for (const [k, v] of Object.entries(form.value)) {
        if (String(v).trim() !== '') directivesToSend[k] = String(v).trim()
      }
      if (!Object.keys(directivesToSend).length) {
        store.showNotification('No hay directivas que guardar (todos vacíos).', 'warning')
        return
      }
      saving.value = true
      try {
        await api.setDbTunerConfig(directivesToSend)
        store.showNotification('Configuración guardada. Reinicia MariaDB para aplicar.', 'success')
        await load()
      } catch (e) { store.showNotification('Error: ' + e.message, 'danger') }
      finally { saving.value = false }
    }

    const restart = async () => {
      if (!confirm('¿Reiniciar MariaDB? Las conexiones activas se cortarán brevemente.')) return
      restarting.value = true
      try {
        const res = await api.restartDbTuner()
        store.showNotification(res.message || 'MariaDB reiniciado', 'success')
        setTimeout(load, 2000)
      } catch (e) { store.showNotification('Error: ' + e.message, 'danger') }
      finally { restarting.value = false }
    }

    const overallIcon = computed(() => ({
      ok: 'bi-check-circle-fill', info: 'bi-info-circle-fill',
      warn: 'bi-exclamation-triangle-fill', crit: 'bi-exclamation-octagon-fill',
    })[overall.value] || 'bi-info-circle-fill')
    const overallTitle = computed(() => ({
      ok: 'La base de datos está bien configurada',
      info: 'Hay sugerencias menores de mejora',
      warn: 'Se recomienda ajustar la configuración',
      crit: 'Hay problemas que conviene resolver',
    })[overall.value] || '')

    const recIcon = (level) => (({
      ok: 'bi-check-circle', info: 'bi-info-circle',
      warn: 'bi-exclamation-triangle', crit: 'bi-exclamation-octagon',
    })[level] || 'bi-info-circle')

    const metricCards = computed(() => {
      const m = metrics.value
      const cards = []
      if (m.innodb_buffer_hit_pct != null)
        cards.push({ label: 'Buffer pool hit', value: m.innodb_buffer_hit_pct + '%',
                     cls: m.innodb_buffer_hit_pct >= 99 ? 'ok' : 'warn' })
      if (m.innodb_buffer_pool_size != null)
        cards.push({ label: 'Buffer pool', value: m.innodb_buffer_pool_size })
      if (m.connections_used_pct != null)
        cards.push({ label: 'Conexiones (pico)', value: m.connections_used_pct + '%',
                     cls: m.connections_used_pct > 85 ? 'warn' : 'ok' })
      if (m.tmp_tables_on_disk_pct != null)
        cards.push({ label: 'Tmp en disco', value: m.tmp_tables_on_disk_pct + '%',
                     cls: m.tmp_tables_on_disk_pct > 25 ? 'warn' : 'ok' })
      if (m.slow_query_pct != null)
        cards.push({ label: 'Consultas lentas', value: m.slow_query_pct + '%' })
      if (m.uptime_hours != null)
        cards.push({ label: 'Uptime', value: m.uptime_hours + ' h' })
      if (m.ram_total != null)
        cards.push({ label: 'RAM del host', value: m.ram_total })
      return cards
    })

    onMounted(load)

    return {
      loading, saving, restarting, enabled, overall, metrics, recommendations,
      directives, current, dropin, dropinPath, serverVersion, form,
      load, applySuggestion, save, restart,
      overallIcon, overallTitle, recIcon, metricCards,
    }
  },
}
</script>

<style scoped>
.dbt-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; margin-bottom: 1.5rem; }
.dbt-title { font-size: 1.5rem; font-weight: 700; margin: 0; display: flex; align-items: center; gap: .5rem; }
.dbt-subtitle { color: var(--text-muted); margin: .25rem 0 0; font-size: .9rem; }
.dbt-loading, .dbt-empty { text-align: center; padding: 3rem 1rem; color: var(--text-muted); }
.dbt-empty i { font-size: 2.5rem; display: block; margin-bottom: .75rem; opacity: .5; }
.dbt-muted { color: var(--text-muted); font-size: .85rem; }

.dbt-summary { margin-bottom: 1.25rem; }
.dbt-summary-row { display: flex; align-items: center; gap: 1rem; }
.dbt-summary-icon { font-size: 1.75rem; }
.dbt-summary-title { font-weight: 600; font-size: 1.05rem; }
.dbt-summary-sub { color: var(--text-muted); font-size: .85rem; }
.dbt-summary--ok   .dbt-summary-icon { color: var(--success); }
.dbt-summary--info .dbt-summary-icon { color: var(--accent); }
.dbt-summary--warn .dbt-summary-icon { color: var(--warning, #f59e0b); }
.dbt-summary--crit .dbt-summary-icon { color: var(--danger); }

.dbt-metrics { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: .75rem; margin-bottom: 1.25rem; }
.dbt-metric { background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--radius-md); padding: .85rem 1rem; }
.dbt-metric-label { font-size: .75rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: .03em; }
.dbt-metric-value { font-size: 1.25rem; font-weight: 600; margin-top: .25rem; font-family: var(--font-mono, monospace); }
.dbt-metric-value.ok { color: var(--success); }
.dbt-metric-value.warn { color: var(--warning, #f59e0b); }

.dbt-allok { color: var(--success); display: flex; align-items: center; gap: .5rem; padding: .5rem 0; }
.dbt-recs { display: flex; flex-direction: column; gap: .75rem; }
.dbt-rec { display: flex; gap: .75rem; padding: 1rem; border-radius: var(--radius-md); border: 1px solid var(--border); background: var(--surface-2); }
.dbt-rec--warn { border-left: 3px solid var(--warning, #f59e0b); }
.dbt-rec--crit { border-left: 3px solid var(--danger); }
.dbt-rec--info { border-left: 3px solid var(--accent); }
.dbt-rec--ok   { border-left: 3px solid var(--success); }
.dbt-rec-icon { font-size: 1.1rem; margin-top: .15rem; }
.dbt-rec--warn .dbt-rec-icon { color: var(--warning, #f59e0b); }
.dbt-rec--crit .dbt-rec-icon { color: var(--danger); }
.dbt-rec--info .dbt-rec-icon { color: var(--accent); }
.dbt-rec-title { font-weight: 600; }
.dbt-rec-detail { color: var(--text-secondary); font-size: .88rem; margin-top: .2rem; line-height: 1.45; }
.dbt-rec-action { display: flex; align-items: center; gap: .75rem; margin-top: .6rem; flex-wrap: wrap; }
.dbt-rec-action code { background: var(--surface-inset); padding: .25rem .5rem; border-radius: 6px; font-size: .8rem; }

.dbt-directives { display: flex; flex-direction: column; gap: 1rem; margin: 1rem 0; }
.dbt-dir { display: grid; grid-template-columns: 1.6fr 1fr; gap: 1.5rem; padding-bottom: 1rem; border-bottom: 1px solid var(--border); }
.dbt-dir:last-child { border-bottom: none; }
@media (max-width: 720px) { .dbt-dir { grid-template-columns: 1fr; gap: .5rem; } }
.dbt-dir-label { font-weight: 600; font-size: .92rem; }
.dbt-dir-key { font-size: .78rem; color: var(--text-muted); font-family: var(--font-mono, monospace); }
.dbt-dir-help { font-size: .82rem; color: var(--text-muted); margin-top: .35rem; line-height: 1.4; }
.dbt-dir-input { display: flex; flex-direction: column; gap: .3rem; }
.dbt-foot { display: flex; align-items: center; justify-content: space-between; gap: 1rem; margin-top: 1rem; flex-wrap: wrap; }
.dbt-foot-actions { display: flex; gap: .5rem; }
</style>
