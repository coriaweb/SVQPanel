<template>
  <span class="badge" :class="[`badge--${tone}`, { 'badge--pulse': pulse }]">
    <span class="badge__dot" v-if="dot"></span>
    <i v-else-if="icon" class="bi" :class="`bi-${icon}`"></i>
    <slot>{{ label }}</slot>
  </span>
</template>

<script>
const TONE_MAP = {
  active: 'success', valid: 'success', running: 'success', ok: 'success', success: 'success', online: 'success',
  warning: 'warning', expiring: 'warning', degraded: 'warning',
  error: 'danger', danger: 'danger', stopped: 'danger', expired: 'danger', failed: 'danger', offline: 'danger',
  pending: 'info', building: 'info', info: 'info', propagating: 'info',
  inactive: 'muted', none: 'muted', muted: 'muted', disabled: 'muted',
}

export default {
  name: 'StatusBadge',
  props: {
    status: { type: String, default: '' }, // mapea a un tono semántico
    label: { type: String, default: '' },
    icon: { type: String, default: '' },
    dot: { type: Boolean, default: true },
    pulse: { type: Boolean, default: false },
  },
  computed: {
    tone() {
      return TONE_MAP[(this.status || '').toLowerCase()] || 'muted'
    },
  },
}
</script>

<style scoped>
.badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border-radius: var(--r-pill);
  font-size: var(--fs-sm);
  font-weight: var(--fw-medium);
  line-height: 1.4;
  border: 1px solid transparent;
  white-space: nowrap;
}
.badge .bi { font-size: 12px; }
.badge__dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; flex-shrink: 0; }

.badge--success { background: var(--success-bg); color: var(--success); border-color: var(--success-border); }
.badge--warning { background: var(--warning-bg); color: var(--warning); border-color: var(--warning-border); }
.badge--danger  { background: var(--danger-bg);  color: var(--danger);  border-color: var(--danger-border); }
.badge--info    { background: var(--info-bg);    color: var(--info);    border-color: var(--info-border); }
.badge--muted   { background: var(--surface-inset); color: var(--text-muted); border-color: var(--border); }

.badge--pulse .badge__dot { animation: svq-pulse 1.6s ease infinite; }
</style>
