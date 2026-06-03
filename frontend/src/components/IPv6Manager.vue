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

          <!-- Sin IP generada todavía -->
          <div v-if="!generatedIP" class="d-grid">
            <button class="btn btn-outline-primary" @click="generateIP" :disabled="generating">
              <span v-if="generating" class="spinner-border spinner-border-sm me-2"></span>
              <i v-else class="bi bi-magic me-2"></i>
              Generar IP disponible del rango
            </button>
          </div>

          <!-- 8 campos separados -->
          <div v-else>
            <div class="ipv6-fields d-flex align-items-center gap-1 flex-wrap">
              <span v-for="(group, i) in groups" :key="i" class="d-flex align-items-center gap-1">
                <input
                  v-model="groups[i]"
                  :readonly="i < fixedGroups"
                  type="text"
                  maxlength="4"
                  class="form-control form-control-sm font-monospace text-center ipv6-group"
                  :class="i < fixedGroups ? 'ipv6-fixed' : 'ipv6-editable'"
                  @input="groups[i] = groups[i].replace(/[^0-9a-fA-F]/g, '').slice(0, 4)"
                />
                <span v-if="i < 7" class="ipv6-sep text-muted">:</span>
              </span>
              <button class="btn btn-outline-secondary btn-sm ms-1" type="button" @click="generateIP" :disabled="generating" title="Regenerar">
                <span v-if="generating" class="spinner-border spinner-border-sm"></span>
                <i v-else class="bi bi-arrow-repeat"></i>
              </button>
            </div>
            <div class="form-text mt-1">
              <i class="bi bi-info-circle me-1"></i>
              Prefijo fijo del rango <code>{{ ipv6Range }}</code> · {{ usedCount }} IPs ya asignadas
            </div>
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
          <button class="btn btn-primary" @click="assignIPv6" :disabled="loading || !isValidIPv6">
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
import { ref, computed, onMounted } from 'vue'
import { useMainStore } from '../stores/useMainStore'
import api from '../services/api'

// Expande una IPv6 a 8 grupos de 4 hex (forma completa)
function expandIPv6(addr) {
  // Manejar :: expansion
  let full = addr
  if (full.includes('::')) {
    const sides = full.split('::')
    const left = sides[0] ? sides[0].split(':') : []
    const right = sides[1] ? sides[1].split(':') : []
    const missing = 8 - left.length - right.length
    full = [...left, ...Array(missing).fill('0'), ...right].join(':')
  }
  return full.split(':').map(g => g.padStart(4, '0'))
}

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
    const fixedGroups = ref(4)  // grupos readonly según prefijo

    // Los 8 grupos editables
    const groups = ref(['0000','0000','0000','0000','0000','0000','0000','0000'])

    const form = ref({ network_interface: 'eth0' })

    // IP compuesta desde los grupos
    const composedIPv6 = computed(() =>
      groups.value.map(g => g || '0').join(':')
    )

    const isValidIPv6 = computed(() => {
      return groups.value.every(g => /^[0-9a-fA-F]{1,4}$/.test(g))
    })

    const generateIP = async () => {
      generating.value = true
      ipv6NotConfigured.value = false
      try {
        const exclude = generatedIP.value ? composedIPv6.value : null
        const data = await api.getNextIPv6(exclude)
        const expanded = expandIPv6(data.next_ipv6)
        groups.value = expanded
        form.value.network_interface = data.network_interface || 'eth0'
        ipv6Range.value = data.range
        usedCount.value = data.used_count

        // Calcular cuántos grupos son fijos según el prefijo del rango
        const prefix = parseInt(data.range.split('/')[1] || '64')
        fixedGroups.value = Math.floor(prefix / 16)

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
          ipv6_address: composedIPv6.value,
          network_interface: form.value.network_interface
        })
        currentIPv6.value = composedIPv6.value
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
      groups.value = ['0000','0000','0000','0000','0000','0000','0000','0000']
      form.value = { network_interface: 'eth0' }
    }

    onMounted(async () => {
      if (!currentIPv6.value) {
        await generateIP()
      }
    })

    return {
      loading, generating, confirmRemove, ipv6NotConfigured,
      currentIPv6, generatedIP, ipv6Range, usedCount,
      fixedGroups, groups, form,
      composedIPv6, isValidIPv6,
      generateIP, assignIPv6, removeIPv6, reset
    }
  }
}
</script>

<style scoped>
.ipv6-group {
  width: 4.2rem;
  padding: 0.25rem 0.3rem;
  letter-spacing: 0.05em;
}
.ipv6-fixed {
  background-color: var(--bs-secondary-bg, #e9ecef);
  color: var(--bs-secondary-color, #6c757d);
  cursor: default;
}
.ipv6-editable {
  background-color: var(--bs-body-bg, #fff);
}
.ipv6-sep {
  font-family: monospace;
  font-size: 1.1rem;
  user-select: none;
}
</style>
