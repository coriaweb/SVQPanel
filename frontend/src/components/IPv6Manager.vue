<template>
  <div>

    <!-- Ya tiene IPv6 asignada -->
    <template v-if="currentIPv6">
      <div class="alert alert-success d-flex align-items-start gap-3">
        <i class="bi bi-shield-check fs-4 text-success mt-1"></i>
        <div class="flex-fill">
          <strong>IPv6 asignada</strong>
          <div class="mt-2 font-monospace bg-dark text-success rounded p-2">
            {{ currentIPv6 }}
          </div>
        </div>
      </div>
      <button class="btn btn-outline-danger btn-sm" @click="confirmRemove = true" :disabled="loading">
        <i class="bi bi-x-circle me-1"></i> Quitar IPv6
      </button>

      <div v-if="confirmRemove" class="alert alert-warning mt-3">
        <p class="mb-2">¿Quitar la dirección IPv6 de este dominio?</p>
        <div class="d-flex gap-2">
          <button class="btn btn-danger btn-sm" @click="removeIPv6" :disabled="loading">
            <span v-if="loading" class="spinner-border spinner-border-sm me-1"></span>
            Confirmar
          </button>
          <button class="btn btn-secondary btn-sm" @click="confirmRemove = false">Cancelar</button>
        </div>
      </div>
    </template>

    <!-- Sin IPv6 -->
    <template v-else>

      <!-- IPv6 no configurado en el panel -->
      <div v-if="ipv6NotConfigured" class="alert alert-warning">
        <i class="bi bi-exclamation-triangle me-2"></i>
        <strong>IPv6 no configurado.</strong>
        <p class="mb-0 mt-1 small">
          Ve a <strong>Configuración</strong> y define el rango IPv6 del servidor antes de asignar IPs.
        </p>
      </div>

      <!-- Formulario de asignación -->
      <div v-else>
        <div class="mb-3">
          <label class="form-label fw-bold">Dirección IPv6</label>

          <!-- IP auto-generada -->
          <div v-if="generatedIP" class="input-group mb-2">
            <span class="input-group-text bg-success text-white">
              <i class="bi bi-magic"></i>
            </span>
            <input
              v-model="form.ipv6_address"
              type="text"
              class="form-control font-monospace"
              placeholder="2a01:4f8:1:2::1"
            />
            <button class="btn btn-outline-secondary" type="button" @click="generateIP" :disabled="generating">
              <span v-if="generating" class="spinner-border spinner-border-sm"></span>
              <i v-else class="bi bi-arrow-repeat"></i>
            </button>
          </div>

          <!-- Sin IP generada todavía -->
          <div v-else class="d-grid">
            <button class="btn btn-outline-primary" @click="generateIP" :disabled="generating">
              <span v-if="generating" class="spinner-border spinner-border-sm me-2"></span>
              <i v-else class="bi bi-magic me-2"></i>
              Generar IP disponible del rango
            </button>
          </div>

          <div v-if="generatedIP" class="form-text">
            <i class="bi bi-info-circle me-1"></i>
            IP del rango <code>{{ ipv6Range }}</code> · {{ usedCount }} IPs ya asignadas
          </div>
        </div>

        <div v-if="generatedIP" class="mb-3">
          <label class="form-label">Interfaz de red</label>
          <input
            v-model="form.network_interface"
            type="text"
            class="form-control font-monospace"
            placeholder="eth0"
          />
          <div class="form-text">Interfaz configurada en Ajustes del panel.</div>
        </div>

        <div v-if="generatedIP" class="d-flex gap-2">
          <button class="btn btn-primary" @click="assignIPv6" :disabled="loading || !form.ipv6_address">
            <span v-if="loading" class="spinner-border spinner-border-sm me-2"></span>
            <i v-else class="bi bi-lightning me-1"></i>
            Asignar IPv6
          </button>
          <button class="btn btn-outline-secondary" @click="reset">Cancelar</button>
        </div>
      </div>
    </template>

  </div>
</template>

<script>
import { ref, onMounted } from 'vue'
import { useMainStore } from '../stores/useMainStore'
import api from '../services/api'

export default {
  name: 'IPv6Manager',
  props: {
    domain: { type: Object, required: true }
  },
  emits: ['reload'],
  setup(props, { emit }) {
    const store = useMainStore()
    const loading = ref(false)
    const generating = ref(false)
    const confirmRemove = ref(false)
    const ipv6NotConfigured = ref(false)

    const currentIPv6 = ref(props.domain.ipv6 || null)
    const generatedIP = ref(false)
    const ipv6Range = ref('')
    const usedCount = ref(0)

    const form = ref({
      ipv6_address: '',
      network_interface: 'eth0'
    })

    const generateIP = async () => {
      generating.value = true
      ipv6NotConfigured.value = false
      try {
        const data = await api.getNextIPv6()
        form.value.ipv6_address = data.next_ipv6
        form.value.network_interface = data.network_interface || 'eth0'
        ipv6Range.value = data.range
        usedCount.value = data.used_count
        generatedIP.value = true
      } catch (e) {
        if (e.message?.includes('no está configurado') || e.message?.includes('configurado en el panel')) {
          ipv6NotConfigured.value = true
        } else {
          store.showNotification('Error al generar IPv6: ' + e.message, 'danger')
        }
      } finally {
        generating.value = false
      }
    }

    const assignIPv6 = async () => {
      loading.value = true
      try {
        await api.assignIPv6(props.domain.id, {
          ipv6_address: form.value.ipv6_address,
          network_interface: form.value.network_interface
        })
        currentIPv6.value = form.value.ipv6_address
        store.showNotification('IPv6 asignada correctamente', 'success')
        generatedIP.value = false
        emit('reload')
      } catch (e) {
        store.showNotification('Error al asignar IPv6: ' + e.message, 'danger')
      } finally {
        loading.value = false
      }
    }

    const removeIPv6 = async () => {
      loading.value = true
      try {
        await api.deleteIPv6(props.domain.id)
        currentIPv6.value = null
        confirmRemove.value = false
        store.showNotification('IPv6 eliminada', 'success')
        emit('reload')
      } catch (e) {
        store.showNotification('Error al quitar IPv6: ' + e.message, 'danger')
      } finally {
        loading.value = false
      }
    }

    const reset = () => {
      generatedIP.value = false
      form.value = { ipv6_address: '', network_interface: 'eth0' }
    }

    // Al abrir, si no tiene IPv6 intenta generar una automáticamente
    onMounted(async () => {
      if (!currentIPv6.value) {
        await generateIP()
      }
    })

    return {
      loading, generating, confirmRemove, ipv6NotConfigured,
      currentIPv6, generatedIP, ipv6Range, usedCount, form,
      generateIP, assignIPv6, removeIPv6, reset
    }
  }
}
</script>
