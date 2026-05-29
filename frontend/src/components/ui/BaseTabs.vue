<template>
  <div class="tabs">
    <div class="tabs__nav" role="tablist">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        class="tab"
        :class="{ active: modelValue === tab.key }"
        role="tab"
        :aria-selected="modelValue === tab.key"
        @click="$emit('update:modelValue', tab.key)"
      >
        <i v-if="tab.icon" class="bi" :class="`bi-${tab.icon}`"></i>
        <span>{{ tab.label }}</span>
        <span v-if="tab.badge != null" class="tab__badge">{{ tab.badge }}</span>
      </button>
    </div>
  </div>
</template>

<script>
export default {
  name: 'BaseTabs',
  props: {
    modelValue: { type: String, required: true },
    tabs: { type: Array, required: true }, // [{ key, label, icon?, badge? }]
  },
  emits: ['update:modelValue'],
}
</script>

<style scoped>
.tabs__nav {
  display: flex;
  align-items: center;
  gap: var(--sp-1);
  border-bottom: 1px solid var(--border);
  overflow-x: auto;
}
.tab {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-3) var(--sp-3) calc(var(--sp-3) + 1px);
  border: none;
  background: transparent;
  color: var(--text-muted);
  font-size: var(--fs-base);
  font-weight: var(--fw-medium);
  cursor: pointer;
  white-space: nowrap;
  transition: color var(--t-fast) var(--ease);
}
.tab .bi { font-size: 15px; }
.tab::after {
  content: '';
  position: absolute;
  left: var(--sp-2); right: var(--sp-2); bottom: -1px;
  height: 2px;
  border-radius: var(--r-pill);
  background: transparent;
  transition: background var(--t-base) var(--ease);
}
.tab:hover { color: var(--text); }
.tab.active { color: var(--color-primary); }
.tab.active::after { background: var(--color-primary); }
.tab__badge {
  font-size: var(--fs-xs);
  background: var(--surface-inset);
  color: var(--text-secondary);
  border-radius: var(--r-pill);
  padding: 1px 7px;
  font-weight: var(--fw-semibold);
}
.tab.active .tab__badge { background: var(--brand-50); color: var(--color-primary); }
[data-theme="dark"] .tab.active .tab__badge { background: var(--surface-2); color: var(--brand-400); }
</style>
