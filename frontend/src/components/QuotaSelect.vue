<template>
  <div class="quota-select">
    <select class="form-select" v-model="choice">
      <option :value="0">Sin límite</option>
      <option v-for="p in presets" :key="p" :value="p">{{ label(p) }}</option>
      <option value="custom">Personalizado…</option>
    </select>
    <SizeInput v-if="choice === 'custom'" v-model="custom" class="mt-2" />
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import SizeInput from './SizeInput.vue'

// v-model SIEMPRE en MB (el backend no cambia). 0 = sin límite.
const props = defineProps({
  modelValue: { type: Number, default: 1024 },
  presets: { type: Array, default: () => [256, 512, 1024, 2048, 5120, 10240, 20480, 51200, 102400] },
})
const emit = defineEmits(['update:modelValue'])

const label = (mb) => (mb >= 1024 && mb % 1024 === 0) ? `${mb / 1024} GB` : `${mb} MB`

// Un valor que no cae en ningún preset (buzón migrado, cuota puesta a mano)
// debe abrir el modo personalizado, no dejar el select en blanco.
const isPreset = (mb) => mb === 0 || props.presets.includes(mb)

const choice = ref(isPreset(props.modelValue) ? props.modelValue : 'custom')
const custom = ref(props.modelValue)

watch(choice, (c) => {
  if (c === 'custom') emit('update:modelValue', custom.value)
  else emit('update:modelValue', c)
})
watch(custom, (v) => {
  if (choice.value === 'custom') emit('update:modelValue', v)
})

// Si el valor llega desde fuera (abrir el modal de editar otro buzón), resincronizar.
watch(() => props.modelValue, (mb) => {
  if (choice.value === 'custom' && mb === custom.value) return
  if (choice.value === mb) return
  if (isPreset(mb)) {
    choice.value = mb
  } else {
    custom.value = mb
    choice.value = 'custom'
  }
})
</script>
