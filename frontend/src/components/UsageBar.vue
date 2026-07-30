<template>
  <div class="ub" :class="`ub--${level}`">
    <div class="ub__head">
      <span class="ub__used">{{ formatMB(used) }}</span>
      <span class="ub__quota">
        <template v-if="quota === 0">/ ∞</template>
        <template v-else>/ {{ formatMB(quota) }}</template>
      </span>
    </div>
    <div class="ub__track">
      <div class="ub__fill" role="progressbar" :style="{ width: percent + '%' }"
           :aria-valuenow="percent" aria-valuemin="0" aria-valuemax="100"></div>
    </div>
    <div v-if="quota > 0" class="ub__foot">
      <span class="ub__pct">{{ percent }}%</span>
      <!-- El aviso va en TEXTO, no solo en el color de la barra: una barra de
           6 px teñida de amarillo pasa desapercibida al revisar 33 usuarios,
           que es justo cuando hay que enterarse. -->
      <span v-if="level !== 'ok'" class="ub__tag" :title="tagTitle">
        <i class="bi" :class="level === 'critical' ? 'bi-exclamation-octagon-fill'
                                                   : 'bi-exclamation-triangle-fill'"></i>
        {{ level === 'critical' ? 'Casi lleno' : 'Alto' }}
      </span>
      <span v-if="quota > 0 && level !== 'ok'" class="ub__left">
        quedan {{ formatMB(Math.max(0, quota - used)) }}
      </span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  used:  { type: Number, default: 0 },
  quota: { type: Number, default: 0 },   // 0 = ilimitado
  warn:  { type: Number, default: 80 },  // % a partir del cual se avisa
  crit:  { type: Number, default: 95 },  // % a partir del cual es crítico
})

const percent = computed(() => {
  if (!props.quota) return 0
  return Math.min(100, Math.round((props.used / props.quota) * 100))
})

const level = computed(() => {
  if (!props.quota) return 'none'                 // sin cuota = ilimitado
  if (percent.value >= props.crit) return 'critical'
  if (percent.value >= props.warn) return 'warn'
  return 'ok'
})

const tagTitle = computed(() =>
  level.value === 'critical'
    ? `Por encima del ${props.crit}% de la cuota: riesgo inminente de quedarse sin espacio.`
    : `Por encima del ${props.warn}% de la cuota: conviene revisarlo.`)

function formatMB(mb) {
  if (!mb) return '0 MB'
  if (mb >= 1024 * 1024) return (mb / (1024 * 1024)).toFixed(1) + ' TB'
  if (mb >= 1024) return (mb / 1024).toFixed(mb >= 10240 ? 0 : 1) + ' GB'
  return mb + ' MB'
}
</script>

<style scoped>
.ub__head {
  display: flex;
  justify-content: space-between;
  gap: .5rem;
  font-size: .8rem;
  margin-bottom: .25rem;
}
.ub__used  { font-family: var(--font-mono, monospace); font-weight: 600; }
.ub__quota { color: var(--text-muted); }

.ub__track {
  height: 6px;
  border-radius: 999px;
  background: var(--surface-inset, #eee);
  overflow: hidden;
}
.ub__fill {
  height: 100%;
  border-radius: 999px;
  background: var(--success, #16a34a);
  transition: width .3s ease;
}
.ub--warn     .ub__fill { background: var(--warning, #d97706); }
.ub--critical .ub__fill { background: var(--danger,  #dc2626); }
.ub--none     .ub__fill { background: var(--text-muted, #999); }

.ub__foot {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: .35rem;
  margin-top: .25rem;
  font-size: .75rem;
  color: var(--text-muted);
}
.ub--warn     .ub__pct { color: var(--warning, #d97706); font-weight: 600; }
.ub--critical .ub__pct { color: var(--danger,  #dc2626); font-weight: 700; }

.ub__tag {
  display: inline-flex;
  align-items: center;
  gap: .2rem;
  padding: .05rem .35rem;
  border-radius: 999px;
  font-size: .7rem;
  font-weight: 600;
  white-space: nowrap;
}
.ub--warn .ub__tag {
  color: var(--warning, #b45309);
  background: var(--warning-bg, #fef3c7);
  border: 1px solid var(--warning-border, #fcd34d);
}
.ub--critical .ub__tag {
  color: var(--danger, #b91c1c);
  background: var(--danger-bg, #fee2e2);
  border: 1px solid var(--danger-border, #fca5a5);
}
.ub__left { white-space: nowrap; }
</style>
