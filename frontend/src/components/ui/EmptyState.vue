<template>
  <div class="empty">
    <div class="empty__icon"><i class="bi" :class="`bi-${icon}`"></i></div>
    <p class="empty__title">{{ title }}</p>
    <p class="empty__desc" v-if="description">{{ description }}</p>
    <div class="empty__action" v-if="$slots.default"><slot /></div>
  </div>
</template>

<script>
export default {
  name: 'EmptyState',
  props: {
    icon: { type: String, default: 'inbox' },
    title: { type: String, default: 'No hay nada por aquí' },
    description: { type: String, default: '' },
  },
}
</script>

<style scoped>
.empty { text-align: center; padding: var(--sp-10) var(--sp-6); }
.empty__icon {
  width: 64px; height: 64px; margin: 0 auto var(--sp-4);
  display: grid; place-items: center;
  border-radius: var(--r-lg);
  background: var(--surface-inset);
  color: var(--text-muted);
  font-size: 28px;
}
.empty__title { margin: 0; font-size: var(--fs-lg); font-weight: var(--fw-semibold); color: var(--text); }
.empty__desc { margin: var(--sp-2) auto 0; max-width: 380px; color: var(--text-muted); font-size: var(--fs-base); }
.empty__action { margin-top: var(--sp-5); }
</style>
