<template>
  <div class="gauge" :class="{ 'gauge--ring': ring }">
    <!-- Modo anillo (SVG) -->
    <svg v-if="ring" class="gauge__svg" viewBox="0 0 80 80">
      <circle class="gauge__track" cx="40" cy="40" r="34" />
      <circle
        class="gauge__fill"
        cx="40" cy="40" r="34"
        :stroke="strokeColor"
        :stroke-dasharray="circumference"
        :stroke-dashoffset="dashOffset"
      />
      <text x="40" y="38" class="gauge__pct">{{ Math.round(pct) }}<tspan font-size="11">%</tspan></text>
      <text x="40" y="54" class="gauge__cap" v-if="caption">{{ caption }}</text>
    </svg>

    <!-- Modo barra -->
    <div v-else class="gauge__bar-wrap">
      <div class="gauge__bar-head" v-if="label || showValue">
        <span class="gauge__label">{{ label }}</span>
        <span class="gauge__value" v-if="showValue">{{ Math.round(pct) }}%</span>
      </div>
      <div class="gauge__bar">
        <div class="gauge__bar-fill" :style="{ width: pct + '%', background: strokeColor }"></div>
      </div>
      <p class="gauge__sub" v-if="caption">{{ caption }}</p>
    </div>
  </div>
</template>

<script>
export default {
  name: 'ResourceGauge',
  props: {
    value: { type: Number, default: 0 },   // 0–100
    label: { type: String, default: '' },
    caption: { type: String, default: '' },
    ring: { type: Boolean, default: false },
    showValue: { type: Boolean, default: true },
  },
  data() {
    return { circumference: 2 * Math.PI * 34 }
  },
  computed: {
    pct() { return Math.max(0, Math.min(100, this.value || 0)) },
    dashOffset() { return this.circumference * (1 - this.pct / 100) },
    strokeColor() {
      if (this.pct >= 90) return 'var(--danger)'
      if (this.pct >= 70) return 'var(--warning)'
      return 'var(--success)'
    },
  },
}
</script>

<style scoped>
/* Anillo */
.gauge__svg { width: 96px; height: 96px; transform: rotate(-90deg); }
.gauge__track { fill: none; stroke: var(--surface-inset); stroke-width: 8; }
.gauge__fill {
  fill: none; stroke-width: 8; stroke-linecap: round;
  transition: stroke-dashoffset var(--t-slow) var(--ease-out), stroke var(--t-base);
}
.gauge__pct, .gauge__cap {
  transform: rotate(90deg); transform-origin: 40px 40px;
  text-anchor: middle; fill: var(--text); font-weight: var(--fw-bold); font-size: 18px;
  font-family: var(--font-sans);
}
.gauge__cap { fill: var(--text-muted); font-size: 9px; font-weight: var(--fw-medium); }

/* Barra */
.gauge__bar-wrap { width: 100%; }
.gauge__bar-head { display: flex; justify-content: space-between; margin-bottom: 6px; }
.gauge__label { font-size: var(--fs-sm); color: var(--text-secondary); font-weight: var(--fw-medium); }
.gauge__value { font-size: var(--fs-sm); color: var(--text); font-weight: var(--fw-semibold); }
.gauge__bar { height: 8px; background: var(--surface-inset); border-radius: var(--r-pill); overflow: hidden; }
.gauge__bar-fill { height: 100%; border-radius: var(--r-pill); transition: width var(--t-slow) var(--ease-out), background var(--t-base); }
.gauge__sub { margin: 6px 0 0; font-size: var(--fs-sm); color: var(--text-muted); }
</style>
