<template>
  <div class="cpick">
    <div class="cpick__chips">
      <span v-for="cc in modelValue" :key="cc" class="cpick__chip">
        <span class="cpick__flag">{{ flag(cc) }}</span>{{ nameOf(cc) }}
        <button type="button" class="cpick__x" :aria-label="`Quitar ${nameOf(cc)}`" @click="remove(cc)">
          <i class="bi bi-x"></i>
        </button>
      </span>
      <span v-if="!modelValue.length" class="cpick__empty">{{ placeholder }}</span>
    </div>
    <div class="cpick__add">
      <div class="cpick__search">
        <input class="svq-input" v-model="q" :disabled="disabled || !countries.length"
               :placeholder="countries.length ? 'Buscar país…' : 'Preparando la lista de países…'"
               @keydown.enter.prevent="pickFirst" @keydown.esc="q = ''" />
        <ul v-if="q && matches.length" class="cpick__list">
          <li v-for="c in matches" :key="c.cc">
            <button type="button" @click="add(c.cc)"><span class="cpick__flag">{{ flag(c.cc) }}</span>{{ c.name }}
              <small>{{ c.cc }}</small></button>
          </li>
        </ul>
      </div>
      <button type="button" class="cpick__quick" :disabled="disabled || !countries.length" @click="addEU">
        + Unión Europea
      </button>
    </div>
  </div>
</template>

<script>
import { ref, computed } from 'vue'

const EU = ['AT', 'BE', 'BG', 'CY', 'CZ', 'DE', 'DK', 'EE', 'ES', 'FI', 'FR', 'GR', 'HR', 'HU',
  'IE', 'IT', 'LT', 'LU', 'LV', 'MT', 'NL', 'PL', 'PT', 'RO', 'SE', 'SI', 'SK']

export default {
  name: 'CountryPicker',
  props: {
    modelValue: { type: Array, default: () => [] },
    countries: { type: Array, default: () => [] },   // [{ cc, name }]
    placeholder: { type: String, default: 'Ningún país elegido' },
    disabled: { type: Boolean, default: false },
  },
  emits: ['update:modelValue'],
  setup(props, { emit }) {
    const q = ref('')
    const byCc = computed(() => Object.fromEntries(props.countries.map(c => [c.cc, c.name])))
    const nameOf = (cc) => byCc.value[cc] || cc
    // Bandera a partir del código (indicadores regionales); en Windows se ve como letras.
    const flag = (cc) => String.fromCodePoint(...[...cc.toUpperCase()].map(ch => 0x1F1A5 + ch.charCodeAt(0)))
    const norm = (s) => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()
    const matches = computed(() => {
      const t = norm(q.value.trim())
      if (!t) return []
      return props.countries
        .filter(c => !props.modelValue.includes(c.cc) && (norm(c.name).includes(t) || c.cc.toLowerCase() === t))
        .slice(0, 8)
    })
    const set = (list) => emit('update:modelValue', [...new Set(list)].sort())
    const add = (cc) => { set([...props.modelValue, cc]); q.value = '' }
    const remove = (cc) => set(props.modelValue.filter(x => x !== cc))
    const pickFirst = () => { if (matches.value.length) add(matches.value[0].cc) }
    const addEU = () => set([...props.modelValue, ...EU.filter(cc => byCc.value[cc])])
    return { q, matches, nameOf, flag, add, remove, pickFirst, addEU }
  },
}
</script>

<style scoped>
.cpick { display: flex; flex-direction: column; gap: var(--sp-2); }
.cpick__chips { display: flex; flex-wrap: wrap; gap: .35rem; min-height: 1.9rem; align-items: center; }
.cpick__chip { display: inline-flex; align-items: center; gap: .3rem; padding: .15rem .25rem .15rem .55rem;
  background: var(--ac-soft); color: var(--text); border-radius: 999px; font-size: .8rem; }
.cpick__flag { font-size: .95rem; line-height: 1; }
.cpick__x { border: 0; background: transparent; color: var(--text-muted); cursor: pointer; padding: 0 .15rem; line-height: 1; }
.cpick__x:hover { color: var(--danger); }
.cpick__empty { font-size: .8rem; color: var(--text-muted); }
.cpick__add { display: flex; gap: var(--sp-2); align-items: flex-start; }
.cpick__search { position: relative; flex: 1; max-width: 340px; }
.cpick__list { position: absolute; z-index: 20; top: calc(100% + 4px); left: 0; right: 0; margin: 0; padding: .25rem;
  list-style: none; background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-md, 10px);
  box-shadow: var(--shadow-md, 0 6px 20px rgba(0,0,0,.12)); }
.cpick__list button { display: flex; align-items: center; gap: .45rem; width: 100%; padding: .35rem .5rem; border: 0;
  background: transparent; color: var(--text); text-align: left; border-radius: var(--r-sm, 6px); cursor: pointer; font-size: .85rem; }
.cpick__list button:hover { background: var(--surface-2); }
.cpick__list small { margin-left: auto; color: var(--text-muted); }
.cpick__quick { border: 1px dashed var(--border); background: transparent; color: var(--text-secondary);
  border-radius: var(--r-sm, 6px); padding: .4rem .7rem; font-size: .8rem; cursor: pointer; white-space: nowrap; }
.cpick__quick:hover:not(:disabled) { border-color: var(--ac); color: var(--ac); }
</style>
