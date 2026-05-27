<template>
  <div>
    <div class="d-flex justify-content-between small mb-1">
      <span class="font-monospace">{{ formatMB(used) }}</span>
      <span class="text-muted">
        <template v-if="quota === 0">/ ∞</template>
        <template v-else>/ {{ formatMB(quota) }}</template>
      </span>
    </div>
    <div class="progress" style="height: 6px;">
      <div class="progress-bar" :class="barColor" role="progressbar"
           :style="{width: percent + '%'}"
           :aria-valuenow="percent" aria-valuemin="0" aria-valuemax="100"></div>
    </div>
    <div v-if="quota > 0" class="small text-muted mt-1">
      {{ percent }}%
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  used:  { type: Number, default: 0 },
  quota: { type: Number, default: 0 },   // 0 = ilimitado
})

const percent = computed(() => {
  if (!props.quota) return 0
  return Math.min(100, Math.round((props.used / props.quota) * 100))
})

const barColor = computed(() => {
  if (!props.quota) return 'bg-secondary'
  if (percent.value >= 95) return 'bg-danger'
  if (percent.value >= 80) return 'bg-warning'
  return 'bg-success'
})

function formatMB(mb) {
  if (!mb) return '0 MB'
  if (mb >= 1024 * 1024) return (mb / (1024 * 1024)).toFixed(1) + ' TB'
  if (mb >= 1024) return (mb / 1024).toFixed(mb >= 10240 ? 0 : 1) + ' GB'
  return mb + ' MB'
}
</script>
