// Ficheros de configuración para clientes SFTP. Llevan servidor, puerto y usuario,
// NUNCA la contraseña (FileZilla la guardaría en base64, que no cifra nada, y estos
// ficheros acaban en Descargas o reenviados): el cliente la teclea al conectar.

const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
  .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&apos;')

// FileZilla: Archivo → Importar… (formato del Gestor de sitios).
// Protocol 1 = SFTP · Logontype 2 = "Pedir contraseña".
export function filezillaXml({ host, port, username, name }) {
  return `<?xml version="1.0" encoding="UTF-8"?>
<FileZilla3>
  <Servers>
    <Server>
      <Host>${esc(host)}</Host>
      <Port>${esc(port)}</Port>
      <Protocol>1</Protocol>
      <Type>0</Type>
      <User>${esc(username)}</User>
      <Logontype>2</Logontype>
      <EncodingType>Auto</EncodingType>
      <BypassProxy>0</BypassProxy>
      <Name>${esc(name)}</Name>
      <SyncBrowsing>0</SyncBrowsing>
      <DirectoryComparison>0</DirectoryComparison>
    </Server>
  </Servers>
</FileZilla3>
`
}

// Cyberduck (Mac/Windows): marcador .duck, se abre con doble clic.
export function cyberduckBookmark({ host, port, username, name }) {
  return `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Protocol</key><string>sftp</string>
  <key>Nickname</key><string>${esc(name)}</string>
  <key>Hostname</key><string>${esc(host)}</string>
  <key>Port</key><string>${esc(port)}</string>
  <key>Username</key><string>${esc(username)}</string>
</dict>
</plist>
`
}

export function downloadText(filename, text, type = 'application/xml') {
  const url = URL.createObjectURL(new Blob([text], { type }))
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
