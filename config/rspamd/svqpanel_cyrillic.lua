-- SVQPanel — penaliza correo con cuerpo en alfabeto CIRÍLICO (ruso/ucraniano).
-- NO editar a mano.
--
-- Motivo: el spam de formularios de contacto (y bastante spam directo) llega en
-- cirílico a negocios españoles, que JAMÁS reciben correo legítimo así. Sumamos
-- peso suficiente para mandarlo a Junk (no rechazo: si alguna vez llega algo
-- legítimo en ruso, queda recuperable en Junk, no se pierde).
--
-- Método robusto: cuenta caracteres cirílicos (U+0400–U+04FF, que en UTF-8 son
-- bytes 0xD0/0xD1 seguidos de continuación) en el texto del cuerpo. Si superan
-- un umbral, marca. No depende del detector de idiomas (poco fiable).

local N = 'SVQPANEL_CYRILLIC_BODY'
local MIN_CYR = 15   -- nº mínimo de caracteres cirílicos para considerarlo

rspamd_config:register_symbol({
  name = N,
  score = 6.0,
  description = 'Cuerpo con texto en alfabeto cirílico (spam típico en webs ES)',
  group = 'svqpanel',
  callback = function(task)
    local parts = task:get_text_parts()
    if not parts then return false end
    for _, part in ipairs(parts) do
      local content = part:get_content()
      if content then
        local s = tostring(content)
        -- UTF-8 del bloque cirílico básico (U+0400–U+04FF): byte prefijo 0xD0
        -- (\208) o 0xD1 (\209) seguido de un byte de continuación 0x80–0xBF.
        local count = 0
        for _ in s:gmatch('[\208\209][\128-\191]') do
          count = count + 1
          if count >= MIN_CYR then
            return true, 1.0, count .. ' chars'
          end
        end
      end
    end
    return false
  end,
})
