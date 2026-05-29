<template>
  <component
    :is="tag"
    class="btn"
    :class="[`btn--${variant}`, `btn--${size}`, { 'is-loading': loading, 'is-block': block }]"
    :disabled="(disabled || loading) && tag === 'button'"
    v-bind="$attrs"
  >
    <span v-if="loading" class="btn__spinner" />
    <i v-else-if="icon" class="bi" :class="`bi-${icon}`" />
    <span v-if="$slots.default" class="btn__label"><slot /></span>
  </component>
</template>

<script>
export default {
  name: 'BaseButton',
  inheritAttrs: false,
  props: {
    variant: { type: String, default: 'primary' }, // primary | secondary | ghost | danger | subtle
    size: { type: String, default: 'md' },          // sm | md
    icon: { type: String, default: '' },
    loading: { type: Boolean, default: false },
    disabled: { type: Boolean, default: false },
    block: { type: Boolean, default: false },
    tag: { type: String, default: 'button' },        // button | a | router-link via :is
  },
}
</script>

<style scoped>
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--sp-2);
  font-family: var(--font-sans);
  font-weight: var(--fw-medium);
  font-size: var(--fs-md);
  line-height: 1;
  border-radius: var(--r-md);
  padding: 9px 16px;
  border: 1px solid transparent;
  cursor: pointer;
  text-decoration: none;
  white-space: nowrap;
  transition: background var(--t-fast) var(--ease), color var(--t-fast) var(--ease),
              border-color var(--t-fast) var(--ease), transform var(--t-fast) var(--ease),
              box-shadow var(--t-fast) var(--ease);
}
.btn .bi { font-size: 15px; }
.btn--sm { padding: 6px 12px; font-size: var(--fs-sm); }
.btn--sm .bi { font-size: 13px; }
.btn.is-block { width: 100%; }

.btn--primary { background: var(--color-primary); color: #fff; box-shadow: var(--shadow-xs); }
.btn--primary:hover { background: var(--color-primary-hover); transform: translateY(-1px); }
.btn--primary:active { transform: translateY(0); box-shadow: none; }

.btn--secondary { background: var(--surface); color: var(--text); border-color: var(--border-strong); }
.btn--secondary:hover { background: var(--surface-inset); }

.btn--ghost { background: transparent; color: var(--text-secondary); }
.btn--ghost:hover { background: var(--surface-inset); color: var(--text); }

.btn--subtle { background: var(--brand-50); color: var(--color-primary); }
[data-theme="dark"] .btn--subtle { background: var(--surface-2); color: var(--brand-400); }
.btn--subtle:hover { background: var(--brand-100); }
[data-theme="dark"] .btn--subtle:hover { background: var(--surface-inset); }

.btn--danger { background: var(--danger); color: #fff; }
.btn--danger:hover { filter: brightness(.94); transform: translateY(-1px); }

.btn:focus-visible { outline: none; box-shadow: var(--shadow-focus); }
.btn:disabled, .btn.is-loading { opacity: .55; cursor: not-allowed; transform: none; box-shadow: none; }

.btn__spinner {
  width: 14px; height: 14px;
  border: 2px solid rgba(255,255,255,.4); border-top-color: #fff;
  border-radius: 50%; animation: svq-spin .6s linear infinite;
}
.btn--secondary .btn__spinner, .btn--ghost .btn__spinner, .btn--subtle .btn__spinner {
  border-color: var(--border-strong); border-top-color: var(--color-primary);
}
</style>
