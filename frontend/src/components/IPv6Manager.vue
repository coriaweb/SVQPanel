<template>
  <div>
    <div v-if="!showForm" class="ipv6-info">
      <div v-if="ipv6" class="alert alert-success">
        <i class="bi bi-shield-check"></i>
        <strong>IPv6 Asignada</strong>
        <div class="mt-2 small">
          <p class="mb-0">
            <strong>Dirección:</strong> <code>{{ ipv6.ipv6_address }}</code><br>
            <strong>Interfaz:</strong> {{ ipv6.network_interface }}<br>
            <strong>Estado:</strong> {{ ipv6.is_active ? 'Activa' : 'Inactiva' }}
          </p>
        </div>
        <div class="mt-3 d-flex gap-2">
          <button class="btn btn-danger btn-sm" @click="showRemoveConfirm = true" :disabled="loading">
            Remover
          </button>
        </div>
      </div>
      <div v-else class="alert alert-info">
        <i class="bi bi-shuffle"></i>
        <strong>Sin IPv6 Asignada</strong>
        <p class="mt-2 mb-0">Este dominio no tiene una dirección IPv6 configurada.</p>
        <button class="btn btn-primary btn-sm mt-3" @click="showForm = true" :disabled="loading">
          <i class="bi bi-plus-circle"></i> Asignar IPv6
        </button>
      </div>

      <div v-if="showRemoveConfirm" class="alert alert-warning mt-3">
        <p class="mb-2">¿Está seguro de que desea remover la dirección IPv6?</p>
        <div class="d-flex gap-2">
          <button class="btn btn-danger btn-sm" @click="removeIPv6" :disabled="loading">
            Confirmar Remoción
          </button>
          <button class="btn btn-secondary btn-sm" @click="showRemoveConfirm = false" :disabled="loading">
            Cancelar
          </button>
        </div>
      </div>
    </div>

    <div v-else class="ipv6-form">
      <div class="mb-3">
        <label for="ipv6_address" class="form-label">Dirección IPv6</label>
        <input
          id="ipv6_address"
          v-model="form.ipv6_address"
          type="text"
          class="form-control"
          placeholder="2001:db8::1"
          required
        />
        <small class="text-muted">Ej: 2001:db8::1 o 2001:db8::/64</small>
      </div>

      <div class="mb-3">
        <label for="network_interface" class="form-label">Interfaz de Red</label>
        <select
          id="network_interface"
          v-model="form.network_interface"
          class="form-select"
          required
        >
          <option value="">Selecciona interfaz</option>
          <option value="eth0">eth0</option>
          <option value="eth1">eth1</option>
          <option value="ens0">ens0</option>
          <option value="ens1">ens1</option>
        </select>
      </div>

      <div class="alert alert-info">
        <small>
          <i class="bi bi-info-circle"></i>
          La interfaz debe existir en el servidor. Verifica con <code>ip link show</code>.
        </small>
      </div>

      <div class="d-flex gap-2">
        <button class="btn btn-primary" @click="assignIPv6" :disabled="loading">
          <span v-if="loading" class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>
          Asignar IPv6
        </button>
        <button class="btn btn-secondary" @click="showForm = false" :disabled="loading">
          Cancelar
        </button>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, onMounted } from 'vue'
import { useMainStore } from '../stores/useMainStore'
import api from '../services/api'

export default {
  name: 'IPv6Manager',
  props: {
    domain: {
      type: Object,
      required: true
    }
  },
  emits: ['reload'],
  setup(props, { emit }) {
    const store = useMainStore()
    const loading = ref(false)
    const showForm = ref(false)
    const showRemoveConfirm = ref(false)
    const ipv6 = ref(null)

    const form = ref({
      ipv6_address: '',
      network_interface: 'eth0'
    })

    const loadIPv6 = async () => {
      try {
        const data = await api.getIPv6(props.domain.id)
        ipv6.value = data
      } catch (error) {
        ipv6.value = null
      }
    }

    const assignIPv6 = async () => {
      loading.value = true
      try {
        await api.assignIPv6(props.domain.id, {
          ipv6_address: form.value.ipv6_address,
          network_interface: form.value.network_interface
        })
        store.showNotification('IPv6 asignada exitosamente', 'success')
        showForm.value = false
        form.value = { ipv6_address: '', network_interface: 'eth0' }
        await loadIPv6()
        emit('reload')
      } catch (error) {
        store.showNotification('Error al asignar IPv6: ' + error.message, 'danger')
      } finally {
        loading.value = false
      }
    }

    const removeIPv6 = async () => {
      loading.value = true
      try {
        await api.deleteIPv6(props.domain.id)
        store.showNotification('IPv6 removida', 'success')
        ipv6.value = null
        showRemoveConfirm.value = false
        emit('reload')
      } catch (error) {
        store.showNotification('Error al remover IPv6: ' + error.message, 'danger')
      } finally {
        loading.value = false
      }
    }

    onMounted(loadIPv6)

    return {
      ipv6,
      form,
      loading,
      showForm,
      showRemoveConfirm,
      assignIPv6,
      removeIPv6
    }
  }
}
</script>

<style scoped>
.ipv6-info {
  padding: 1rem;
  border-radius: 0.5rem;
  background-color: #f8f9fa;
}

.ipv6-form {
  padding: 1rem;
  border-radius: 0.5rem;
  background-color: #f0f8ff;
  border-left: 4px solid #0d6efd;
}

code {
  background-color: #f5f5f5;
  padding: 0.2rem 0.4rem;
  border-radius: 0.25rem;
  font-family: 'Courier New', monospace;
}
</style>
