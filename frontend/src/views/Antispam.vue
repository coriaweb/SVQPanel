<template>
  <div class="sv-view">
    <div class="as-head">
      <div>
        <h2 class="as-title"><i class="bi bi-shield-check"></i> Antispam</h2>
        <p class="as-subtitle">Estado del filtro Rspamd y del aprendizaje (Bayes)</p>
      </div>
      <button class="as-btn" :disabled="loading" @click="load">
        <i class="bi bi-arrow-clockwise"></i> Actualizar
      </button>
    </div>

    <div v-if="loading" class="as-loading"><span class="as-spinner"></span></div>

    <div v-else-if="!data.available" class="as-empty">
      <i class="bi bi-shield-slash"></i>
      <p>No se pudo consultar Rspamd{{ data.reason ? ' (' + data.reason + ')' : '' }}.</p>
    </div>

    <div v-else>
      <!-- Estado del aprendizaje -->
      <div class="as-card" :class="data.bayes_ready ? 'as-card--ok' : 'as-card--warn'">
        <div class="as-card-icon"><i class="bi" :class="data.bayes_ready ? 'bi-mortarboard-fill' : 'bi-hourglass-split'"></i></div>
        <div>
          <div class="as-card-title">
            {{ data.bayes_ready ? 'El filtro ya está aprendiendo y puntuando' : 'El filtro está aprendiendo (en rodaje)' }}
          </div>
          <div class="as-card-sub">
            <template v-if="data.bayes_ready">
              El Bayes tiene datos suficientes y ya influye en la detección de spam.
            </template>
            <template v-else>
              Necesita ~{{ data.min_learns }} correos de spam y {{ data.min_learns }} de ham aprendidos
              para puntuar con fuerza. Pide a los clientes que muevan el spam a la carpeta «Junk».
            </template>
          </div>
        </div>
      </div>

      <!-- Aprendizaje -->
      <h6 class="as-section">Aprendizaje (Bayes)</h6>
      <div class="as-grid">
        <div class="as-metric">
          <div class="as-metric-val">{{ data.learned_spam }}</div>
          <div class="as-metric-lbl">Spam aprendido</div>
          <div class="as-progress"><div class="as-progress-fill as-fill-spam" :style="{width: pct(data.learned_spam, data.min_learns)+'%'}"></div></div>
          <div class="as-metric-hint">objetivo: {{ data.min_learns }}</div>
        </div>
        <div class="as-metric">
          <div class="as-metric-val">{{ data.learned_ham }}</div>
          <div class="as-metric-lbl">Legítimo aprendido (ham)</div>
          <div class="as-progress"><div class="as-progress-fill as-fill-ham" :style="{width: pct(data.learned_ham, data.min_learns)+'%'}"></div></div>
          <div class="as-metric-hint">objetivo: {{ data.min_learns }}</div>
        </div>
      </div>

      <!-- Actividad -->
      <h6 class="as-section">Actividad del filtro</h6>
      <div class="as-grid as-grid-4">
        <div class="as-metric as-metric-sm">
          <div class="as-metric-val">{{ data.scanned }}</div>
          <div class="as-metric-lbl">Correos analizados</div>
        </div>
        <div class="as-metric as-metric-sm">
          <div class="as-metric-val">{{ data.spam }}</div>
          <div class="as-metric-lbl">Tratados como spam</div>
        </div>
        <div class="as-metric as-metric-sm">
          <div class="as-metric-val">{{ data.ham }}</div>
          <div class="as-metric-lbl">Tratados como legítimo</div>
        </div>
        <div class="as-metric as-metric-sm">
          <div class="as-metric-val">{{ data.learned_total }}</div>
          <div class="as-metric-lbl">Total aprendidos</div>
        </div>
      </div>

      <!-- Acciones -->
      <h6 class="as-section">Acciones aplicadas</h6>
      <div class="as-actions">
        <div class="as-action"><span class="as-dot as-dot-danger"></span> Rechazados <b>{{ data.act_reject }}</b></div>
        <div class="as-action"><span class="as-dot as-dot-warn"></span> Frenados (rate-limit / greylist) <b>{{ data.act_soft_reject + data.act_greylist }}</b></div>
        <div class="as-action"><span class="as-dot as-dot-info"></span> Marcados como spam <b>{{ data.act_add_header }}</b></div>
        <div class="as-action"><span class="as-dot as-dot-ok"></span> Entregados sin acción <b>{{ data.act_no_action }}</b></div>
      </div>

      <p class="as-tip">
        <i class="bi bi-lightbulb"></i>
        Para que el filtro mejore: los clientes deben <strong>mover el spam a la carpeta «Junk»</strong>
        (no borrarlo) y <strong>sacar de «Junk»</strong> lo que sea legítimo. Cada movimiento entrena a Rspamd.
      </p>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useMainStore } from '../stores/useMainStore'
import api from '../services/api'

const store = useMainStore()
const loading = ref(true)
const data = ref({ available: false })

function pct(v, max) { return max > 0 ? Math.min(100, Math.round(100 * v / max)) : 0 }

async function load() {
  loading.value = true
  try {
    data.value = await api.get('/api/antispam/stats')
  } catch (e) {
    store.showNotification('Error al cargar el antispam: ' + (e.message || e), 'danger')
    data.value = { available: false }
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.as-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem; margin-bottom: 1.25rem; flex-wrap: wrap; }
.as-title { font-size: 1.5rem; font-weight: 700; display: flex; align-items: center; gap: .5rem; }
.as-subtitle { color: var(--text-muted); font-size: .9rem; margin-top: .25rem; }

.as-loading { text-align: center; padding: 2rem; }
.as-spinner { display: inline-block; width: 1.4rem; height: 1.4rem; border: 2px solid var(--border); border-top-color: var(--ac); border-radius: 50%; animation: as-spin .6s linear infinite; }
@keyframes as-spin { to { transform: rotate(360deg); } }
.as-empty { text-align: center; padding: 3rem 1rem; color: var(--text-muted); }
.as-empty i { font-size: 2.5rem; display: block; margin-bottom: .5rem; }

.as-card { display: flex; gap: 1rem; align-items: center; padding: 1.1rem 1.25rem; border-radius: var(--r-md); border: 1px solid var(--border); margin-bottom: 1.5rem; }
.as-card--ok { background: color-mix(in srgb, var(--success) 8%, transparent); border-color: color-mix(in srgb, var(--success) 30%, transparent); }
.as-card--warn { background: color-mix(in srgb, var(--warning) 8%, transparent); border-color: color-mix(in srgb, var(--warning) 30%, transparent); }
.as-card-icon i { font-size: 1.8rem; }
.as-card--ok .as-card-icon i { color: var(--success); }
.as-card--warn .as-card-icon i { color: var(--warning); }
.as-card-title { font-weight: 600; font-size: .98rem; }
.as-card-sub { color: var(--text-muted); font-size: .85rem; margin-top: .2rem; }

.as-section { font-size: .8rem; font-weight: 600; text-transform: uppercase; letter-spacing: .03em; color: var(--text-muted); margin: 1.25rem 0 .65rem; }

.as-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
.as-grid-4 { grid-template-columns: repeat(4, 1fr); }
@media (max-width: 640px) { .as-grid, .as-grid-4 { grid-template-columns: 1fr 1fr; } }
.as-metric { border: 1px solid var(--border); border-radius: var(--r-md); padding: 1rem; background: var(--surface-1); }
.as-metric-sm { padding: .8rem; }
.as-metric-val { font-size: 1.7rem; font-weight: 700; line-height: 1; }
.as-metric-lbl { font-size: .8rem; color: var(--text-muted); margin-top: .35rem; }
.as-metric-hint { font-size: .72rem; color: var(--text-muted); margin-top: .3rem; }
.as-progress { height: 6px; background: var(--surface-inset); border-radius: 999px; overflow: hidden; margin-top: .6rem; }
.as-progress-fill { height: 100%; border-radius: 999px; transition: width .2s; }
.as-fill-spam { background: var(--danger); }
.as-fill-ham { background: var(--success); }

.as-actions { display: flex; flex-wrap: wrap; gap: 1.25rem; padding: 1rem 1.25rem; border: 1px solid var(--border); border-radius: var(--r-md); background: var(--surface-1); }
.as-action { font-size: .88rem; display: flex; align-items: center; gap: .45rem; }
.as-action b { margin-left: .15rem; }
.as-dot { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
.as-dot-danger { background: var(--danger); }
.as-dot-warn { background: var(--warning); }
.as-dot-info { background: var(--info); }
.as-dot-ok { background: var(--success); }

.as-tip { margin-top: 1.5rem; font-size: .85rem; color: var(--text-secondary); background: color-mix(in srgb, var(--info) 7%, transparent); border: 1px solid color-mix(in srgb, var(--info) 22%, transparent); border-radius: var(--r-md); padding: .8rem 1rem; }

.as-btn { display: inline-flex; align-items: center; gap: .35rem; padding: .4rem .8rem; font-size: .82rem; border-radius: var(--r-sm); border: 1px solid var(--border); background: var(--surface-2); color: var(--text); cursor: pointer; }
.as-btn:disabled { opacity: .55; cursor: not-allowed; }
</style>
