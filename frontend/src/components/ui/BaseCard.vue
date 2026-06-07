<template>
  <div class="card" :class="{ 'card--interactive': interactive, 'card--flush': flush }">
    <div class="card__header" v-if="$slots.header || title">
      <div class="card__title-wrap">
        <i v-if="icon" class="bi" :class="`bi-${icon}`"></i>
        <slot name="header">
          <span class="card__title">{{ title }}</span>
        </slot>
      </div>
      <div class="card__actions" v-if="$slots.actions">
        <slot name="actions" />
      </div>
    </div>
    <div class="card__body" :class="{ 'card__body--flush': flush }">
      <slot />
    </div>
    <div class="card__footer" v-if="$slots.footer">
      <slot name="footer" />
    </div>
  </div>
</template>

<script>
export default {
  name: 'BaseCard',
  props: {
    title: { type: String, default: '' },
    icon: { type: String, default: '' },
    interactive: { type: Boolean, default: false },
    flush: { type: Boolean, default: false }, // body sin padding (para tablas/listas)
  },
}
</script>

<style scoped>
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
  transition: box-shadow var(--t-base) var(--ease), border-color var(--t-base) var(--ease), transform var(--t-base) var(--ease);
}
.card--interactive { cursor: pointer; }
.card--interactive:hover {
  box-shadow: var(--shadow-md);
  border-color: var(--border-strong);
  transform: translateY(-2px);
}
.card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  padding: var(--sp-4) var(--sp-5);
  /* Marca SVQ: cabecera con fondo navy oscuro y título/icono naranja,
     igual en tema claro y oscuro. */
  background: var(--svq-navy);
  border-bottom: 1px solid var(--svq-navy);
}
.card__title-wrap { display: flex; align-items: center; gap: var(--sp-2); min-width: 0; }
.card__title-wrap .bi { color: var(--svq-orange); font-size: 16px; }
.card__title { font-size: var(--fs-md); font-weight: var(--fw-semibold); color: var(--svq-orange); }
.card__actions { display: flex; align-items: center; gap: var(--sp-2); flex-shrink: 0; }
/* Botones de la cabecera sobre el fondo navy: legibles en claro y oscuro.
   :deep porque los BaseButton son componentes hijos con estilos scoped propios. */
.card__actions :deep(.btn--ghost) { color: rgba(255, 255, 255, .82); }
.card__actions :deep(.btn--ghost:hover) { background: rgba(255, 255, 255, .12); color: #fff; }
.card__actions :deep(.btn--secondary) {
  background: rgba(255, 255, 255, .1);
  color: #fff;
  border-color: rgba(255, 255, 255, .22);
}
.card__actions :deep(.btn--secondary:hover) { background: rgba(255, 255, 255, .18); }
.card__body { padding: var(--sp-5); }
.card__body--flush { padding: 0; }
.card__footer {
  padding: var(--sp-3) var(--sp-5);
  border-top: 1px solid var(--border);
  background: var(--surface-2);
}
</style>
