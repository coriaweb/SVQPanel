// Categorías de las plantillas web (orden y etiqueta en los selectores).
// Compartido por el alta de dominio (DomainForm) y la ficha (DomainDetail → Avanzado).
export const TEMPLATE_CATEGORIES = [
  { key: 'cms',        label: 'CMS' },
  { key: 'framework',  label: 'Frameworks' },
  { key: 'ecommerce',  label: 'E-commerce' },
  { key: 'other',      label: 'Otros' },
]

export function parseTemplatePhp(tpl) {
  if (!tpl?.php_ini_overrides) return {}
  try { return JSON.parse(tpl.php_ini_overrides) || {} } catch { return {} }
}
