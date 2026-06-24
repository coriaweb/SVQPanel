<template>
  <div class="size-input">
    <input
      type="number"
      class="form-control form-control-sm size-input__num"
      :min="0"
      :step="unit === 'GB' ? 0.5 : 1"
      v-model.number="amount"
      :placeholder="placeholder"
    />
    <select class="form-select form-select-sm size-input__unit" v-model="unit">
      <option value="MB">MB</option>
      <option value="GB">GB</option>
    </select>
  </div>
</template>

<script setup>
import { ref, watch, computed } from 'vue'

const props = defineProps({
  // v-model SIEMPRE en MB (el backend no cambia). 0 = sin límite.
  modelValue: { type: Number, default: 0 },
  placeholder: { type: String, default: '0 = sin límite' },
})
const emit = defineEmits(['update:modelValue'])

// Unidad por defecto: GB si el valor es un múltiplo "redondo" de 1024 y >= 1 GB.
function defaultUnit(mb) {
  return (mb >= 1024 && mb % 1024 === 0) ? 'GB' : 'MB'
}

const unit = ref(defaultUnit(props.modelValue))
const amount = ref(unit.value === 'GB' ? props.modelValue / 1024 : props.modelValue)

// Convertir a MB para emitir (redondeo a entero: el backend trabaja en MB).
const asMB = computed(() => {
  const v = Number(amount.value) || 0
  return unit.value === 'GB' ? Math.round(v * 1024) : Math.round(v)
})

watch(asMB, v => emit('update:modelValue', v))

// Al cambiar la unidad, reconvertir el número mostrado para no alterar el valor.
watch(unit, (nu, ou) => {
  const v = Number(amount.value) || 0
  if (nu === 'GB' && ou === 'MB') amount.value = +(v / 1024).toFixed(2)
  else if (nu === 'MB' && ou === 'GB') amount.value = Math.round(v * 1024)
})

// Si el valor llega desde fuera (cargar un plan a editar), resincronizar.
watch(() => props.modelValue, (mb) => {
  if (mb === asMB.value) return
  unit.value = defaultUnit(mb)
  amount.value = unit.value === 'GB' ? +(mb / 1024).toFixed(2) : mb
})
</script>

<style scoped>
.size-input { display: flex; gap: .4rem; }
.size-input__num { flex: 1; }
.size-input__unit { width: 4.5rem; flex: 0 0 auto; }
</style>
