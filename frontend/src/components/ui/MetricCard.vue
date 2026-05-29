<template>
  <div class="metric">
    <div class="metric__top">
      <span class="metric__chip" :class="`metric__chip--${tone}`">
        <i class="bi" :class="`bi-${icon}`"></i>
      </span>
      <span class="metric__delta" v-if="delta !== null && delta !== undefined" :class="deltaClass">
        <i class="bi" :class="delta >= 0 ? 'bi-arrow-up-short' : 'bi-arrow-down-short'"></i>{{ Math.abs(delta) }}%
      </span>
    </div>
    <div class="metric__value">
      <span v-if="loading" class="svq-skeleton metric__skeleton"></span>
      <template v-else>{{ value }}<small v-if="unit" class="metric__unit">{{ unit }}</small></template>
    </div>
    <p class="metric__label">{{ label }}</p>
    <p class="metric__hint" v-if="hint">{{ hint }}</p>
  </div>
</template>

<script>
export default {
  name: 'MetricCard',
  props: {
    icon: { type: String, default: 'graph-up' },
    label: { type: String, default: '' },
    value: { type: [String, Number], default: '—' },
    unit: { type: String, default: '' },
    hint: { type: String, default: '' },
    tone: { type: String, default: 'brand' }, // brand | success | warning | danger | info
    delta: { type: Number, default: null },
    loading: { type: Boolean, default: false },
  },
  computed: {
    deltaClass() {
      return this.delta >= 0 ? 'is-up' : 'is-down'
    },
  },
}
</script>

<style scoped>
.metric {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-sm);
  padding: var(--sp-5);
  transition: box-shadow var(--t-base) var(--ease), transform var(--t-base) var(--ease);
}
.metric:hover { box-shadow: var(--shadow-md); transform: translateY(-2px); }
.metric__top { display: flex; align-items: center; justify-content: space-between; margin-bottom: var(--sp-4); }
.metric__chip {
  width: 40px; height: 40px;
  display: grid; place-items: center;
  border-radius: var(--r-md);
  font-size: 18px;
}
.metric__chip--brand   { background: var(--brand-50);    color: var(--color-primary); }
[data-theme="dark"] .metric__chip--brand { background: var(--surface-2); color: var(--brand-400); }
.metric__chip--success { background: var(--success-bg);  color: var(--success); }
.metric__chip--warning { background: var(--warning-bg);  color: var(--warning); }
.metric__chip--danger  { background: var(--danger-bg);   color: var(--danger); }
.metric__chip--info    { background: var(--info-bg);     color: var(--info); }

.metric__delta { display: inline-flex; align-items: center; font-size: var(--fs-sm); font-weight: var(--fw-semibold); }
.metric__delta.is-up { color: var(--success); }
.metric__delta.is-down { color: var(--danger); }

.metric__value {
  font-size: var(--fs-3xl);
  font-weight: var(--fw-bold);
  line-height: 1.1;
  color: var(--text);
  letter-spacing: -.02em;
}
.metric__unit { font-size: var(--fs-lg); font-weight: var(--fw-medium); color: var(--text-muted); margin-left: 4px; }
.metric__skeleton { display: inline-block; width: 64px; height: 32px; }
.metric__label { margin: var(--sp-2) 0 0; color: var(--text-secondary); font-size: var(--fs-base); font-weight: var(--fw-medium); }
.metric__hint { margin: 2px 0 0; color: var(--text-muted); font-size: var(--fs-sm); }
</style>
