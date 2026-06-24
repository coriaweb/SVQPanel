<template>
  <div class="pf">
    <div class="pf-input-row">
      <div class="pf-input-wrap">
        <input
          :type="visible ? 'text' : 'password'"
          class="pf-input"
          :value="modelValue"
          :placeholder="placeholder"
          :autocomplete="autocomplete"
          @input="$emit('update:modelValue', $event.target.value)"
        />
        <button type="button" class="pf-eye" :title="visible ? 'Ocultar' : 'Mostrar'" @click="visible = !visible">
          <i class="bi" :class="visible ? 'bi-eye-slash' : 'bi-eye'"></i>
        </button>
      </div>
      <button type="button" class="pf-gen" title="Generar contraseña segura" @click="generate">
        <i class="bi bi-shuffle"></i> Generar
      </button>
    </div>

    <!-- Medidor de fortaleza -->
    <div v-if="modelValue" class="pf-meter">
      <div class="pf-meter-bar">
        <div class="pf-meter-fill" :class="'pf-str-' + strength.level" :style="{ width: strength.pct + '%' }"></div>
      </div>
      <span class="pf-meter-label" :class="'pf-str-' + strength.level">{{ strength.label }}</span>
    </div>

    <!-- Checklist de requisitos -->
    <ul v-if="showChecklist && (focused || modelValue)" class="pf-reqs">
      <li v-for="req in checks" :key="req.key" :class="{ 'pf-ok': req.ok }">
        <i class="bi" :class="req.ok ? 'bi-check-circle-fill' : 'bi-circle'"></i> {{ req.label }}
      </li>
    </ul>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import api from '../services/api'

const props = defineProps({
  modelValue: { type: String, default: '' },
  placeholder: { type: String, default: 'Contraseña' },
  autocomplete: { type: String, default: 'new-password' },
  showChecklist: { type: Boolean, default: true },
})
const emit = defineEmits(['update:modelValue', 'valid'])

const visible = ref(false)
const focused = ref(false)

// Política (con defaults razonables hasta que cargue la real del servidor).
const policy = ref({
  min_length: 12, require_upper: true, require_lower: true,
  require_digit: true, require_symbol: false,
})

onMounted(async () => {
  try {
    const p = await api.get('/api/settings/password-policy')
    if (p && typeof p === 'object') policy.value = { ...policy.value, ...p }
  } catch (_) { /* usa defaults */ }
})

const checks = computed(() => {
  const v = props.modelValue || ''
  const out = [{ key: 'len', label: `Mínimo ${policy.value.min_length} caracteres`, ok: v.length >= policy.value.min_length }]
  if (policy.value.require_upper) out.push({ key: 'up', label: 'Una mayúscula', ok: /[A-Z]/.test(v) })
  if (policy.value.require_lower) out.push({ key: 'lo', label: 'Una minúscula', ok: /[a-z]/.test(v) })
  if (policy.value.require_digit) out.push({ key: 'di', label: 'Un número', ok: /[0-9]/.test(v) })
  if (policy.value.require_symbol) out.push({ key: 'sy', label: 'Un símbolo', ok: /[^A-Za-z0-9]/.test(v) })
  return out
})

const valid = computed(() => checks.value.every(c => c.ok))
// Emitir validez para que el formulario padre pueda deshabilitar el submit.
watch(valid, v => emit('valid', v), { immediate: true })

const strength = computed(() => {
  const v = props.modelValue || ''
  let score = 0
  if (v.length >= policy.value.min_length) score++
  if (v.length >= policy.value.min_length + 4) score++
  if (/[A-Z]/.test(v) && /[a-z]/.test(v)) score++
  if (/[0-9]/.test(v)) score++
  if (/[^A-Za-z0-9]/.test(v)) score++
  if (!valid.value) return { level: 'weak', label: 'No cumple', pct: Math.min(40, score * 15) }
  if (score >= 5) return { level: 'strong', label: 'Fuerte', pct: 100 }
  if (score >= 4) return { level: 'good', label: 'Buena', pct: 75 }
  return { level: 'ok', label: 'Aceptable', pct: 55 }
})

const SYMBOLS = '!@#$%&*()-_=+[]{}.,?'
function rand(set) { return set[Math.floor((window.crypto.getRandomValues(new Uint32Array(1))[0] / 2 ** 32) * set.length)] }

async function generate() {
  // Preferimos el generador del servidor (respeta la política real con CSPRNG).
  try {
    const r = await api.post('/api/settings/generate-password', {})
    if (r && r.password) { emit('update:modelValue', r.password); visible.value = true; return }
  } catch (_) { /* fallback local */ }
  // Fallback en cliente.
  const p = policy.value
  const required = []
  if (p.require_lower) required.push('abcdefghijklmnopqrstuvwxyz')
  if (p.require_upper) required.push('ABCDEFGHIJKLMNOPQRSTUVWXYZ')
  if (p.require_digit) required.push('0123456789')
  if (p.require_symbol) required.push(SYMBOLS)
  if (!required.length) required.push('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')
  const alphabet = required.join('')
  const n = Math.max(p.min_length, 12)
  let chars = required.map(g => rand(g))
  while (chars.length < n) chars.push(rand(alphabet))
  for (let i = chars.length - 1; i > 0; i--) {
    const j = Math.floor((window.crypto.getRandomValues(new Uint32Array(1))[0] / 2 ** 32) * (i + 1))
    ;[chars[i], chars[j]] = [chars[j], chars[i]]
  }
  emit('update:modelValue', chars.join(''))
  visible.value = true
}
</script>

<style scoped>
.pf { display: flex; flex-direction: column; gap: .5rem; }
.pf-input-row { display: flex; gap: .5rem; }
.pf-input-wrap { position: relative; flex: 1; }
.pf-input {
  width: 100%; background: var(--surface-inset); color: var(--text);
  border: 1px solid var(--border); border-radius: var(--r-sm, 8px);
  padding: .5rem 2.2rem .5rem .7rem; font-size: .9rem; font-family: var(--font-mono, monospace);
}
.pf-input:focus { outline: none; border-color: var(--ac); box-shadow: 0 0 0 3px color-mix(in srgb, var(--ac) 18%, transparent); }
.pf-eye {
  position: absolute; right: .5rem; top: 50%; transform: translateY(-50%);
  background: none; border: none; color: var(--text-muted); cursor: pointer; padding: 0; font-size: 1rem;
}
.pf-gen {
  display: inline-flex; align-items: center; gap: .35rem; white-space: nowrap;
  background: var(--surface-2); color: var(--text); border: 1px solid var(--border);
  border-radius: var(--r-sm, 8px); padding: .5rem .8rem; font-size: .82rem; font-weight: 600; cursor: pointer;
}
.pf-gen:hover { border-color: var(--ac); color: var(--ac); }

.pf-meter { display: flex; align-items: center; gap: .6rem; }
.pf-meter-bar { flex: 1; height: 5px; background: var(--surface-inset); border-radius: 999px; overflow: hidden; }
.pf-meter-fill { height: 100%; border-radius: 999px; transition: width .2s, background .2s; }
.pf-meter-label { font-size: .75rem; font-weight: 600; }
.pf-str-weak   { background: var(--danger);  color: var(--danger); }
.pf-str-ok     { background: var(--warning); color: var(--warning); }
.pf-str-good   { background: var(--info);    color: var(--info); }
.pf-str-strong { background: var(--success); color: var(--success); }

.pf-reqs { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: .3rem .9rem; }
.pf-reqs li { font-size: .76rem; color: var(--text-muted); display: flex; align-items: center; gap: .3rem; }
.pf-reqs li.pf-ok { color: var(--success); }
.pf-reqs li i { font-size: .8rem; }
</style>
