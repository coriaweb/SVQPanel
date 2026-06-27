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

      <!-- ===== AJUSTES DEL ADMIN ===== -->
      <template v-if="tuning.available">
        <!-- Umbrales -->
        <h6 class="as-section">Umbrales de decisión (sensibilidad)</h6>
        <p class="as-hint-block">
          Cuanto más bajo el umbral, más agresivo. Un correo se <b>marca como spam</b> (va a Junk)
          al superar «Marcar», y se <b>rechaza</b> al superar «Rechazar». Bajar «Rechazar» si se
          cuela mucho spam claro; subirlo si hay falsos positivos.
        </p>
        <div class="as-grid as-grid-3">
          <div v-for="k in ['greylist','add header','reject']" :key="k" class="as-metric as-metric-sm">
            <div class="as-metric-lbl">{{ actionLabel(k) }}</div>
            <input type="number" step="0.5" class="as-input" v-model.number="thresholds[k]" />
            <div class="as-metric-hint">por defecto: {{ tuning.default_actions[k] }}</div>
          </div>
        </div>
        <div class="as-row-end">
          <button class="as-btn as-btn-primary" :disabled="savingT" @click="saveThresholds">
            <i class="bi bi-check-lg"></i> Guardar umbrales
          </button>
        </div>

        <!-- Pesos de símbolos -->
        <h6 class="as-section">Peso de reglas (símbolos de Rspamd)</h6>
        <p class="as-hint-block">
          Sube el castigo de las señales que veas en tu spam. Pasa el ratón por la
          descripción para ver su significado. Los <strong>modificados</strong> salen
          resaltados; el botón ↺ restaura el valor por defecto. Vacío = por defecto.
        </p>
        <div class="as-symbar">
          <input type="search" class="as-input as-input-wide" placeholder="Buscar símbolo o descripción… (ej. PHISHING, HELO, DKIM)"
                 v-model="symSearch" />
          <label class="as-symfilter">
            <input type="checkbox" v-model="onlyEdited" /> Solo modificados ({{ Object.keys(tuning.weight_overrides || {}).length }})
          </label>
        </div>
        <div class="as-symtable">
          <div v-for="s in pagedSymbols" :key="s.name" class="as-symrow" :class="{ 'as-symrow--edited': isEdited(s.name) }">
            <div class="as-symname">
              <code>{{ s.name }}</code>
              <span v-if="isEdited(s.name)" class="as-symtag">modificado</span>
              <span class="as-symdesc" :title="s.description || s.name">
                {{ s.description_es || s.description || '—' }}
              </span>
            </div>
            <div class="as-symw">
              <span class="as-symdef" :title="'Peso por defecto: ' + s.weight">def {{ s.weight }}</span>
              <input type="number" step="0.5" class="as-input as-input-xs"
                     :placeholder="String(s.weight)" v-model.number="weightEdits[s.name]" />
              <button class="as-btn as-btn-xs" :disabled="savingW" @click="saveWeight(s.name)">Aplicar</button>
              <button v-if="isEdited(s.name)" class="as-btn as-btn-xs as-btn-danger" :disabled="savingW"
                      :title="'Restaurar peso por defecto (' + s.weight + ')'" @click="resetWeight(s.name)">↺</button>
            </div>
          </div>
          <div v-if="!filteredSymbols.length" class="as-empty-sm">Sin resultados.</div>
        </div>
        <div class="as-pager" v-if="filteredSymbols.length > pageSize">
          <button class="as-btn as-btn-xs" :disabled="symPage===0" @click="symPage--">‹ Anterior</button>
          <span class="as-pager-info">{{ symPage*pageSize+1 }}–{{ Math.min((symPage+1)*pageSize, filteredSymbols.length) }} de {{ filteredSymbols.length }}</span>
          <button class="as-btn as-btn-xs" :disabled="(symPage+1)*pageSize>=filteredSymbols.length" @click="symPage++">Siguiente ›</button>
        </div>

        <!-- Reglas de contenido -->
        <h6 class="as-section">Reglas propias (por remitente, asunto o palabra)</h6>
        <p class="as-hint-block">
          Bloquea o marca correos por su contenido. Ej.: remitente <code>@spammer.com</code>,
          asunto contiene <code>oferta</code>, o palabra en el cuerpo.
          <br><strong>Ojo:</strong> «contiene» también bloquea variantes (RE:, Fwd:, texto
          añadido) — útil para spam, pero con palabras cortas puede pillar correos buenos.
          Usa «es exactamente» si quieres bloquear solo ese asunto literal.
        </p>
        <div class="as-rules">
          <div v-for="(r, i) in rules" :key="i" class="as-rule">
            <select class="as-input" v-model="r.type">
              <option v-for="(lbl, t) in tuning.rule_types" :key="t" :value="t">{{ lbl }}</option>
            </select>
            <select v-if="r.type !== 'from'" class="as-input as-input-sm" v-model="r.match">
              <option v-for="(lbl, m) in tuning.rule_matches" :key="m" :value="m">{{ lbl }}</option>
            </select>
            <input class="as-input" v-model="r.pattern" placeholder="patrón (ej. @dominio.com, palabra)" />
            <select class="as-input" v-model="r.action">
              <option v-for="(lbl, a) in tuning.rule_actions" :key="a" :value="a">{{ lbl }}</option>
            </select>
            <input v-if="r.action==='spam'" type="number" step="0.5" class="as-input as-input-xs"
                   v-model.number="r.weight" placeholder="peso" />
            <button class="as-btn as-btn-xs as-btn-danger" @click="rules.splice(i,1)"><i class="bi bi-trash"></i></button>
          </div>
          <div v-if="!rules.length" class="as-empty-sm">No hay reglas. Añade una abajo.</div>
        </div>
        <div class="as-row-end">
          <button class="as-btn" @click="rules.push({type:'subject',match:'contains',pattern:'',action:'reject',weight:6})">
            <i class="bi bi-plus-lg"></i> Añadir regla
          </button>
          <button class="as-btn as-btn-primary" :disabled="savingR" @click="saveRules">
            <i class="bi bi-check-lg"></i> Guardar reglas
          </button>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useMainStore } from '../stores/useMainStore'
import api from '../services/api'

const store = useMainStore()
const loading = ref(true)
const data = ref({ available: false })

// Ajustes del admin
const tuning = ref({ available: false, symbols: [], rules: [], default_actions: {}, rule_types: {}, rule_actions: {}, rule_matches: {} })
const thresholds = ref({ greylist: 4, 'add header': 6, reject: 15 })
const weightEdits = ref({})
const rules = ref([])
const symSearch = ref('')
const onlyEdited = ref(false)
const symPage = ref(0)
const pageSize = 25
const savingT = ref(false)
const savingW = ref(false)
const savingR = ref(false)

const ACTION_LABELS = { greylist: 'Greylist (lista gris)', 'add header': 'Marcar como spam', reject: 'Rechazar' }
function actionLabel(k) { return ACTION_LABELS[k] || k }

function pct(v, max) { return max > 0 ? Math.min(100, Math.round(100 * v / max)) : 0 }

function isEdited(name) {
  return Object.prototype.hasOwnProperty.call(tuning.value.weight_overrides || {}, name)
}

const filteredSymbols = computed(() => {
  const q = symSearch.value.trim().toLowerCase()
  let list = tuning.value.symbols || []
  if (onlyEdited.value) list = list.filter(s => isEdited(s.name))
  if (q) {
    list = list.filter(s =>
      s.name.toLowerCase().includes(q) ||
      (s.description_es || '').toLowerCase().includes(q) ||
      (s.description || '').toLowerCase().includes(q))
  }
  return list
})

const pagedSymbols = computed(() =>
  filteredSymbols.value.slice(symPage.value * pageSize, (symPage.value + 1) * pageSize)
)

// Volver a la primera página al cambiar el filtro/búsqueda.
watch([symSearch, onlyEdited], () => { symPage.value = 0 })

async function resetWeight(name) {
  delete weightEdits.value[name]
  savingW.value = true
  try {
    const weights = {}
    for (const [k, v] of Object.entries(weightEdits.value)) {
      if (v !== '' && v !== null && v !== undefined && !Number.isNaN(Number(v))) weights[k] = Number(v)
    }
    await api.put('/api/antispam/tuning', { weights })
    store.showNotification(`Peso de ${name} restaurado al valor por defecto`, 'success')
    await load()
  } catch (e) {
    store.showNotification('Error: ' + (e.message || e), 'danger')
  } finally { savingW.value = false }
}

async function load() {
  loading.value = true
  try {
    data.value = await api.get('/api/antispam/stats')
    try {
      const t = await api.get('/api/antispam/tuning')
      tuning.value = t
      if (t.actions) thresholds.value = { ...thresholds.value, ...t.actions }
      weightEdits.value = { ...(t.weight_overrides || {}) }
      rules.value = (t.rules || []).map(r => ({ weight: 6, match: 'contains', ...r }))
    } catch { /* tuning no disponible: dejar solo stats */ }
  } catch (e) {
    store.showNotification('Error al cargar el antispam: ' + (e.message || e), 'danger')
    data.value = { available: false }
  } finally {
    loading.value = false
  }
}

async function saveThresholds() {
  savingT.value = true
  try {
    await api.put('/api/antispam/tuning', { actions: thresholds.value })
    store.showNotification('Umbrales guardados', 'success')
  } catch (e) {
    store.showNotification('Error: ' + (e.message || e), 'danger')
  } finally { savingT.value = false }
}

async function saveWeight(name) {
  savingW.value = true
  try {
    // Reunir todos los overrides actuales (los editados con valor numérico).
    const weights = {}
    for (const [k, v] of Object.entries(weightEdits.value)) {
      if (v !== '' && v !== null && v !== undefined && !Number.isNaN(Number(v))) weights[k] = Number(v)
    }
    await api.put('/api/antispam/tuning', { weights })
    store.showNotification(`Peso de ${name} aplicado`, 'success')
    await load()  // refrescar para marcar el símbolo como modificado
  } catch (e) {
    store.showNotification('Error: ' + (e.message || e), 'danger')
  } finally { savingW.value = false }
}

async function saveRules() {
  savingR.value = true
  try {
    const clean = rules.value.filter(r => r.pattern && r.pattern.trim())
    await api.put('/api/antispam/rules', { rules: clean })
    store.showNotification('Reglas guardadas', 'success')
  } catch (e) {
    store.showNotification('Error: ' + (e.message || e), 'danger')
  } finally { savingR.value = false }
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
.as-btn-primary { background: var(--ac); border-color: var(--ac); color: #fff; }
.as-btn-danger { color: var(--danger); }
.as-btn-xs { padding: .25rem .55rem; font-size: .76rem; }

.as-hint-block { font-size: .85rem; color: var(--text-muted); margin: 0 0 .75rem; }
.as-grid-3 { grid-template-columns: repeat(3, 1fr); }
@media (max-width: 640px) { .as-grid-3 { grid-template-columns: 1fr; } }
.as-input { width: 100%; padding: .4rem .6rem; border: 1px solid var(--border); border-radius: var(--r-sm); background: var(--surface-1); color: var(--text); font-size: .85rem; margin-top: .3rem; }
.as-input-wide { max-width: 420px; margin-bottom: .8rem; }
.as-input-xs { width: 80px; margin-top: 0; }
.as-input-sm { width: 140px; margin-top: 0; flex: none; }
.as-row-end { display: flex; justify-content: flex-end; gap: .6rem; margin-top: .8rem; }

.as-symbar { display: flex; align-items: center; gap: 1rem; margin-bottom: .8rem; flex-wrap: wrap; }
.as-symbar .as-input-wide { margin-bottom: 0; }
.as-symfilter { font-size: .82rem; color: var(--text-muted); display: flex; align-items: center; gap: .35rem; white-space: nowrap; }
.as-symtable { border: 1px solid var(--border); border-radius: var(--r-md); overflow: hidden; }
.as-symrow { display: flex; justify-content: space-between; align-items: center; gap: 1rem; padding: .5rem .8rem; border-bottom: 1px solid var(--border); }
.as-symrow:last-child { border-bottom: 0; }
.as-symrow--edited { background: color-mix(in srgb, var(--ac) 8%, transparent); border-left: 3px solid var(--ac); }
.as-symname { min-width: 0; flex: 1; }
.as-symname code { font-size: .8rem; }
.as-symtag { font-size: .68rem; font-weight: 600; color: var(--ac); background: color-mix(in srgb, var(--ac) 14%, transparent); border-radius: 999px; padding: .05rem .45rem; margin-left: .45rem; }
.as-symdesc { display: block; font-size: .76rem; color: var(--text-muted); margin-top: .15rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.as-symw { display: flex; align-items: center; gap: .5rem; flex: none; }
.as-symdef { font-size: .74rem; color: var(--text-muted); cursor: help; }
.as-empty-sm { padding: 1rem; text-align: center; color: var(--text-muted); font-size: .85rem; }
.as-pager { display: flex; align-items: center; justify-content: center; gap: 1rem; margin-top: .8rem; font-size: .82rem; }
.as-pager-info { color: var(--text-muted); }

.as-rules { display: flex; flex-direction: column; gap: .5rem; }
.as-rule { display: flex; gap: .5rem; align-items: center; }
.as-rule .as-input { margin-top: 0; }
</style>
