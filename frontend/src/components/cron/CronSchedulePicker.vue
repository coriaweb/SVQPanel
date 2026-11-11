<template>
  <div class="csp">
    <!-- Modo -->
    <div class="csp-modes" role="tablist">
      <button v-for="m in MODES" :key="m.key" type="button" role="tab"
              class="csp-mode" :class="{ 'is-on': simple.mode === m.key }"
              :aria-selected="simple.mode === m.key" @click="setMode(m.key)">
        {{ m.label }}
      </button>
    </div>

    <!-- Detalle del modo -->
    <div class="csp-detail">
      <template v-if="simple.mode === 'minutes'">
        <span>Cada</span>
        <select v-model.number="simple.every" class="svq-input csp-sm">
          <option v-for="n in MINUTE_STEPS" :key="n" :value="n">{{ n }}</option>
        </select>
        <span>{{ simple.every === 1 ? 'minuto' : 'minutos' }}</span>
        <small v-if="simple.every < 5" class="csp-warn">
          <i class="bi bi-exclamation-triangle"></i> Muy frecuente: úsalo solo si la tarea es rápida.
        </small>
      </template>

      <template v-else-if="simple.mode === 'hourly'">
        <span>Cada</span>
        <select v-model.number="simple.everyHours" class="svq-input csp-sm">
          <option v-for="n in HOUR_STEPS" :key="n" :value="n">{{ n }}</option>
        </select>
        <span>{{ simple.everyHours === 1 ? 'hora' : 'horas' }}, en el minuto</span>
        <input v-model.number="simple.minute" type="number" min="0" max="59" class="svq-input csp-sm" />
      </template>

      <template v-else-if="simple.mode === 'daily'">
        <span>Todos los días a las</span>
        <input v-model="simple.time" type="time" class="svq-input csp-time" />
      </template>

      <template v-else-if="simple.mode === 'weekly'">
        <div class="csp-days">
          <button v-for="w in WEEKDAYS" :key="w.v" type="button" class="csp-day"
                  :class="{ 'is-on': simple.days.includes(w.v) }" :title="w.name"
                  @click="toggleDay(w.v)">{{ w.short }}</button>
        </div>
        <span>a las</span>
        <input v-model="simple.time" type="time" class="svq-input csp-time" />
        <small v-if="!simple.days.length" class="csp-warn">Elige al menos un día.</small>
      </template>

      <template v-else-if="simple.mode === 'monthly'">
        <span>El día</span>
        <select v-model.number="simple.monthDay" class="svq-input csp-sm">
          <option v-for="d in 31" :key="d" :value="d">{{ d }}</option>
        </select>
        <span>de cada mes a las</span>
        <input v-model="simple.time" type="time" class="svq-input csp-time" />
        <small v-if="simple.monthDay > 28" class="csp-warn">
          Los meses sin día {{ simple.monthDay }} no se ejecuta.
        </small>
      </template>

      <div v-else class="csp-adv">
        <div v-for="f in FIELDS" :key="f.key" class="csp-adv__f">
          <label>{{ f.label }}</label>
          <input v-model="adv[f.key]" class="svq-input mono" placeholder="*" />
        </div>
        <small class="csp-muted">
          Formato crontab: <code>*</code> = todos, <code>*/5</code> = cada 5, <code>1-5</code> = rango,
          <code>1,15</code> = lista. Día de la semana: 0 = domingo.
        </small>
      </div>
    </div>

    <!-- Resumen + próximas ejecuciones -->
    <div class="csp-summary">
      <div class="csp-summary__row">
        <code class="csp-expr">{{ exprText }}</code>
        <strong>{{ description }}</strong>
      </div>
      <div class="csp-next">
        <span class="csp-muted"><i class="bi bi-calendar-event"></i> Próximas ejecuciones
          <span v-if="tzLabel">(hora del servidor, {{ tzLabel }})</span>:</span>
        <span v-if="nextError" class="csp-err">{{ nextError }}</span>
        <span v-else-if="!nextRuns.length" class="csp-muted">—</span>
        <span v-for="(r, i) in nextRuns" :key="i" class="csp-chip">{{ r }}</span>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, reactive, computed, watch } from 'vue'
import api from '../../services/api.js'
import { getPanelTimezone, formatDateTime } from '../../utils/datetime'
import {
  WEEKDAYS, MINUTE_STEPS, HOUR_STEPS, defaultSimple, fromSimple, toSimple, describeCron,
} from '../../utils/cronSimple'

const MODES = [
  { key: 'minutes', label: 'Cada X minutos' },
  { key: 'hourly',  label: 'Cada hora' },
  { key: 'daily',   label: 'Cada día' },
  { key: 'weekly',  label: 'Algunos días' },
  { key: 'monthly', label: 'Cada mes' },
  { key: 'advanced', label: 'Avanzado' },
]
const FIELDS = [
  { key: 'minute', label: 'Minuto' }, { key: 'hour', label: 'Hora' },
  { key: 'day', label: 'Día' }, { key: 'month', label: 'Mes' },
  { key: 'weekday', label: 'Día semana' },
]

export default {
  name: 'CronSchedulePicker',
  props: {
    // { minute, hour, day, month, weekday }
    modelValue: { type: Object, required: true },
  },
  emits: ['update:modelValue'],
  setup(props, { emit }) {
    const simple = reactive(defaultSimple())
    const adv = reactive({ minute: '*', hour: '*', day: '*', month: '*', weekday: '*' })

    // Estado inicial desde el valor recibido (editar un cron existente)
    const init = (v) => {
      Object.assign(adv, v)
      Object.assign(simple, toSimple(v))
    }
    init(props.modelValue)

    const current = computed(() => (simple.mode === 'advanced' ? { ...adv } : fromSimple(simple)))
    const exprText = computed(() => {
      const c = current.value
      return `${c.minute} ${c.hour} ${c.day} ${c.month} ${c.weekday}`
    })
    const description = computed(() => describeCron(current.value))

    const sameAs = (a, b) => ['minute', 'hour', 'day', 'month', 'weekday'].every((k) => a[k] === b[k])
    watch(current, (c) => { if (!sameAs(c, props.modelValue)) emit('update:modelValue', { ...c }) },
          { deep: true, immediate: true })
    // Si el padre cambia el valor (p. ej. una app sugiere su frecuencia), resincronizar
    watch(() => props.modelValue, (v) => { if (!sameAs(v, current.value)) init(v) }, { deep: true })

    const setMode = (mode) => {
      if (mode === 'advanced') Object.assign(adv, current.value)
      simple.mode = mode
    }
    const toggleDay = (d) => {
      const i = simple.days.indexOf(d)
      if (i >= 0) simple.days.splice(i, 1)
      else simple.days.push(d)
    }

    // Próximas ejecuciones (calculadas en el servidor, en su hora local = la de cron)
    const nextRuns = ref([])
    const nextError = ref('')
    let timer = null
    let seq = 0
    watch(exprText, () => {
      clearTimeout(timer)
      timer = setTimeout(async () => {
        const my = ++seq
        try {
          const r = await api.cronNextRuns(current.value)
          if (my !== seq) return
          nextError.value = ''
          nextRuns.value = (r.runs || []).map((x) => formatDateTime(x))
        } catch (e) {
          if (my !== seq) return
          nextRuns.value = []
          nextError.value = 'Expresión no válida'
        }
      }, 300)
    }, { immediate: true })

    const tzLabel = computed(() => getPanelTimezone() || '')

    return {
      MODES, FIELDS, WEEKDAYS, MINUTE_STEPS, HOUR_STEPS,
      simple, adv, exprText, description, setMode, toggleDay,
      nextRuns, nextError, tzLabel,
    }
  },
}
</script>

<style scoped>
.csp { display: flex; flex-direction: column; gap: var(--sp-3); }
.csp-modes { display: flex; flex-wrap: wrap; gap: 6px; }
.csp-mode {
  font-size: var(--fs-xs); padding: 5px 11px; border-radius: var(--r-pill);
  border: 1px solid var(--border); background: var(--surface); color: var(--text-secondary);
  cursor: pointer; transition: all .12s;
}
.csp-mode:hover { border-color: var(--svq-orange); color: var(--svq-orange); }
.csp-mode.is-on { background: var(--svq-orange); border-color: var(--svq-orange); color: #fff; }
.csp-detail { display: flex; align-items: center; flex-wrap: wrap; gap: var(--sp-2); font-size: var(--fs-sm); }
.csp-sm { width: auto; min-width: 70px; }
.csp-time { width: auto; min-width: 110px; }
.csp-days { display: inline-flex; gap: 4px; }
.csp-day {
  width: 32px; height: 32px; border-radius: 50%; border: 1px solid var(--border);
  background: var(--surface); color: var(--text-secondary); font-weight: var(--fw-semibold);
  font-size: var(--fs-xs); cursor: pointer;
}
.csp-day.is-on { background: var(--svq-orange); border-color: var(--svq-orange); color: #fff; }
.csp-warn { flex-basis: 100%; color: var(--warning); font-size: var(--fs-xs); }
.csp-adv { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: var(--sp-2); width: 100%; }
.csp-adv__f { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.csp-adv__f label { font-size: var(--fs-xs); font-weight: var(--fw-semibold); }
.csp-adv__f .svq-input { width: 100%; box-sizing: border-box; }
.csp-adv small { grid-column: 1 / -1; }
@media (max-width: 560px) { .csp-adv { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
.csp-summary {
  display: flex; flex-direction: column; gap: 6px; padding: var(--sp-3);
  background: var(--surface-inset); border: 1px solid var(--border); border-radius: var(--r-md, 10px);
}
.csp-summary__row { display: flex; align-items: center; gap: var(--sp-2); flex-wrap: wrap; font-size: var(--fs-sm); }
.csp-expr { font-family: var(--font-mono); font-size: var(--fs-xs); background: var(--surface); padding: 2px 8px; border-radius: var(--r-sm); border: 1px solid var(--border); }
.csp-next { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.csp-chip { font-size: var(--fs-xs); padding: 2px 8px; border-radius: var(--r-pill); background: var(--surface); border: 1px solid var(--border); }
.csp-muted { color: var(--text-muted); font-size: var(--fs-xs); }
.csp-err { color: var(--danger); font-size: var(--fs-xs); }
</style>
