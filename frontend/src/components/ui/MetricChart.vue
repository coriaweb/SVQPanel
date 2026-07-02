<template>
  <div class="mchart">
    <div class="mchart__head">
      <div>
        <span class="mchart__title">{{ title }}</span>
        <span v-if="unit" class="mchart__unit">{{ unit }}</span>
      </div>
      <span class="mchart__current" :style="{ color }">{{ currentLabel }}</span>
    </div>

    <svg :viewBox="`0 0 ${W} ${H}`" preserveAspectRatio="none" class="mchart__svg">
      <!-- Líneas de referencia (grid horizontal) -->
      <line v-for="g in gridLines" :key="g.y"
            :x1="0" :y1="g.y" :x2="W" :y2="g.y"
            class="mchart__grid" />

      <!-- Área bajo la curva -->
      <path v-if="areaPath" :d="areaPath" :fill="color" fill-opacity="0.12" />
      <!-- Línea -->
      <path v-if="linePath" :d="linePath" :stroke="color" fill="none"
            stroke-width="1.5" vector-effect="non-scaling-stroke" />
    </svg>

    <div class="mchart__axis">
      <span v-for="(lbl, i) in xLabels" :key="i">{{ lbl }}</span>
    </div>
  </div>
</template>

<script>
import { computed } from 'vue'
import { formatTime } from '../../utils/datetime'

export default {
  name: 'MetricChart',
  props: {
    title:  { type: String, default: '' },
    unit:   { type: String, default: '' },
    color:  { type: String, default: 'var(--ac)' },
    // series: array de { ts, value }
    series: { type: Array, default: () => [] },
    // máximo del eje Y (si null, autoescala). Para % usar 100.
    max:    { type: Number, default: null },
    // formateador del valor actual
    format: { type: Function, default: (v) => v?.toFixed(1) },
  },
  setup(props) {
    const W = 300
    const H = 80

    const values = computed(() => props.series.map(p => p.value ?? 0))

    const yMax = computed(() => {
      if (props.max != null) return props.max
      const m = Math.max(1, ...values.value)
      return m * 1.15  // 15% de margen arriba
    })

    const points = computed(() => {
      const n = values.value.length
      if (n === 0) return []
      const ym = yMax.value || 1
      return values.value.map((v, i) => {
        const x = n === 1 ? W / 2 : (i / (n - 1)) * W
        const y = H - Math.min(H, (v / ym) * H)
        return [x, y]
      })
    })

    const linePath = computed(() => {
      const pts = points.value
      if (!pts.length) return ''
      return pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ')
    })

    const areaPath = computed(() => {
      const pts = points.value
      if (!pts.length) return ''
      const line = pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ')
      return `${line} L${pts[pts.length - 1][0].toFixed(1)},${H} L${pts[0][0].toFixed(1)},${H} Z`
    })

    const gridLines = computed(() => {
      // 3 líneas: 25/50/75% de la altura
      return [0.25, 0.5, 0.75].map(f => ({ y: H * f }))
    })

    const currentLabel = computed(() => {
      const v = values.value[values.value.length - 1]
      if (v == null) return '—'
      return props.format(v)
    })

    const xLabels = computed(() => {
      const s = props.series
      if (s.length < 2) return []
      const fmt = formatTime
      // primero, medio, último
      return [fmt(s[0].ts), fmt(s[Math.floor(s.length / 2)].ts), fmt(s[s.length - 1].ts)]
    })

    return { W, H, linePath, areaPath, gridLines, currentLabel, xLabels }
  },
}
</script>

<style scoped>
.mchart {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r-md, 10px);
  padding: 1rem;
}
.mchart__head {
  display: flex; justify-content: space-between; align-items: baseline;
  margin-bottom: .5rem;
}
.mchart__title { font-weight: 600; font-size: .9rem; }
.mchart__unit { font-size: .75rem; color: var(--text-muted); margin-left: .35rem; }
.mchart__current { font-size: 1.1rem; font-weight: 700; font-variant-numeric: tabular-nums; }
.mchart__svg { width: 100%; height: 80px; display: block; }
.mchart__grid { stroke: var(--border); stroke-width: 1; stroke-dasharray: 3 4; opacity: .5; }
.mchart__axis {
  display: flex; justify-content: space-between;
  font-size: .7rem; color: var(--text-muted); margin-top: .35rem;
}
</style>
