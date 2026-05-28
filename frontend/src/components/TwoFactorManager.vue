<template>
  <div class="twofa-manager">

    <!-- ── Estado: desactivado ── -->
    <template v-if="!status.totp_enabled">
      <div v-if="step === 'idle'" class="text-center py-3">
        <i class="bi bi-shield-slash text-secondary" style="font-size:2.5rem"></i>
        <p class="mt-2 text-muted">El doble factor de autenticación no está activado.</p>
        <button class="btn btn-primary" @click="startSetup" :disabled="loading">
          <i class="bi bi-shield-lock me-1"></i> Activar 2FA
        </button>
      </div>

      <!-- paso QR -->
      <div v-if="step === 'qr'">
        <p class="text-muted mb-3">
          Escanea el código QR con tu aplicación autenticadora (<strong>Google Authenticator</strong>,
          <strong>Authy</strong>, <strong>2FAS</strong>, etc.) y luego introduce el código de 6 dígitos.
        </p>

        <div class="text-center mb-3">
          <img :src="setupData.qr_code" alt="QR 2FA" class="qr-img" />
        </div>

        <div class="mb-3">
          <label class="form-label text-muted small">O introduce manualmente la clave:</label>
          <div class="input-group input-group-sm">
            <input type="text" class="form-control font-monospace" :value="setupData.secret" readonly />
            <button class="btn btn-outline-secondary" @click="copySecret" title="Copiar">
              <i class="bi bi-clipboard"></i>
            </button>
          </div>
        </div>

        <div class="mb-3">
          <label class="form-label">Código de verificación</label>
          <input
            v-model="verifyCode"
            type="text"
            inputmode="numeric"
            pattern="[0-9]{6}"
            maxlength="6"
            class="form-control text-center"
            style="font-size:1.3rem;letter-spacing:0.35rem"
            placeholder="000000"
            autocomplete="one-time-code"
            ref="verifyInput"
          />
        </div>

        <div v-if="errorMsg" class="alert alert-danger py-2">
          <i class="bi bi-exclamation-circle me-1"></i>{{ errorMsg }}
        </div>

        <div class="d-flex gap-2">
          <button class="btn btn-success flex-grow-1" @click="enable2FA"
            :disabled="loading || verifyCode.length !== 6">
            <span v-if="loading" class="spinner-border spinner-border-sm me-1"></span>
            <i v-else class="bi bi-check-lg me-1"></i>
            Activar
          </button>
          <button class="btn btn-outline-secondary" @click="cancelSetup">Cancelar</button>
        </div>
      </div>
    </template>

    <!-- ── Estado: activado ── -->
    <template v-else>
      <div v-if="step === 'idle'">
        <div class="d-flex align-items-center gap-3 mb-3">
          <i class="bi bi-shield-fill-check text-success" style="font-size:2rem"></i>
          <div>
            <strong>2FA activado</strong>
            <div class="text-muted small" v-if="status.totp_enabled_at">
              Desde {{ formatDate(status.totp_enabled_at) }}
            </div>
          </div>
        </div>
        <button class="btn btn-outline-danger btn-sm" @click="step = 'disable'">
          <i class="bi bi-shield-slash me-1"></i> Desactivar 2FA
        </button>
      </div>

      <!-- paso desactivar -->
      <div v-if="step === 'disable'">
        <p class="text-muted mb-3">
          Introduce el código actual de tu autenticador para confirmar la desactivación.
        </p>
        <div class="mb-3">
          <label class="form-label">Código de verificación</label>
          <input
            v-model="disableCode"
            type="text"
            inputmode="numeric"
            pattern="[0-9]{6}"
            maxlength="6"
            class="form-control text-center"
            style="font-size:1.3rem;letter-spacing:0.35rem"
            placeholder="000000"
            ref="disableInput"
          />
        </div>

        <div v-if="errorMsg" class="alert alert-danger py-2">
          <i class="bi bi-exclamation-circle me-1"></i>{{ errorMsg }}
        </div>

        <div class="d-flex gap-2">
          <button class="btn btn-danger flex-grow-1" @click="disable2FA"
            :disabled="loading || disableCode.length !== 6">
            <span v-if="loading" class="spinner-border spinner-border-sm me-1"></span>
            <i v-else class="bi bi-shield-slash me-1"></i>
            Desactivar
          </button>
          <button class="btn btn-outline-secondary" @click="step = 'idle'; disableCode = ''; errorMsg = ''">
            Cancelar
          </button>
        </div>
      </div>
    </template>

  </div>
</template>

<script>
import { ref, onMounted, nextTick } from 'vue'
import api from '../services/api'

export default {
  name: 'TwoFactorManager',
  emits: ['status-changed'],
  setup(_, { emit }) {
    const loading     = ref(false)
    const step        = ref('idle')   // 'idle' | 'qr' | 'disable'
    const status      = ref({ totp_enabled: false, totp_enabled_at: null })
    const setupData   = ref(null)
    const verifyCode  = ref('')
    const disableCode = ref('')
    const errorMsg    = ref('')
    const verifyInput = ref(null)
    const disableInput = ref(null)

    const loadStatus = async () => {
      try {
        status.value = await api.get2FAStatus()
      } catch {
        status.value = { totp_enabled: false, totp_enabled_at: null }
      }
    }

    onMounted(loadStatus)

    const startSetup = async () => {
      errorMsg.value = ''
      loading.value  = true
      try {
        setupData.value = await api.setup2FA()
        step.value      = 'qr'
        verifyCode.value = ''
        await nextTick()
        verifyInput.value?.focus()
      } catch (e) {
        errorMsg.value = e.message || 'Error al generar el código QR'
      } finally {
        loading.value = false
      }
    }

    const enable2FA = async () => {
      if (verifyCode.value.length !== 6) return
      errorMsg.value = ''
      loading.value  = true
      try {
        await api.enable2FA(verifyCode.value)
        await loadStatus()
        step.value       = 'idle'
        verifyCode.value = ''
        emit('status-changed', true)
      } catch (e) {
        errorMsg.value   = e.message || 'Código incorrecto'
        verifyCode.value = ''
        await nextTick()
        verifyInput.value?.focus()
      } finally {
        loading.value = false
      }
    }

    const cancelSetup = () => {
      step.value       = 'idle'
      verifyCode.value = ''
      errorMsg.value   = ''
      setupData.value  = null
    }

    const disable2FA = async () => {
      if (disableCode.value.length !== 6) return
      errorMsg.value = ''
      loading.value  = true
      try {
        await api.disable2FA(disableCode.value)
        await loadStatus()
        step.value        = 'idle'
        disableCode.value = ''
        emit('status-changed', false)
      } catch (e) {
        errorMsg.value    = e.message || 'Código incorrecto'
        disableCode.value = ''
        await nextTick()
        disableInput.value?.focus()
      } finally {
        loading.value = false
      }
    }

    const copySecret = () => {
      navigator.clipboard?.writeText(setupData.value?.secret || '')
    }

    const formatDate = (iso) => {
      if (!iso) return ''
      return new Date(iso).toLocaleDateString('es-ES', { dateStyle: 'long' })
    }

    return {
      loading, step, status, setupData,
      verifyCode, disableCode, errorMsg,
      verifyInput, disableInput,
      startSetup, enable2FA, cancelSetup, disable2FA,
      copySecret, formatDate,
    }
  }
}
</script>

<style scoped>
.qr-img {
  max-width: 200px;
  border: 1px solid #dee2e6;
  border-radius: 8px;
  padding: 8px;
}
</style>
