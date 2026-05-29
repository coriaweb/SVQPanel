<template>
  <transition name="modal">
    <div v-if="isOpen" class="modal-overlay" @click.self="close">
      <div class="modal-content" :class="sizeClass" role="dialog" aria-modal="true">
        <div class="modal-header">
          <h5>{{ title }}</h5>
          <button type="button" class="modal-close" @click="close" aria-label="Cerrar">
            <i class="bi bi-x-lg"></i>
          </button>
        </div>
        <div class="modal-body">
          <slot></slot>
        </div>
        <div class="modal-footer" v-if="$slots.footer">
          <slot name="footer"></slot>
        </div>
      </div>
    </div>
  </transition>
</template>

<script>
export default {
  name: 'Modal',
  props: {
    isOpen: { type: Boolean, required: true },
    title: { type: String, required: true },
    size: { type: String, default: 'md', validator: (v) => ['sm', 'md', 'lg', 'xl'].includes(v) },
  },
  emits: ['close'],
  computed: {
    sizeClass() { return this.size !== 'md' ? `modal-${this.size}` : '' },
  },
  watch: {
    isOpen(open) {
      if (open) document.addEventListener('keydown', this.onKey)
      else document.removeEventListener('keydown', this.onKey)
    },
  },
  unmounted() { document.removeEventListener('keydown', this.onKey) },
  methods: {
    close() { this.$emit('close') },
    onKey(e) { if (e.key === 'Escape') this.close() },
  },
}
</script>

<style scoped>
.modal-overlay {
  position: fixed; inset: 0;
  background: rgba(10, 12, 20, 0.55);
  backdrop-filter: blur(3px);
  display: flex; align-items: center; justify-content: center;
  z-index: 1050;
  padding: var(--sp-4);
}
.modal-content {
  background: var(--surface);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: var(--r-xl);
  box-shadow: var(--shadow-lg);
  width: 100%; max-width: 520px;
  max-height: 90vh; overflow-y: auto;
}
.modal-content.modal-lg { max-width: 820px; }
.modal-content.modal-xl { max-width: 1120px; }
.modal-content.modal-sm { max-width: 380px; }

.modal-header {
  padding: var(--sp-5);
  border-bottom: 1px solid var(--border);
  display: flex; justify-content: space-between; align-items: center;
}
.modal-header h5 {
  margin: 0; font-size: var(--fs-lg); font-weight: var(--fw-semibold); color: var(--text);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: calc(100% - 2.5rem);
}
.modal-body { padding: var(--sp-5); }
.modal-footer {
  padding: var(--sp-4) var(--sp-5);
  border-top: 1px solid var(--border);
  display: flex; gap: var(--sp-2); justify-content: flex-end;
  background: var(--surface-2);
}
.modal-close {
  width: 32px; height: 32px;
  background: transparent; border: none; cursor: pointer;
  color: var(--text-muted); border-radius: var(--r-sm);
  display: grid; place-items: center; font-size: 15px; flex-shrink: 0;
  transition: background var(--t-fast), color var(--t-fast);
}
.modal-close:hover { background: var(--surface-inset); color: var(--text); }

/* Transición */
.modal-enter-active, .modal-leave-active { transition: opacity var(--t-base) var(--ease); }
.modal-enter-active .modal-content, .modal-leave-active .modal-content { transition: transform var(--t-base) var(--ease-out), opacity var(--t-base) var(--ease); }
.modal-enter-from, .modal-leave-to { opacity: 0; }
.modal-enter-from .modal-content, .modal-leave-to .modal-content { transform: scale(.96) translateY(8px); opacity: 0; }
</style>
