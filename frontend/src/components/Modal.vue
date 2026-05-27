<template>
  <div v-if="isOpen" class="modal-overlay" @click.self="close">
    <div class="modal-content" :class="sizeClass">
      <div class="modal-header">
        <h5>{{ title }}</h5>
        <button type="button" class="btn-close" @click="close"></button>
      </div>
      <div class="modal-body">
        <slot></slot>
      </div>
      <div class="modal-footer" v-if="$slots.footer">
        <slot name="footer"></slot>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'Modal',
  props: {
    isOpen: {
      type: Boolean,
      required: true
    },
    title: {
      type: String,
      required: true
    },
    size: {
      type: String,
      default: 'md',
      validator: (v) => ['sm', 'md', 'lg', 'xl'].includes(v)
    }
  },
  emits: ['close'],
  computed: {
    sizeClass() {
      return this.size !== 'md' ? `modal-${this.size}` : ''
    }
  },
  methods: {
    close() {
      this.$emit('close')
    }
  }
}
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1050;
}

.modal-content {
  background: white;
  border-radius: 0.5rem;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.2);
  width: 90%;
  max-width: 500px;
  max-height: 90vh;
  overflow-y: auto;
  animation: slideIn 0.3s ease-out;
}

.modal-content.modal-lg  { max-width: 800px; }
.modal-content.modal-xl  { max-width: 1100px; }
.modal-content.modal-sm  { max-width: 360px; }

@keyframes slideIn {
  from {
    transform: translateY(-50px);
    opacity: 0;
  }
  to {
    transform: translateY(0);
    opacity: 1;
  }
}

.modal-header {
  padding: 1.25rem;
  border-bottom: 1px solid #dee2e6;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.modal-header h5 {
  margin: 0;
  font-size: 1.25rem;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: calc(100% - 2rem);
}

.modal-body {
  padding: 1.25rem;
}

.modal-footer {
  padding: 1.25rem;
  border-top: 1px solid #dee2e6;
  display: flex;
  gap: 0.5rem;
  justify-content: flex-end;
}

.btn-close {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 1.5rem;
  color: #6c757d;
  flex-shrink: 0;
}

.btn-close:hover {
  color: #000;
}
</style>
