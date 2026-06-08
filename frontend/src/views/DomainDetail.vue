<template>
  <div class="domain-detail">
    <!-- Cabecera -->
    <header class="dd-head">
      <div class="dd-head__left">
        <router-link to="/domains" class="dd-back" title="Volver a dominios"><i class="bi bi-arrow-left"></i></router-link>
        <div>
          <h1 class="dd-title">
            <i class="bi bi-globe2"></i>
            {{ domain?.domain_name || '—' }}
          </h1>
          <p class="dd-sub" v-if="domain">
            <StatusBadge
              :status="domain.is_suspended ? 'warning' : (domain.is_active ? 'active' : 'error')"
              :label="domain.is_suspended ? 'Suspendido' : (domain.is_active ? 'Activo' : 'Inactivo')" />
            <span class="dd-sub__sep">·</span>
            <span class="mono">PHP {{ domain.php_version || '—' }}</span>
          </p>
        </div>
      </div>
      <div class="dd-head__actions" v-if="domain">
        <BaseButton variant="secondary" size="sm" icon="box-arrow-up-right" tag="a"
          v-bind="{ href: 'http://' + domain.domain_name, target: '_blank' }">Visitar</BaseButton>
        <BaseButton variant="secondary" size="sm" icon="folder2-open" @click="goFiles">Archivos</BaseButton>
      </div>
    </header>

    <div v-if="loading" class="svq-skeleton" style="height:300px;border-radius:var(--r-lg)"></div>

    <template v-else-if="domain">
      <BaseTabs v-model="tab" :tabs="tabList" />

      <!-- ===== Overview ===== -->
      <div v-show="tab === 'overview'" class="dd-grid">
        <BaseCard title="Información" icon="info-circle">
          <div class="kv">
            <div class="kv__row"><span class="kv__k">Document root</span><span class="kv__v mono">{{ domain.public_html || '—' }}</span></div>
            <div class="kv__row"><span class="kv__k">IPv4</span><span class="kv__v mono">{{ domain.ipv4 || '—' }}</span></div>
            <div class="kv__row"><span class="kv__k">IPv6</span><span class="kv__v mono">{{ domain.ipv6 || 'sin asignar' }}</span></div>
            <div class="kv__row"><span class="kv__k">Creado</span><span class="kv__v">{{ formatDate(domain.created_at) }}</span></div>
          </div>
        </BaseCard>

        <BaseCard title="SSL" icon="shield-lock">
          <template #actions><StatusBadge :status="sslActive ? 'valid' : 'none'" :label="sslActive ? 'Activo' : 'Sin SSL'" /></template>
          <p class="dd-muted">{{ sslActive ? 'Certificado activo para este dominio.' : 'Este dominio no tiene certificado SSL.' }}</p>
          <BaseButton variant="subtle" size="sm" icon="shield-check" @click="tab = 'ssl'">Gestionar SSL</BaseButton>
        </BaseCard>

        <BaseCard title="PHP" icon="filetype-php">
          <template #actions><span class="mono dd-php">{{ domain.php_version || '—' }}</span></template>
          <p class="dd-muted">Versión y ajustes php.ini de este dominio.</p>
          <BaseButton variant="subtle" size="sm" icon="sliders" @click="tab = 'php'">Configurar PHP</BaseButton>
        </BaseCard>

        <BaseCard title="FastCGI cache" icon="lightning-charge">
          <template #actions>
            <StatusBadge :status="domain.fastcgi_cache_enabled ? 'active' : 'none'" :label="domain.fastcgi_cache_enabled ? 'Activa' : 'Off'" />
          </template>
          <p class="dd-muted">
            {{ domain.fastcgi_cache_enabled ? `Cache activa (TTL ${domain.fastcgi_cache_ttl_minutes || 60} min).` : 'Cache desactivada.' }}
          </p>
          <div class="dd-actions-row">
            <BaseButton variant="subtle" size="sm" :icon="domain.fastcgi_cache_enabled ? 'lightning-fill' : 'lightning'" @click="toggleCache" :loading="cacheSaving">
              {{ domain.fastcgi_cache_enabled ? 'Desactivar' : 'Activar' }}
            </BaseButton>
            <BaseButton v-if="domain.fastcgi_cache_enabled" variant="ghost" size="sm" icon="trash3" @click="purgeCache" :loading="cacheSaving">Purgar</BaseButton>
          </div>
        </BaseCard>

        <!-- Modo solo-lectura HTTP -->
        <BaseCard title="Modo solo-lectura" icon="slash-circle">
          <template #actions>
            <StatusBadge
              :status="domain.readonly_mode_enabled ? 'warning' : 'none'"
              :label="domain.readonly_mode_enabled ? 'Activo' : 'Off'"
            />
          </template>
          <p class="dd-muted">
            {{ domain.readonly_mode_enabled
              ? 'POST/PUT/DELETE bloqueados. Solo las IPs indicadas pueden escribir.'
              : 'Bloquea POST/PUT/DELETE/PATCH excepto desde IPs autorizadas. Útil para contener un sitio comprometido.' }}
          </p>
          <div v-if="showReadonlyForm" class="dd-readonly-form">
            <label class="dd-label">IPs/CIDRs autorizadas para escribir (una por línea)</label>
            <textarea
              v-model="readonlyIps"
              class="svq-input mono"
              rows="3"
              placeholder="1.2.3.4&#10;10.0.0.0/8&#10;(vacío = nadie puede hacer POST)"
            ></textarea>
            <div class="dd-actions-row">
              <BaseButton variant="primary" size="sm" icon="check2" :loading="readonlySaving" @click="saveReadonlyMode(true)">
                Activar
              </BaseButton>
              <BaseButton variant="ghost" size="sm" @click="showReadonlyForm = false">Cancelar</BaseButton>
            </div>
          </div>
          <div v-else class="dd-actions-row">
            <BaseButton
              v-if="!domain.readonly_mode_enabled"
              variant="subtle" size="sm" icon="slash-circle"
              @click="showReadonlyForm = true"
            >Activar modo solo-lectura</BaseButton>
            <BaseButton
              v-else
              variant="danger" size="sm" icon="slash-circle"
              :loading="readonlySaving"
              @click="saveReadonlyMode(false)"
            >Desactivar</BaseButton>
            <BaseButton
              v-if="domain.readonly_mode_enabled"
              variant="ghost" size="sm" icon="pencil"
              @click="editReadonlyIps"
            >Editar IPs</BaseButton>
          </div>
        </BaseCard>

        <!-- HTTP/3 (QUIC) -->
        <BaseCard title="HTTP/3 (QUIC)" icon="lightning-charge">
          <template #actions>
            <StatusBadge
              :status="domain.http3_enabled ? 'active' : 'none'"
              :label="domain.http3_enabled ? 'Activo' : 'Off'"
            />
          </template>
          <p class="dd-muted">
            {{ domain.http3_enabled
              ? 'HTTP/3 activo. El navegador usará QUIC (UDP 443) para conexiones más rápidas.'
              : 'HTTP/3 usa QUIC (UDP) para cargas más rápidas. Requiere SSL activo y nginx 1.25+.' }}
          </p>
          <p v-if="!domain.ssl_enabled" class="dd-muted" style="color:var(--warning)">
            <i class="bi bi-exclamation-triangle"></i> Requiere SSL activo en este dominio.
          </p>
          <div class="dd-actions-row">
            <BaseButton
              :variant="domain.http3_enabled ? 'danger' : 'subtle'"
              size="sm"
              :icon="domain.http3_enabled ? 'lightning' : 'lightning-charge'"
              :loading="http3Saving"
              :disabled="!domain.ssl_enabled && !domain.http3_enabled"
              @click="toggleHttp3"
            >
              {{ domain.http3_enabled ? 'Desactivar' : 'Activar HTTP/3' }}
            </BaseButton>
          </div>
        </BaseCard>

        <!-- Headers HTTP de seguridad -->
        <BaseCard title="Headers de seguridad" icon="shield-check">
          <template #actions>
            <StatusBadge
              :status="domain.security_headers_enabled ? 'active' : 'none'"
              :label="domain.security_headers_enabled ? 'Activo' : 'Off'"
            />
          </template>
          <p class="dd-muted">
            {{ domain.security_headers_enabled
              ? 'Headers de seguridad activos: X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, X-XSS-Protection.'
              : 'Activa headers HTTP de seguridad para proteger a los visitantes del sitio. No afecta al contenido ni rompe scripts.' }}
          </p>
          <div class="dd-actions-row">
            <BaseButton
              :variant="domain.security_headers_enabled ? 'danger' : 'subtle'"
              size="sm"
              :icon="domain.security_headers_enabled ? 'shield-slash' : 'shield-check'"
              :loading="secHeadersSaving"
              @click="toggleSecurityHeaders"
            >
              {{ domain.security_headers_enabled ? 'Desactivar' : 'Activar headers' }}
            </BaseButton>
          </div>
        </BaseCard>

        <BaseCard title="Recursos" icon="hdd" class="dd-span2">
          <template #actions>
            <BaseButton variant="ghost" size="sm" icon="arrow-repeat" @click="loadDisk" :loading="diskLoading">Recalcular</BaseButton>
          </template>
          <div v-if="disk" class="disk-grid">
            <div class="disk-item"><span class="disk-k">public_html</span><span class="disk-v mono">{{ formatMB(disk.public_html_mb) }}</span></div>
            <div class="disk-item"><span class="disk-k">Logs</span><span class="disk-v mono">{{ formatMB(disk.logs_mb) }}</span></div>
            <div class="disk-item"><span class="disk-k">Total</span><span class="disk-v mono">{{ formatMB((disk.public_html_mb || 0) + (disk.logs_mb || 0)) }}</span></div>
          </div>
          <p v-else class="dd-muted">Pulsa «Recalcular» para medir el uso de disco.</p>
        </BaseCard>

        <!-- WordPress detectado → panel de gestión (WP Toolkit) -->
        <WpManager
          v-if="detectedApp.app === 'wordpress'"
          :domain-id="domainId"
          :domain-name="domain.domain_name"
          class="dd-span2"
        />

        <!-- App no gestionable ya instalada (Laravel/Nextcloud/PrestaShop/otro) -->
        <BaseCard
          v-else-if="detectedApp.app && !['empty','wordpress'].includes(detectedApp.app)"
          title="Aplicación instalada" icon="box-seam" class="dd-span2">
          <div class="app-detected">
            <i class="bi bi-hdd-stack app-detected__icon"></i>
            <div>
              <p class="app-detected__title">{{ appLabel(detectedApp.app) }} detectado</p>
              <p class="dd-muted">Este dominio ya tiene contenido. El panel de gestión avanzado solo está disponible para WordPress; para esta app, gestiónala desde su propio backoffice.</p>
            </div>
          </div>
        </BaseCard>

        <!-- Dominio vacío → instalador -->
        <BaseCard v-else title="Instalar aplicación" icon="box-seam" class="dd-span2">
          <p class="dd-muted">Instala una aplicación lista para usar en este dominio (crea su base de datos y la configura).</p>
          <div class="app-install">
            <div class="app-install__row">
              <label class="app-field">
                <span>Aplicación</span>
                <select class="svq-select" v-model="appForm.app">
                  <option value="wordpress">WordPress</option>
                  <option value="laravel">Laravel</option>
                  <option value="nextcloud">Nextcloud</option>
                  <option value="prestashop">PrestaShop</option>
                </select>
              </label>
              <label class="app-field" v-if="appNeedsAdmin">
                <span>Usuario admin</span>
                <input class="svq-input" v-model="appForm.admin_user" placeholder="admin" />
              </label>
            </div>
            <div class="app-install__row" v-if="appNeedsAdmin">
              <label class="app-field">
                <span>Contraseña admin</span>
                <input class="svq-input" v-model="appForm.admin_password" type="text" placeholder="mín. 8 caracteres" />
              </label>
              <label class="app-field" v-if="appNeedsEmail">
                <span>Email admin</span>
                <input class="svq-input" v-model="appForm.admin_email" type="email" :placeholder="`admin@${domain.domain_name}`" />
              </label>
            </div>
            <div class="app-install__row" v-if="appForm.app === 'wordpress'">
              <label class="app-field">
                <span>Idioma</span>
                <select class="svq-select" v-model="appForm.locale">
                  <option v-for="l in wpLocales" :key="l.code" :value="l.code">{{ l.label }}</option>
                </select>
              </label>
            </div>
            <p v-if="appForm.app === 'laravel'" class="dd-muted"><i class="bi bi-info-circle"></i> Laravel se instala sin usuario admin (lo defines en tu app). Servirá desde <code>/public</code> automáticamente.</p>
            <p v-else-if="appForm.app === 'nextcloud'" class="dd-muted"><i class="bi bi-info-circle"></i> Nextcloud se instala desatendido con esta cuenta admin. La primera carga puede tardar unos segundos.</p>
            <p v-else-if="appForm.app === 'prestashop'" class="dd-muted"><i class="bi bi-info-circle"></i> PrestaShop se instala desatendido. Entrarás al back office con tu <strong>email</strong> y contraseña; la URL de admin se mostrará al terminar.</p>
            <div class="app-install__foot">
              <small class="dd-muted"><i class="bi bi-exclamation-triangle"></i> El dominio debe estar vacío (sin web previa).</small>
              <BaseButton variant="primary" size="sm" icon="download" :loading="installing" @click="doInstallApp">Instalar</BaseButton>
            </div>
            <div v-if="installResult" class="app-result">
              <p class="app-result__title"><i class="bi bi-check-circle-fill"></i> {{ installResult.message }}</p>
              <div class="app-result__row"><span>URL</span><a :href="installResult.data.url" target="_blank" class="mono">{{ installResult.data.url }}</a></div>
              <div class="app-result__row" v-if="installResult.data.admin_url"><span>Admin</span><a :href="installResult.data.admin_url" target="_blank" class="mono">{{ installResult.data.admin_url }}</a></div>
              <div class="app-result__row" v-if="installResult.data.admin_user"><span>Usuario</span><span class="mono">{{ installResult.data.admin_user }}</span></div>
              <div class="app-result__row" v-if="installResult.data.warning"><span>Aviso</span><span style="color:var(--warning)">{{ installResult.data.warning }}</span></div>
            </div>
          </div>
        </BaseCard>

        <BaseCard title="Acciones rápidas" icon="lightning-charge">
          <div class="quick-col">
            <BaseButton variant="ghost" size="sm" icon="diagram-3" block @click="tab = 'ipv6'">Gestionar IPv6</BaseButton>
            <BaseButton variant="ghost" size="sm" icon="download" block :loading="downloading" @click="downloadSite">Descargar sitio</BaseButton>
            <BaseButton v-if="!domain.is_suspended" variant="ghost" size="sm" icon="pause-circle" block @click="suspend">Suspender</BaseButton>
            <BaseButton v-else variant="ghost" size="sm" icon="play-circle" block @click="unsuspend">Reactivar</BaseButton>
            <BaseButton variant="danger" size="sm" icon="trash" block @click="remove">Eliminar dominio</BaseButton>
          </div>
        </BaseCard>
      </div>

      <!-- ===== SSL ===== -->
      <BaseCard v-show="tab === 'ssl'" title="Certificado SSL" icon="shield-lock">
        <SSLManager :domain="domain" @reload="reloadDomain" />
      </BaseCard>

      <!-- ===== PHP ===== -->
      <BaseCard v-show="tab === 'php'" title="Configuración PHP" icon="filetype-php">
        <template #actions>
          <select class="svq-select svq-select--sm" :value="domain.php_version" @change="changePHP($event.target.value)">
            <option v-for="v in phpVersions" :key="v" :value="v">PHP {{ v }}</option>
          </select>
        </template>
        <div v-if="phpLoading" class="svq-skeleton" style="height:200px"></div>
        <div v-else>
          <p class="dd-muted">Ajustes php.ini propios (vacío = valor global del servidor). No puedes superar el límite del servidor.</p>
          <div class="php-table">
            <div class="php-row php-row--head">
              <span>Directiva</span><span>Valor</span><span>Servidor</span>
            </div>
            <div class="php-row" v-for="(spec, key) in phpDirectives" :key="key">
              <div>
                <div class="php-label">{{ spec.label }}</div>
                <code class="php-code">{{ key }}</code>
              </div>
              <div>
                <select v-if="spec.type === 'bool'" class="svq-input" v-model="phpForm[key]">
                  <option value="">(servidor)</option><option value="On">On</option><option value="Off">Off</option>
                </select>
                <input v-else class="svq-input" v-model="phpForm[key]" :placeholder="phpDefaults[key] || '(servidor)'">
              </div>
              <div class="php-server mono">{{ phpDefaults[key] ?? '—' }}</div>
            </div>
          </div>
          <div class="dd-form-foot">
            <small class="dd-muted">
              <i class="bi bi-info-circle"></i>
              <span v-if="phpHasPool" style="color:var(--success)"> Pool dedicado activo</span>
              <span v-else> Usando php.ini global</span>
            </small>
            <BaseButton variant="primary" size="sm" :loading="phpSaving" @click="savePhp">Guardar y aplicar</BaseButton>
          </div>
        </div>
      </BaseCard>

      <!-- ===== Recursos del pool PHP-FPM (tarjeta propia) ===== -->
      <BaseCard v-show="tab === 'php'" title="Recursos del pool PHP-FPM" icon="cpu">
        <div class="fpm-block">
          <p class="dd-muted" style="margin:0 0 1rem">
            Controla cuántos procesos PHP levanta este dominio (consumo de RAM/CPU).
            Elige un perfil o ajústalo a mano.
          </p>

          <div v-if="!fpmLoaded" class="svq-skeleton" style="height:90px"></div>
            <div v-else>
              <!-- Presets -->
              <div class="fpm-presets">
                <button v-for="(p, key) in fpmPresets" :key="key" type="button"
                        class="fpm-preset" :class="{ 'is-active': fpmPreset === key }"
                        @click="selectFpmPreset(key)">
                  <span class="fpm-preset-name">{{ p.label }}</span>
                  <span class="fpm-preset-desc">{{ p.description }}</span>
                </button>
              </div>

              <!-- Ajuste manual (avanzado, colapsable) -->
              <button type="button" class="fpm-advanced-toggle" @click="fpmAdvanced = !fpmAdvanced">
                <i class="bi" :class="fpmAdvanced ? 'bi-chevron-down' : 'bi-chevron-right'"></i>
                Ajuste manual avanzado
              </button>
              <div v-show="fpmAdvanced" class="fpm-manual">
                <div class="fpm-field">
                  <label>Modo (pm)</label>
                  <select class="svq-input" v-model="fpmManual.pm">
                    <option value="ondemand">ondemand — procesos solo bajo demanda (menos RAM)</option>
                    <option value="dynamic">dynamic — mantiene procesos listos (más rápido)</option>
                    <option value="static">static — número fijo de procesos</option>
                  </select>
                </div>
                <div class="fpm-field">
                  <label>Máx. procesos (max_children)</label>
                  <input class="svq-input" type="number" min="1" :max="fpmCaps['pm.max_children']"
                         v-model.number="fpmManual['pm.max_children']" />
                  <small class="dd-muted">Tope del servidor: {{ fpmCaps['pm.max_children'] }}</small>
                </div>
                <div class="fpm-field">
                  <label>Peticiones por proceso (max_requests)</label>
                  <input class="svq-input" type="number" min="0" :max="fpmCaps['pm.max_requests']"
                         v-model.number="fpmManual['pm.max_requests']" />
                  <small class="dd-muted">Recicla el proceso tras N peticiones (mitiga fugas de memoria)</small>
                </div>
                <template v-if="fpmManual.pm === 'dynamic'">
                  <div class="fpm-field">
                    <label>Procesos iniciales (start_servers)</label>
                    <input class="svq-input" type="number" min="1" v-model.number="fpmManual['pm.start_servers']" />
                  </div>
                  <div class="fpm-field">
                    <label>Mín. en reserva (min_spare_servers)</label>
                    <input class="svq-input" type="number" min="1" v-model.number="fpmManual['pm.min_spare_servers']" />
                  </div>
                  <div class="fpm-field">
                    <label>Máx. en reserva (max_spare_servers)</label>
                    <input class="svq-input" type="number" min="1" v-model.number="fpmManual['pm.max_spare_servers']" />
                  </div>
                </template>
                <div class="fpm-field" v-if="fpmManual.pm === 'ondemand'">
                  <label>Timeout de inactividad (idle_timeout)</label>
                  <input class="svq-input" v-model="fpmManual['pm.process_idle_timeout']" placeholder="10s" />
                </div>
              </div>

              <div class="dd-form-foot">
                <small class="dd-muted">
                  <i class="bi bi-cpu"></i>
                  RAM estimada en pico: ~{{ fpmEstimatedRamMb }} MB
                  <span style="opacity:.7">({{ fpmEffectiveChildren }} procesos × ~40 MB)</span>
                </small>
                <BaseButton variant="primary" size="sm" :loading="fpmSaving" @click="saveFpm">
                  Aplicar recursos
                </BaseButton>
              </div>
            </div>
        </div>
      </BaseCard>

      <!-- ===== IPv6 ===== -->
      <BaseCard v-show="tab === 'ipv6'" title="IPv6" icon="diagram-3">
        <IPv6Manager :domain="domain" @reload="reloadDomain" />
      </BaseCard>

      <!-- ===== Bots ===== -->
      <BaseCard v-show="tab === 'bots'" title="Bloqueo de Bots" icon="robot">
        <p class="text-muted small mb-4">
          Bloquea user-agents maliciosos específicamente para este dominio (HTTP 444).
          Los bots bloqueados globalmente en Seguridad → Bad Bots también aplican.
        </p>
        <div v-if="botsLoading" class="text-center py-3">
          <span class="spinner-border spinner-border-sm"></span>
        </div>
        <div v-else style="display:flex;flex-direction:column;gap:1.5rem">
          <!-- Bots conocidos -->
          <div>
            <h6 style="font-size:.95rem;font-weight:600;margin-bottom:1rem;color:var(--text-secondary)">Bots conocidos</h6>
            <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:1rem">
              <div v-for="bot in domainKnownBots" :key="bot.id"
                   style="padding:1rem;border-radius:var(--radius-md);border:1px solid var(--border);background:var(--surface-2);transition:all .15s;cursor:pointer"
                   :class="{ 'bot-card-active': bot.enabled && !bot.globalBlocked, 'bot-card-global': bot.globalBlocked }"
                   @click="toggleBotEnabled(bot)">
                <div style="display:flex;align-items:flex-start;gap:.75rem">
                  <input class="form-check-input" type="checkbox" style="margin-top:.2rem;flex-shrink:0"
                         :id="'dbot-'+domain.id+'-'+bot.id"
                         :checked="bot.enabled"
                         @click.stop="toggleBotEnabled(bot)"
                         :disabled="bot.globalBlocked" />
                  <div style="flex:1;min-width:0">
                    <div style="display:flex;align-items:center;gap:.5rem;margin-bottom:.25rem">
                      <label :for="'dbot-'+domain.id+'-'+bot.id"
                             style="font-weight:600;font-size:.95rem;cursor:pointer;margin:0"
                             :class="bot.globalBlocked ? 'text-muted' : ''">
                        {{ bot.label }}
                      </label>
                      <span v-if="bot.globalBlocked" style="font-size:.7rem;padding:.2rem .4rem;border-radius:var(--radius-sm);background:var(--text-muted);color:var(--surface);font-weight:500">global</span>
                      <span v-else-if="bot.enabled" style="font-size:.7rem;padding:.2rem .4rem;border-radius:var(--radius-sm);background:var(--danger);color:#fff;font-weight:500">bloqueado</span>
                    </div>
                    <p style="font-size:.8rem;color:var(--text-muted);margin:0 0 .5rem 0">{{ bot.description }}</p>
                    <code style="font-size:.75rem;color:var(--text-muted);background:var(--surface-3);padding:.25rem .4rem;border-radius:.25rem;display:block;word-break:break-all">~*{{ bot.pattern }}</code>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Patrones personalizados -->
          <div>
            <h6 style="font-size:.95rem;font-weight:600;margin-bottom:1rem;color:var(--text-secondary)">Patrones personalizados</h6>
            <div style="display:flex;flex-direction:column;gap:.5rem;max-width:100%">
              <div v-for="(p, i) in domainCustomBots" :key="i"
                   style="display:flex;gap:.5rem;align-items:center">
                <span style="font-family:var(--font-mono);font-size:.85rem;color:var(--text-muted);flex-shrink:0">~*</span>
                <input v-model="domainCustomBots[i]" type="text"
                       style="flex:1;padding:.5rem .75rem;border:1px solid var(--border);border-radius:var(--radius-sm);font-family:var(--font-mono);font-size:.85rem;background:var(--surface);color:var(--text)"
                       placeholder="patron-bot" />
                <button type="button" class="bot-btn-delete"
                        @click="domainCustomBots.splice(i, 1)">
                  <i class="bi bi-trash" style="font-size:.9rem"></i>
                </button>
              </div>
              <button type="button" class="bot-btn-add"
                      @click="domainCustomBots.push('')">
                <i class="bi bi-plus" style="margin-right:.3rem"></i>Añadir patrón
              </button>
            </div>
          </div>

          <!-- Botón guardar -->
          <BaseButton variant="primary" size="sm" icon="save" :loading="botsSaving"
                      @click="saveDomainBots"
                      style="align-self:flex-start">
            Guardar y aplicar
          </BaseButton>
        </div>
      </BaseCard>

      <!-- ===== Git deploy ===== -->
      <BaseCard v-show="tab === 'git'" title="Despliegue Git" icon="git">
        <template #actions v-if="git && git.enabled">
          <BaseButton size="sm" variant="primary" :loading="gitDeploying" @click="doDeploy">
            <i class="bi bi-arrow-repeat"></i> Actualizar ahora
          </BaseButton>
        </template>

        <div v-if="gitLoading" class="svq-skeleton" style="height:160px"></div>

        <!-- No activo: formulario de alta -->
        <template v-else-if="git && !git.enabled">
          <p class="dd-muted" style="margin-bottom:var(--sp-4)">
            Despliega tu sitio directamente desde un repositorio Git (GitHub/GitLab).
            Cada despliegue crea una <strong>release</strong> nueva; puedes volver a una
            anterior con un clic. Requiere que <code>public_html</code> esté vacío.
          </p>

          <div class="dd-field">
            <label>URL del repositorio</label>
            <input class="form-control mono" v-model="gitForm.repo_url"
                   placeholder="https://github.com/usuario/repo.git  o  git@github.com:usuario/repo.git">
          </div>
          <div class="row g-3">
            <div class="col-md-4 dd-field">
              <label>Rama</label>
              <input class="form-control mono" v-model="gitForm.branch" placeholder="main">
            </div>
            <div class="col-md-4 dd-field">
              <label>Proveedor</label>
              <select class="form-select" v-model="gitForm.provider">
                <option value="github">GitHub</option>
                <option value="gitlab">GitLab</option>
                <option value="generic">Otro</option>
              </select>
            </div>
            <div class="col-md-4 dd-field">
              <label>Releases a conservar</label>
              <input type="number" min="1" max="30" class="form-control" v-model.number="gitForm.keep_releases">
            </div>
          </div>
          <div class="dd-field">
            <label>Comandos de build (opcional, uno por línea)</label>
            <textarea class="form-control mono" rows="3" v-model="gitForm.build_commands"
                      placeholder="composer install --no-dev --optimize-autoloader&#10;npm ci && npm run build"></textarea>
            <small class="dd-muted">Se ejecutan tras cada despliegue, como tu usuario, dentro de la release.</small>
          </div>

          <!-- Deploy key para repos privados -->
          <div class="border rounded p-3 mt-3" style="background:var(--surface-inset)">
            <div class="d-flex justify-content-between align-items-center mb-2">
              <strong><i class="bi bi-key me-1"></i>Repositorio privado (deploy key SSH)</strong>
              <BaseButton size="sm" variant="ghost" :loading="gitKeyGen" @click="genKey">Generar clave</BaseButton>
            </div>
            <p class="dd-muted mb-2" style="font-size:.85rem">
              Si tu repo es privado, genera la clave y añádela como <em>Deploy Key</em> en GitHub/GitLab,
              luego usa la URL <code>git@…</code>.
            </p>
            <textarea v-if="git.deploy_key_pub" class="form-control mono" rows="2" readonly :value="git.deploy_key_pub"></textarea>
          </div>

          <div class="mt-4">
            <BaseButton variant="primary" :loading="gitSaving" @click="doSetup">
              <i class="bi bi-cloud-download"></i> Activar y desplegar
            </BaseButton>
          </div>
        </template>

        <!-- Activo: estado + releases + webhook -->
        <template v-else-if="git">
          <div class="dd-kv">
            <div><span class="dd-muted">Repositorio</span><div class="mono">{{ git.repo_url }}</div></div>
            <div><span class="dd-muted">Rama</span><div class="mono">{{ git.branch }}</div></div>
            <div><span class="dd-muted">Release activa</span><div class="mono">{{ git.active_release || '—' }}</div></div>
            <div v-if="git.last_deployment"><span class="dd-muted">Último commit</span>
              <div class="mono">{{ (git.last_deployment.commit_sha || '').slice(0,7) }} — {{ git.last_deployment.commit_msg }}</div>
            </div>
          </div>

          <!-- Webhook -->
          <div class="border rounded p-3 mt-3" style="background:var(--surface-inset)">
            <strong><i class="bi bi-broadcast me-1"></i>Auto-deploy por Webhook</strong>
            <p class="dd-muted mb-2" style="font-size:.85rem">
              Añade esta URL en los Webhooks de tu repo (content-type JSON, secret = el token de la URL).
              Cada push a <code>{{ git.branch }}</code> desplegará automáticamente.
            </p>
            <div class="d-flex gap-2">
              <input class="form-control mono" readonly :value="git.webhook_url">
              <BaseButton size="sm" variant="ghost" @click="copyText(git.webhook_url)"><i class="bi bi-clipboard"></i></BaseButton>
            </div>
          </div>

          <!-- Releases -->
          <h6 class="mt-4 mb-2"><i class="bi bi-clock-history me-1"></i>Releases</h6>
          <table class="table table-sm align-middle">
            <thead><tr><th>Release</th><th>Estado</th><th class="text-end">Acción</th></tr></thead>
            <tbody>
              <tr v-for="r in git.releases" :key="r">
                <td class="mono">{{ r }}</td>
                <td><StatusBadge v-if="git.active_release === r" status="success" text="Activa" /><span v-else class="dd-muted">—</span></td>
                <td class="text-end">
                  <BaseButton v-if="git.active_release !== r" size="sm" variant="ghost"
                              :loading="gitRolling === r" @click="doRollback(r)">Rollback</BaseButton>
                </td>
              </tr>
              <tr v-if="!git.releases || !git.releases.length"><td colspan="3" class="dd-muted">Sin releases todavía.</td></tr>
            </tbody>
          </table>

          <!-- Historial -->
          <h6 class="mt-4 mb-2"><i class="bi bi-journal-text me-1"></i>Historial de despliegues</h6>
          <table class="table table-sm align-middle">
            <thead><tr><th>Fecha</th><th>Commit</th><th>Origen</th><th>Estado</th></tr></thead>
            <tbody>
              <tr v-for="d in gitDeployments" :key="d.id">
                <td>{{ d.created_at ? new Date(d.created_at).toLocaleString('es-ES') : '—' }}</td>
                <td class="mono">{{ (d.commit_sha || '').slice(0,7) || '—' }} {{ d.commit_msg }}</td>
                <td>{{ d.trigger }}</td>
                <td><StatusBadge :status="d.status === 'success' ? 'success' : 'danger'" :text="d.status" /></td>
              </tr>
              <tr v-if="!gitDeployments.length"><td colspan="4" class="dd-muted">Sin despliegues.</td></tr>
            </tbody>
          </table>

          <div class="mt-3">
            <BaseButton variant="ghost" size="sm" @click="doDisableGit">
              <i class="bi bi-x-circle"></i> Desactivar despliegue Git
            </BaseButton>
          </div>
        </template>
      </BaseCard>

      <!-- ===== Avanzado: directivas nginx/apache personalizadas ===== -->
      <BaseCard v-show="tab === 'advanced'" title="Directivas personalizadas" icon="sliders">
        <p class="dd-muted">
          Reglas extra que se inyectan <strong>dentro</strong> del bloque del dominio (además de la plantilla).
          No incluyas <code>server {'{'}</code> ni <code>&lt;VirtualHost&gt;</code>: pega solo directivas
          (p. ej. <code>location</code>, <code>add_header</code>, <code>rewrite</code>…). Se valida antes de aplicar;
          si hay un error, se descarta y el sitio sigue intacto.
        </p>

        <div class="adv-field">
          <label class="adv-label"><i class="bi bi-hdd-network"></i> Nginx</label>
          <textarea class="svq-input mono adv-textarea" rows="10" v-model="advNginx"
            placeholder="location /healthz { return 200 'ok'; }"></textarea>
        </div>

        <div class="adv-field">
          <label class="adv-label"><i class="bi bi-feather"></i> Apache <span class="dd-muted">(solo si el dominio usa Apache+Nginx)</span></label>
          <textarea class="svq-input mono adv-textarea" rows="8" v-model="advApache"
            placeholder="Header set X-Mi-Cabecera 'valor'"></textarea>
        </div>

        <div v-if="advError" class="adv-error"><i class="bi bi-exclamation-triangle"></i> {{ advError }}</div>

        <div class="adv-actions">
          <BaseButton variant="primary" icon="check2" :loading="advSaving" @click="saveCustomConfig">Guardar y aplicar</BaseButton>
          <small class="dd-muted">Se ejecuta <code>nginx -t</code> / <code>apachectl configtest</code> antes de recargar.</small>
        </div>
      </BaseCard>

      <!-- ===== Logs ===== -->
      <BaseCard v-show="tab === 'logs'" title="Registros" icon="journal-text" flush>
        <template #actions>
          <div class="logs-controls">
            <div class="seg">
              <button :class="{active: logTab==='access'}" @click="switchLog('access')">access</button>
              <button :class="{active: logTab==='error'}" @click="switchLog('error')">error</button>
            </div>
            <select class="svq-select svq-select--sm" v-model.number="logLines" @change="loadLogs">
              <option :value="50">50</option><option :value="200">200</option><option :value="500">500</option><option :value="2000">2000</option>
            </select>
            <button class="icon-act" @click="loadLogs" title="Refrescar"><i class="bi bi-arrow-clockwise"></i></button>
          </div>
        </template>
        <div class="logs-body">
          <div v-if="logsLoading" class="svq-skeleton" style="height:200px;margin:var(--sp-4)"></div>
          <div v-else-if="!logsData.exists" class="dd-muted" style="padding:var(--sp-5)">
            {{ logsData.message || 'Sin datos.' }}
            <div class="mono dd-muted" style="margin-top:6px">{{ logsData.path }}</div>
          </div>
          <template v-else>
            <div class="logs-search-bar">
              <i class="bi bi-search logs-search-icon"></i>
              <input
                class="logs-search-input"
                v-model="logSearch"
                placeholder="Filtrar líneas… (IP, ruta, código, texto)"
                spellcheck="false"
              />
              <span v-if="logSearch" class="logs-match-count">
                {{ filteredLogLines.length }} / {{ logsData.lines.length }}
              </span>
              <button v-if="logSearch" class="logs-search-clear" @click="logSearch = ''" title="Limpiar">
                <i class="bi bi-x"></i>
              </button>
            </div>
            <div class="logs-meta mono">{{ logsData.path }} — {{ logsData.count }} líneas</div>
            <div class="logs-pre">
              <div
                v-for="(line, i) in filteredLogLines"
                :key="i"
                class="log-line"
                :class="logLineClass(line)"
                v-html="highlightLog(line)"
              ></div>
              <div v-if="filteredLogLines.length === 0" class="dd-muted" style="padding:var(--sp-4)">
                Sin resultados para <strong>{{ logSearch }}</strong>
              </div>
            </div>
          </template>
        </div>
      </BaseCard>
    </template>

    <BaseCard v-else>
      <EmptyState icon="exclamation-triangle" title="Dominio no encontrado" description="No se pudo cargar este dominio.">
        <BaseButton tag="router-link" v-bind="{ to: '/domains' }" variant="primary">Volver a dominios</BaseButton>
      </EmptyState>
    </BaseCard>
  </div>
</template>

<script>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMainStore } from '../stores/useMainStore'
import api from '../services/api'
import BaseCard from '../components/ui/BaseCard.vue'
import BaseButton from '../components/ui/BaseButton.vue'
import BaseTabs from '../components/ui/BaseTabs.vue'
import StatusBadge from '../components/ui/StatusBadge.vue'
import EmptyState from '../components/ui/EmptyState.vue'
import SSLManager from '../components/SSLManager.vue'
import IPv6Manager from '../components/IPv6Manager.vue'
import WpManager from '../components/WpManager.vue'

export default {
  name: 'DomainDetail',
  components: { BaseCard, BaseButton, BaseTabs, StatusBadge, EmptyState, SSLManager, IPv6Manager, WpManager },
  setup() {
    const route = useRoute()
    const router = useRouter()
    const store = useMainStore()

    const domainId = computed(() => parseInt(route.params.id))
    const domain = ref(null)
    const loading = ref(true)
    const tab = ref('overview')
    const phpVersions = ref([])

    const tabList = [
      { key: 'overview', label: 'Resumen', icon: 'grid-1x2' },
      { key: 'ssl',      label: 'SSL',     icon: 'shield-lock' },
      { key: 'php',      label: 'PHP',     icon: 'filetype-php' },
      { key: 'ipv6',     label: 'IPv6',    icon: 'diagram-3' },
      { key: 'bots',     label: 'Bots',    icon: 'robot' },
      { key: 'git',      label: 'Git',     icon: 'git' },
      { key: 'advanced', label: 'Avanzado',icon: 'sliders' },
      { key: 'logs',     label: 'Logs',    icon: 'journal-text' },
    ]

    const formatMB = (mb) => {
      if (!mb) return '0 MB'
      if (mb >= 1024) return (mb / 1024).toFixed(mb % 1024 === 0 ? 0 : 1) + ' GB'
      return mb + ' MB'
    }
    const formatDate = (d) => d ? new Date(d).toLocaleDateString('es-ES', { day: '2-digit', month: 'short', year: 'numeric' }) : '—'

    // ── Directivas personalizadas (tab Avanzado) ──
    const advNginx  = ref('')
    const advApache = ref('')
    const advSaving = ref(false)
    const advError  = ref('')
    const _syncAdv = () => {
      advNginx.value  = domain.value?.custom_nginx_config  || ''
      advApache.value = domain.value?.custom_apache_config || ''
    }
    const saveCustomConfig = async () => {
      advSaving.value = true; advError.value = ''
      try {
        await api.updateDomainCustomConfig(domainId.value, {
          custom_nginx_config:  advNginx.value,
          custom_apache_config: advApache.value,
        })
        store.showNotification('Directivas aplicadas', 'success')
        await reloadDomain()
      } catch (e) {
        advError.value = e.message || 'No se pudo aplicar la configuración'
      } finally { advSaving.value = false }
    }

    const loadDomain = async () => {
      loading.value = true
      try {
        domain.value = await api.getDomain(domainId.value)
        _syncAdv()
      } catch (e) {
        store.showNotification('Error al cargar el dominio', 'danger')
        domain.value = null
      } finally { loading.value = false }
    }
    const reloadDomain = async () => {
      domain.value = await api.getDomain(domainId.value)
      _syncAdv()
      loadSslState()
    }

    // ── SSL real (puede diferir de domain.ssl_enabled si se activó fuera del panel) ──
    const sslActive = ref(null)  // null = no cargado, true/false = estado real
    const loadSslState = async () => {
      try {
        const data = await api.getDomainSSL(domainId.value)
        sslActive.value = !!(data.ssl_enabled || data.cert_info)
      } catch { sslActive.value = false }
    }

    // ── Disco ──
    const disk = ref(null)
    const diskLoading = ref(false)
    const loadDisk = async () => {
      diskLoading.value = true
      try { disk.value = await api.getDomainDisk(domainId.value) }
      catch { store.showNotification('Error midiendo disco', 'danger') }
      finally { diskLoading.value = false }
    }

    // ── Cache ──
    const cacheSaving = ref(false)
    const toggleCache = async () => {
      cacheSaving.value = true
      try {
        const enabled = !domain.value.fastcgi_cache_enabled
        await api.setDomainCache(domainId.value, enabled, domain.value.fastcgi_cache_ttl_minutes || 60)
        store.showNotification(enabled ? 'Cache activada' : 'Cache desactivada', 'success')
        await reloadDomain()
      } catch (e) { store.showNotification('Error: ' + e.message, 'danger') }
      finally { cacheSaving.value = false }
    }
    const purgeCache = async () => {
      if (!confirm(`¿Purgar la cache de ${domain.value.domain_name}?`)) return
      cacheSaving.value = true
      try { const r = await api.purgeDomainCache(domainId.value); store.showNotification(`Cache purgada — ${r.freed_mb} MB`, 'success') }
      catch (e) { store.showNotification('Error: ' + e.message, 'danger') }
      finally { cacheSaving.value = false }
    }

    // ── PHP ──
    const phpLoading = ref(false), phpSaving = ref(false)
    const phpDirectives = ref({}), phpDefaults = ref({}), phpForm = ref({}), phpHasPool = ref(false)
    const loadPhp = async () => {
      phpLoading.value = true
      try {
        const cfg = await api.getDomainPhpConfig(domainId.value)
        phpDirectives.value = cfg.directives || {}
        phpDefaults.value = cfg.server_defaults || {}
        phpHasPool.value = cfg.has_pool
        const form = {}
        for (const key of Object.keys(phpDirectives.value)) {
          form[key] = (cfg.overrides && cfg.overrides[key] != null) ? cfg.overrides[key] : ''
        }
        phpForm.value = form
      } catch (e) { store.showNotification('Error config PHP: ' + e.message, 'danger') }
      finally { phpLoading.value = false }
      // Cargar también el tuning de recursos del pool FPM (mismo tab)
      loadFpm()
    }
    const savePhp = async () => {
      phpSaving.value = true
      try {
        const overrides = {}
        for (const [k, v] of Object.entries(phpForm.value)) if (String(v).trim() !== '') overrides[k] = String(v).trim()
        await api.setDomainPhpConfig(domainId.value, overrides)
        store.showNotification('Configuración PHP aplicada', 'success')
      } catch (e) { store.showNotification('Error: ' + e.message, 'danger') }
      finally { phpSaving.value = false }
    }
    const changePHP = async (version) => {
      try {
        await api.changePHPVersion(domainId.value, version)
        store.showNotification(`PHP cambiado a ${version}`, 'success')
        await reloadDomain(); await loadPhp()
      } catch (e) { store.showNotification('Error: ' + e.message, 'danger'); await reloadDomain() }
    }

    // ── PHP-FPM: tuning de recursos del pool ──
    const fpmLoaded = ref(false), fpmSaving = ref(false), fpmAdvanced = ref(false)
    const fpmPresets = ref({}), fpmCaps = ref({ 'pm.max_children': 50, 'pm.max_requests': 5000 })
    const fpmPreset = ref('medium')
    const fpmManual = ref({})   // pm.* efectivos (preset resuelto + ajustes del usuario)

    const loadFpm = async () => {
      try {
        const cfg = await api.getDomainFpmConfig(domainId.value)
        fpmPresets.value = cfg.presets || {}
        fpmCaps.value = cfg.caps || fpmCaps.value
        fpmPreset.value = (cfg.tuning && cfg.tuning.preset) || cfg.default_preset || 'medium'
        // El manual arranca con las directivas efectivas (preset resuelto).
        // Así el "ajuste avanzado" siempre muestra valores reales coherentes.
        fpmManual.value = { ...(cfg.effective || {}) }
        // Si el dominio tenía manual guardado, marcarlo encima
        if (cfg.tuning && cfg.tuning.manual) {
          fpmManual.value = { ...fpmManual.value, ...cfg.tuning.manual }
          fpmAdvanced.value = true
        }
        fpmLoaded.value = true
      } catch (e) { store.showNotification('Error config FPM: ' + e.message, 'danger') }
    }

    // Al elegir un preset, resolvemos sus directivas y reseteamos el manual a ellas.
    const selectFpmPreset = (key) => {
      fpmPreset.value = key
      const p = fpmPresets.value[key] || {}
      const eff = {}
      for (const [k, v] of Object.entries(p)) {
        if (k !== 'label' && k !== 'description') eff[k] = v
      }
      fpmManual.value = eff
    }

    // ¿El manual difiere del preset puro? Si sí, enviamos manual; si no, solo preset.
    const fpmManualDiffersFromPreset = () => {
      const p = fpmPresets.value[fpmPreset.value] || {}
      for (const [k, v] of Object.entries(fpmManual.value)) {
        if (k === 'label' || k === 'description') continue
        if (String(p[k]) !== String(v)) return true
      }
      return false
    }

    const fpmEffectiveChildren = computed(() => Number(fpmManual.value['pm.max_children']) || 10)
    const fpmEstimatedRamMb = computed(() => fpmEffectiveChildren.value * 40)

    const saveFpm = async () => {
      fpmSaving.value = true
      try {
        const tuning = { preset: fpmPreset.value }
        if (fpmAdvanced.value && fpmManualDiffersFromPreset()) {
          // Solo enviamos las claves tuneables relevantes
          const keys = ['pm','pm.max_children','pm.max_requests','pm.process_idle_timeout',
                        'pm.start_servers','pm.min_spare_servers','pm.max_spare_servers']
          const manual = {}
          for (const k of keys) if (fpmManual.value[k] != null && fpmManual.value[k] !== '') manual[k] = fpmManual.value[k]
          tuning.manual = manual
        }
        const res = await api.setDomainFpmConfig(domainId.value, tuning)
        fpmManual.value = { ...(res.effective || fpmManual.value) }
        store.showNotification('Recursos PHP-FPM aplicados', 'success')
      } catch (e) { store.showNotification('Error: ' + e.message, 'danger') }
      finally { fpmSaving.value = false }
    }

    // ── Logs ──
    const logTab = ref('access'), logLines = ref(200), logsLoading = ref(false)
    const logSearch = ref('')
    const logsData = ref({ exists: false, lines: [], path: '' })

    const loadLogs = async () => {
      logsLoading.value = true
      try {
        const data = await api.getDomainLogs(domainId.value, logTab.value, logLines.value)
        // Invertir: líneas más nuevas arriba
        if (data.lines) data.lines = [...data.lines].reverse()
        logsData.value = data
      }
      catch (e) { logsData.value = { exists: false, lines: [], path: '', message: e.message } }
      finally { logsLoading.value = false }
    }
    const switchLog = (t) => { logTab.value = t; logSearch.value = ''; loadLogs() }

    const filteredLogLines = computed(() => {
      if (!logSearch.value.trim()) return logsData.value.lines || []
      const q = logSearch.value.toLowerCase()
      return (logsData.value.lines || []).filter(l => l.toLowerCase().includes(q))
    })

    const logLineClass = (line) => {
      if (/\s(5\d{2})\s/.test(line) || /\[error\]|\[crit\]|\[emerg\]/i.test(line)) return 'log-error'
      if (/\s(4\d{2})\s/.test(line) || /\[warn\]/i.test(line)) return 'log-warn'
      if (/\s(2\d{2})\s/.test(line)) return 'log-ok'
      return ''
    }

    const highlightLog = (line) => {
      if (!logSearch.value.trim()) return escHtml(line)
      const q = logSearch.value
      const re = new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi')
      return escHtml(line).replace(re, m => `<mark class="log-mark">${m}</mark>`)
    }

    const escHtml = (s) => s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')

    // ── Acciones ──
    const downloading = ref(false)
    const downloadSite = async () => {
      downloading.value = true
      try {
        const { blob, filename } = await api.downloadDomainSite(domainId.value)
        const url = URL.createObjectURL(blob); const a = document.createElement('a')
        a.href = url; a.download = filename; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url)
      } catch (e) { store.showNotification('Error al descargar: ' + e.message, 'danger') }
      finally { downloading.value = false }
    }
    const suspend = async () => {
      if (!confirm(`¿Suspender ${domain.value.domain_name}?`)) return
      try { await api.suspendDomain(domainId.value); store.showNotification('Dominio suspendido', 'warning'); await reloadDomain() }
      catch (e) { store.showNotification('Error: ' + e.message, 'danger') }
    }
    const unsuspend = async () => {
      try { await api.unsuspendDomain(domainId.value); store.showNotification('Dominio reactivado', 'success'); await reloadDomain() }
      catch (e) { store.showNotification('Error: ' + e.message, 'danger') }
    }
    const remove = async () => {
      if (!confirm('¿Eliminar este dominio? Se borrarán todos sus archivos.')) return
      try { await api.deleteDomain(domainId.value); store.showNotification('Dominio eliminado', 'success'); router.push('/domains') }
      catch (e) { store.showNotification('Error: ' + e.message, 'danger') }
    }
    const goFiles = () => router.push({ path: '/files', query: { domain: domainId.value } })

    // ── Detección de app instalada (decide instalar vs gestionar) ──
    const detectedApp = ref({ app: null, managed: false })
    const loadDetectedApp = async () => {
      try {
        const r = await api.getDomainApp(domainId.value)
        detectedApp.value = r.data || { app: null, managed: false }
      } catch (e) { detectedApp.value = { app: null, managed: false } }
    }
    const appLabel = (a) => ({ wordpress: 'WordPress', laravel: 'Laravel', nextcloud: 'Nextcloud', prestashop: 'PrestaShop', unknown: 'Aplicación' }[a] || 'Aplicación')

    // ── Autoinstalador de apps ──
    const appForm = ref({ app: 'wordpress', admin_user: 'admin', admin_password: '', admin_email: '', locale: 'es_ES' })
    const installing = ref(false)
    const installResult = ref(null)
    // Idiomas de WordPress (los sirve el backend; es_ES por defecto). Fallback
    // mínimo por si la llamada falla, para no dejar el selector vacío.
    const wpLocales = ref([{ code: 'es_ES', label: 'Español (España)' }, { code: 'en_US', label: 'English (US)' }])
    const loadWpLocales = async () => {
      try {
        const r = await api.getWordpressLocales()
        if (r?.locales?.length) wpLocales.value = r.locales
        if (r?.default) appForm.value.locale = r.default
      } catch (e) { /* fallback ya cargado */ }
    }
    loadWpLocales()
    // wordpress/nextcloud/prestashop tienen cuenta admin; wordpress y prestashop piden email
    const appNeedsAdmin = computed(() => ['wordpress', 'nextcloud', 'prestashop'].includes(appForm.value.app))
    const appNeedsEmail = computed(() => ['wordpress', 'prestashop'].includes(appForm.value.app))
    const doInstallApp = async () => {
      if (appNeedsAdmin.value) {
        if (!appForm.value.admin_password || appForm.value.admin_password.length < 8) {
          store.showNotification('La contraseña admin debe tener al menos 8 caracteres', 'danger'); return
        }
        if (appNeedsEmail.value && !appForm.value.admin_email) {
          store.showNotification('Indica un email de administrador', 'danger'); return
        }
      }
      // Solo enviamos los campos relevantes para cada app
      const payload = { app: appForm.value.app, admin_user: appForm.value.admin_user }
      if (appNeedsAdmin.value) payload.admin_password = appForm.value.admin_password
      if (appNeedsEmail.value) payload.admin_email = appForm.value.admin_email
      if (appForm.value.app === 'wordpress') payload.locale = appForm.value.locale
      installing.value = true
      installResult.value = null
      try {
        const r = await api.installApp(domainId.value, payload)
        installResult.value = r
        store.showNotification(r.message || 'Aplicación instalada', 'success')
        await reloadDomain()
        await loadDetectedApp()   // tras instalar, la tarjeta pasa a modo gestión
      } catch (e) {
        store.showNotification('Error instalando: ' + e.message, 'danger')
      } finally {
        installing.value = false
      }
    }

    // ── Git deploy ──
    const git = ref(null)
    const gitDeployments = ref([])
    const gitLoading = ref(false)
    const gitSaving = ref(false)
    const gitDeploying = ref(false)
    const gitKeyGen = ref(false)
    const gitRolling = ref('')
    const gitForm = ref({ repo_url: '', branch: 'main', provider: 'github', build_commands: '', keep_releases: 5 })

    const loadGit = async () => {
      gitLoading.value = true
      try {
        const r = await api.getGitStatus(domainId.value)
        git.value = r.data
        if (git.value.enabled) {
          gitForm.value.branch = git.value.branch || 'main'
          gitForm.value.build_commands = git.value.build_commands || ''
          gitForm.value.keep_releases = git.value.keep_releases || 5
          await loadGitDeployments()
        }
      } catch (e) { store.showNotification('Error cargando Git: ' + e.message, 'danger') }
      finally { gitLoading.value = false }
    }
    const loadGitDeployments = async () => {
      try { const r = await api.getGitDeployments(domainId.value); gitDeployments.value = r.data || [] }
      catch { gitDeployments.value = [] }
    }
    const genKey = async () => {
      gitKeyGen.value = true
      try {
        const r = await api.genGitDeployKey(domainId.value)
        if (git.value) git.value.deploy_key_pub = r.deploy_key_pub
        store.showNotification('Deploy key generada', 'success')
      } catch (e) { store.showNotification('Error: ' + e.message, 'danger') }
      finally { gitKeyGen.value = false }
    }
    const doSetup = async () => {
      if (!gitForm.value.repo_url.trim()) { store.showNotification('Indica la URL del repositorio', 'danger'); return }
      gitSaving.value = true
      try {
        const r = await api.setupGit(domainId.value, gitForm.value)
        git.value = r.data
        store.showNotification(r.message || 'Repositorio desplegado', 'success')
        await loadGitDeployments()
      } catch (e) { store.showNotification('Error: ' + e.message, 'danger') }
      finally { gitSaving.value = false }
    }
    const doDeploy = async () => {
      gitDeploying.value = true
      try {
        const r = await api.deployGit(domainId.value)
        git.value = r.data
        store.showNotification(r.message || 'Despliegue completado', 'success')
        await loadGitDeployments()
      } catch (e) { store.showNotification('Error: ' + e.message, 'danger'); await loadGitDeployments() }
      finally { gitDeploying.value = false }
    }
    const doRollback = async (releaseName) => {
      if (!confirm(`¿Volver a la release ${releaseName}?`)) return
      gitRolling.value = releaseName
      try {
        const r = await api.rollbackGit(domainId.value, releaseName)
        git.value = r.data
        store.showNotification(r.message || 'Rollback completado', 'success')
        await loadGitDeployments()
      } catch (e) { store.showNotification('Error: ' + e.message, 'danger') }
      finally { gitRolling.value = '' }
    }
    const doDisableGit = async () => {
      if (!confirm('¿Desactivar el despliegue Git? Los archivos actuales se conservan.')) return
      try {
        await api.disableGit(domainId.value)
        store.showNotification('Despliegue Git desactivado', 'success')
        await loadGit()
      } catch (e) { store.showNotification('Error: ' + e.message, 'danger') }
    }
    const copyText = async (txt) => {
      try { await navigator.clipboard.writeText(txt); store.showNotification('Copiado', 'success') }
      catch { store.showNotification('No se pudo copiar', 'warning') }
    }

    // Cargar Git la primera vez que se entra en su pestaña
    watch(tab, (t) => {
      if (t === 'git' && git.value === null) loadGit()
      if (t === 'bots') loadDomainBots()
    })

    // ── Bots por dominio ───────────────────────────────────────────────────
    const KNOWN_BOTS_CATALOG = [
      { id: 'terrabot',       label: 'Terrabot',          pattern: 'terrabot',        description: 'Bot de ataque conocido' },
      { id: 'masscan',        label: 'Masscan',           pattern: 'masscan',         description: 'Scanner de puertos masivo' },
      { id: 'zgrab',          label: 'ZGrab',             pattern: 'zgrab',           description: 'Scanner de vulnerabilidades' },
      { id: 'nikto',          label: 'Nikto',             pattern: 'nikto',           description: 'Scanner de vulnerabilidades web' },
      { id: 'sqlmap',         label: 'SQLMap',            pattern: 'sqlmap',          description: 'Herramienta SQL injection' },
      { id: 'nuclei',         label: 'Nuclei',            pattern: 'nuclei',          description: 'Scanner de vulnerabilidades' },
      { id: 'python_requests',label: 'Python-requests',   pattern: 'python-requests', description: 'Scripts de scraping en Python' },
      { id: 'semrush',        label: 'SemrushBot',        pattern: 'SemrushBot',      description: 'Bot de SEO agresivo' },
      { id: 'ahrefsbot',      label: 'AhrefsBot',         pattern: 'AhrefsBot',       description: 'Bot de SEO agresivo' },
      { id: 'mj12bot',        label: 'MJ12bot',           pattern: 'MJ12bot',         description: 'Bot de SEO agresivo' },
      { id: 'gptbot',         label: 'GPTBot',            pattern: 'GPTBot',          description: 'Bot scraping OpenAI' },
      { id: 'ccbot',          label: 'CCBot',             pattern: 'CCBot',           description: 'Bot Common Crawl (datos IA)' },
      { id: 'bytespider',     label: 'ByteSpider',        pattern: 'Bytespider',      description: 'Bot TikTok/ByteDance' },
    ]

    const domainKnownBots   = ref([])
    const domainCustomBots  = ref([])
    const globalBlockedBots = ref(new Set())  // patrones bloqueados globalmente
    const botsLoading       = ref(false)
    const botsSaving        = ref(false)

    const loadDomainBots = async () => {
      botsLoading.value = true
      try {
        // Cargar lista global para saber cuáles ya están bloqueados
        const globalData = await api.get('/api/security/bad-bots')
        const globalEnabled = (globalData.known_bots || [])
          .filter(b => b.enabled).map(b => b.pattern.toLowerCase())
        const globalCustom = (globalData.custom_patterns || []).map(p => p.toLowerCase())
        globalBlockedBots.value = new Set([...globalEnabled, ...globalCustom])
      } catch { globalBlockedBots.value = new Set() }
      finally { botsLoading.value = false }

      const raw = domain.value?.blocked_user_agents
      let active = []
      try { active = JSON.parse(raw || '[]') } catch { active = [] }
      const activeSet = new Set(active.map(p => p.toLowerCase()))
      domainKnownBots.value = KNOWN_BOTS_CATALOG.map(b => ({
        ...b,
        enabled:       activeSet.has(b.pattern.toLowerCase()),
        globalBlocked: globalBlockedBots.value.has(b.pattern.toLowerCase()),
      }))
      const knownPatterns = new Set(KNOWN_BOTS_CATALOG.map(b => b.pattern.toLowerCase()))
      domainCustomBots.value = active.filter(p => !knownPatterns.has(p.toLowerCase()))
    }

    const toggleBotEnabled = (bot) => {
      if (!bot.globalBlocked) {
        bot.enabled = !bot.enabled
      }
    }

    const saveDomainBots = async () => {
      botsSaving.value = true
      try {
        const patterns = [
          ...domainKnownBots.value.filter(b => b.enabled).map(b => b.pattern),
          ...domainCustomBots.value.filter(p => p.trim()),
        ]
        await api.setDomainBadBots(domainId.value, patterns)
        store.showNotification('Bots actualizados y nginx recargado', 'success')
        await reloadDomain()
        await loadDomainBots()
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      } finally {
        botsSaving.value = false
      }
    }

    // ── Modo solo-lectura HTTP ──────────────────────────────────────────────
    const showReadonlyForm = ref(false)
    const readonlyIps = ref('')
    const readonlySaving = ref(false)

    const editReadonlyIps = () => {
      // Rellenar el textarea con las IPs actuales (una por línea)
      try {
        const ips = JSON.parse(domain.value?.allowed_mutation_ips || '[]')
        readonlyIps.value = Array.isArray(ips) ? ips.join('\n') : ''
      } catch { readonlyIps.value = '' }
      showReadonlyForm.value = true
    }

    const saveReadonlyMode = async (enable) => {
      readonlySaving.value = true
      try {
        // Convertir las líneas en un JSON array de IPs válidas
        let ipsJson = null
        if (enable) {
          const ips = readonlyIps.value
            .split('\n').map(s => s.trim()).filter(Boolean)
          ipsJson = JSON.stringify(ips)
        }
        await api.updateDomain(domainId.value, {
          readonly_mode_enabled: enable,
          allowed_mutation_ips: ipsJson,
        })
        await reloadDomain()
        showReadonlyForm.value = false
        store.showNotification(
          enable ? 'Modo solo-lectura activado' : 'Modo solo-lectura desactivado',
          enable ? 'warning' : 'success'
        )
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      } finally {
        readonlySaving.value = false
      }
    }

    // ── HTTP/3 (QUIC) ───────────────────────────────────────────────────────
    const http3Saving = ref(false)

    const toggleHttp3 = async () => {
      http3Saving.value = true
      try {
        const enable = !domain.value?.http3_enabled
        await api.updateDomain(domainId.value, { http3_enabled: enable })
        await reloadDomain()
        store.showNotification(
          enable ? 'HTTP/3 activado — recuerda abrir el puerto UDP 443 en el firewall' : 'HTTP/3 desactivado',
          enable ? 'success' : 'warning'
        )
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      } finally {
        http3Saving.value = false
      }
    }

    // ── Headers HTTP de seguridad ───────────────────────────────────────────
    const secHeadersSaving = ref(false)

    const toggleSecurityHeaders = async () => {
      secHeadersSaving.value = true
      try {
        const enable = !domain.value?.security_headers_enabled
        await api.updateDomain(domainId.value, { security_headers_enabled: enable })
        await reloadDomain()
        store.showNotification(
          enable ? 'Headers de seguridad activados' : 'Headers de seguridad desactivados',
          enable ? 'success' : 'warning'
        )
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      } finally {
        secHeadersSaving.value = false
      }
    }

    onMounted(async () => {
      await loadDomain()
      try { const d = await api.getPHPVersions(); phpVersions.value = d?.versions?.length ? d.versions : ['8.2'] }
      catch { phpVersions.value = ['7.4', '8.0', '8.1', '8.2', '8.3', '8.4'] }
      if (domain.value) { loadDisk(); loadPhp(); loadLogs(); loadSslState(); loadDetectedApp() }
    })

    return {
      domain, loading, tab, tabList, phpVersions, reloadDomain,
      sslActive,
      formatMB, formatDate,
      disk, diskLoading, loadDisk,
      cacheSaving, toggleCache, purgeCache,
      phpLoading, phpSaving, phpDirectives, phpDefaults, phpForm, phpHasPool, savePhp, changePHP,
      fpmLoaded, fpmSaving, fpmAdvanced, fpmPresets, fpmCaps, fpmPreset, fpmManual,
      selectFpmPreset, fpmEffectiveChildren, fpmEstimatedRamMb, saveFpm,
      logTab, logLines, logsLoading, logsData, loadLogs, switchLog,
      logSearch, filteredLogLines, logLineClass, highlightLog,
      downloading, downloadSite, suspend, unsuspend, remove, goFiles,
      advNginx, advApache, advSaving, advError, saveCustomConfig,
      appForm, installing, installResult, doInstallApp, appNeedsAdmin, appNeedsEmail, wpLocales,
      detectedApp, appLabel,
      git, gitDeployments, gitLoading, gitSaving, gitDeploying, gitKeyGen, gitRolling, gitForm,
      loadGit, genKey, doSetup, doDeploy, doRollback, doDisableGit, copyText,
      showReadonlyForm, readonlyIps, readonlySaving, saveReadonlyMode, editReadonlyIps,
      domainKnownBots, domainCustomBots, botsLoading, botsSaving, saveDomainBots, toggleBotEnabled,
      secHeadersSaving, toggleSecurityHeaders,
      http3Saving, toggleHttp3,
    }
  },
}
</script>

<style scoped>
.domain-detail { max-width: var(--content-max); margin: 0 auto; display: flex; flex-direction: column; gap: var(--sp-5); }

.dd-head { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--sp-4); flex-wrap: wrap; }
.dd-head__left { display: flex; align-items: center; gap: var(--sp-3); }
.dd-back { width: 38px; height: 38px; display: grid; place-items: center; border: 1px solid var(--border); border-radius: var(--r-md); color: var(--text-secondary); text-decoration: none; transition: all var(--t-fast); flex-shrink: 0; }
.dd-back:hover { background: var(--surface-inset); color: var(--text); }
.dd-title { margin: 0; font-size: var(--fs-2xl); font-weight: var(--fw-bold); letter-spacing: -.02em; color: var(--text); display: flex; align-items: center; gap: var(--sp-2); }
.dd-title .bi { color: var(--color-primary); }
.dd-sub { margin: var(--sp-1) 0 0; display: flex; align-items: center; gap: var(--sp-2); color: var(--text-secondary); }
.dd-sub__sep { color: var(--text-muted); }
.dd-head__actions { display: flex; gap: var(--sp-2); flex-wrap: wrap; }
.mono { font-family: var(--font-mono); }
.dd-muted { color: var(--text-muted); font-size: var(--fs-sm); margin: 0 0 var(--sp-3); }
.dd-field { margin-bottom: var(--sp-3); }
.dd-field > label { display: block; font-size: var(--fs-sm); font-weight: 500; margin-bottom: 4px; color: var(--text-secondary); }
.dd-kv { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: var(--sp-3); }
.dd-kv > div > span { display: block; font-size: var(--fs-sm); color: var(--text-muted); margin-bottom: 2px; }
.dd-php { font-weight: var(--fw-semibold); color: var(--text); }

.dd-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--sp-4); align-items: start; }
.dd-span2 { grid-column: span 2; }

.kv { display: flex; flex-direction: column; }
.kv__row { display: flex; justify-content: space-between; gap: var(--sp-3); padding: 7px 0; border-bottom: 1px solid var(--border); }
.kv__row:last-child { border-bottom: none; }
.kv__k { color: var(--text-muted); font-size: var(--fs-sm); }
.kv__v { color: var(--text); font-size: var(--fs-sm); font-weight: var(--fw-medium); text-align: right; word-break: break-all; }

.dd-actions-row { display: flex; gap: var(--sp-2); }
.quick-col { display: flex; flex-direction: column; gap: var(--sp-2); }

/* Autoinstalador */
.app-install { display: flex; flex-direction: column; gap: var(--sp-3); }
.app-install__row { display: grid; grid-template-columns: 1fr 1fr; gap: var(--sp-3); }
.app-field { display: flex; flex-direction: column; gap: 4px; }
.app-field > span { font-size: var(--fs-sm); color: var(--text-secondary); font-weight: var(--fw-medium); }
.app-install__foot { display: flex; align-items: center; justify-content: space-between; gap: var(--sp-3); flex-wrap: wrap; }
.app-result { border-top: 1px solid var(--border); padding-top: var(--sp-3); display: flex; flex-direction: column; gap: 6px; }
.app-result__title { margin: 0 0 var(--sp-2); color: var(--success); font-weight: var(--fw-semibold); display: flex; align-items: center; gap: 6px; }
.app-result__row { display: flex; gap: var(--sp-3); font-size: var(--fs-sm); }
.app-result__row > span:first-child { min-width: 70px; color: var(--text-muted); }
@media (max-width: 680px) { .app-install__row { grid-template-columns: 1fr; } }
.app-detected { display: flex; align-items: flex-start; gap: var(--sp-3); }
.app-detected__icon { font-size: 1.8rem; color: var(--accent); }
.app-detected__title { margin: 0 0 4px; font-weight: var(--fw-semibold); }

.disk-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--sp-3); }
.disk-item { background: var(--surface-inset); border-radius: var(--r-md); padding: var(--sp-3) var(--sp-4); }
.disk-k { display: block; font-size: var(--fs-sm); color: var(--text-muted); }
.disk-v { font-size: var(--fs-lg); font-weight: var(--fw-bold); color: var(--text); }

/* select / input */
.svq-select, .svq-input {
  height: 38px; padding: 0 var(--sp-3); width: 100%;
  background: var(--surface); color: var(--text);
  border: 1px solid var(--border-strong); border-radius: var(--r-md); font-size: var(--fs-base);
}
.svq-select { cursor: pointer; }
.svq-select--sm { height: 32px; width: auto; font-size: var(--fs-sm); }
.svq-input:focus, .svq-select:focus { outline: none; border-color: var(--color-primary); box-shadow: var(--shadow-focus); }

/* Tab Avanzado — directivas personalizadas */
.adv-field { margin-bottom: var(--sp-4); }
.adv-label { display: flex; align-items: center; gap: 6px; font-weight: var(--fw-medium); margin-bottom: 6px; }
.adv-label .bi { color: var(--svq-orange); }
.adv-textarea { height: auto; padding: var(--sp-3); line-height: 1.5; resize: vertical; }
.adv-actions { display: flex; align-items: center; gap: var(--sp-3); flex-wrap: wrap; }
.adv-error { color: var(--danger); font-size: var(--fs-sm); margin-bottom: var(--sp-3); display: flex; align-items: center; gap: 6px; white-space: pre-wrap; }

/* PHP table */
.php-table { display: flex; flex-direction: column; border: 1px solid var(--border); border-radius: var(--r-md); overflow: hidden; }
.php-row { display: grid; grid-template-columns: 1.4fr 1fr 0.8fr; gap: var(--sp-3); align-items: center; padding: var(--sp-3) var(--sp-4); border-bottom: 1px solid var(--border); }
.php-row:last-child { border-bottom: none; }
.php-row--head { background: var(--surface-inset); font-size: var(--fs-xs); text-transform: uppercase; letter-spacing: .05em; color: var(--text-muted); font-weight: var(--fw-semibold); }
.php-label { font-size: var(--fs-sm); color: var(--text); }
.php-code { font-size: var(--fs-xs); color: var(--text-muted); font-family: var(--font-mono); }
.php-server { font-size: var(--fs-sm); color: var(--text-muted); }
.dd-form-foot { display: flex; align-items: center; justify-content: space-between; gap: var(--sp-3); margin-top: var(--sp-4); }

/* PHP-FPM tuning */
.fpm-presets { display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--sp-3); margin: 0 0 var(--sp-4); }
@media (max-width: 640px) { .fpm-presets { grid-template-columns: 1fr; } }
.fpm-preset { text-align: left; display: flex; flex-direction: column; gap: 4px; padding: var(--sp-3) var(--sp-4); border: 1px solid var(--border); border-radius: var(--r-md); background: var(--surface); cursor: pointer; transition: all .15s; }
.fpm-preset:hover { border-color: var(--accent); }
.fpm-preset.is-active { border-color: var(--accent); background: var(--accent-soft, rgba(99,102,241,.08)); box-shadow: 0 0 0 1px var(--accent) inset; }
.fpm-preset-name { font-size: var(--fs-sm); font-weight: var(--fw-semibold); color: var(--text); }
.fpm-preset-desc { font-size: var(--fs-xs); color: var(--text-muted); line-height: 1.35; }
.fpm-advanced-toggle { background: none; border: none; color: var(--text-secondary); font-size: var(--fs-sm); cursor: pointer; display: inline-flex; align-items: center; gap: 6px; padding: var(--sp-2) 0; }
.fpm-advanced-toggle:hover { color: var(--text); }
.fpm-manual { display: grid; grid-template-columns: repeat(2, 1fr); gap: var(--sp-3) var(--sp-4); padding: var(--sp-3) 0; }
@media (max-width: 640px) { .fpm-manual { grid-template-columns: 1fr; } }
.fpm-field { display: flex; flex-direction: column; gap: 4px; }
.fpm-field label { font-size: var(--fs-xs); color: var(--text-secondary); font-weight: var(--fw-medium); }
.fpm-field small { font-size: var(--fs-xs); color: var(--text-muted); }

/* Logs */
.logs-controls { display: flex; align-items: center; gap: var(--sp-2); }
.seg { display: inline-flex; background: var(--surface-inset); border: 1px solid var(--border); border-radius: var(--r-md); padding: 2px; }
.seg button { border: none; background: transparent; color: var(--text-muted); padding: 4px 12px; border-radius: var(--r-sm); cursor: pointer; font-size: var(--fs-sm); font-family: var(--font-mono); }
.seg button.active { background: var(--surface); color: var(--color-primary); box-shadow: var(--shadow-xs); }
.icon-act { width: 32px; height: 32px; border: 1px solid var(--border); background: var(--surface); border-radius: var(--r-sm); color: var(--text-secondary); cursor: pointer; }
.icon-act:hover { background: var(--surface-inset); color: var(--text); }
.logs-search-bar {
  display: flex; align-items: center; gap: var(--sp-2);
  padding: var(--sp-2) var(--sp-4);
  border-bottom: 1px solid var(--border);
  background: var(--surface-2);
}
.logs-search-icon { color: var(--text-muted); font-size: 13px; flex-shrink: 0; }
.logs-search-input {
  flex: 1; background: transparent; border: none; outline: none;
  font-size: var(--fs-sm); color: var(--text-primary); font-family: var(--font-mono);
}
.logs-match-count { font-size: var(--fs-xs); color: var(--text-muted); white-space: nowrap; }
.logs-search-clear {
  background: none; border: none; cursor: pointer; color: var(--text-muted); padding: 0 2px;
  line-height: 1; font-size: 14px;
}
.logs-search-clear:hover { color: var(--text-primary); }

.logs-meta { padding: var(--sp-2) var(--sp-5); font-size: var(--fs-sm); color: var(--text-muted); border-bottom: 1px solid var(--border); }
.logs-pre {
  margin: 0;
  background: var(--surface-inset);
  font-family: var(--font-mono); font-size: 12px; line-height: 1.6;
  max-height: 60vh; overflow: auto;
}
.log-line {
  padding: 1px var(--sp-5); white-space: pre-wrap; word-break: break-all;
  border-left: 2px solid transparent;
}
.log-line:hover { background: color-mix(in srgb, var(--accent) 4%, transparent); }
.log-error { color: #f87171; border-left-color: #f87171; background: color-mix(in srgb, #f87171 5%, transparent); }
.log-warn  { color: #fb923c; border-left-color: #fb923c; background: color-mix(in srgb, #fb923c 5%, transparent); }
.log-ok    { color: var(--text-secondary); }
.log-mark  { background: #fef08a; color: #1a1a1a; border-radius: 2px; padding: 0 1px; }

@media (max-width: 1000px) { .dd-grid { grid-template-columns: 1fr 1fr; } .dd-span2 { grid-column: span 2; } }
@media (max-width: 680px) { .dd-grid { grid-template-columns: 1fr; } .dd-span2 { grid-column: auto; } .disk-grid { grid-template-columns: 1fr; } }

/* Bot cards styling */
.bot-card-active { border-color: var(--danger); background: color-mix(in srgb, var(--danger) 8%, var(--surface-2)); }
.bot-card-global { opacity: 0.6; }
.bot-btn-delete {
  padding: .5rem; border: 1px solid var(--border); border-radius: var(--radius-sm);
  background: var(--surface); color: var(--danger); cursor: pointer; transition: all .15s;
}
.bot-btn-delete:hover { background: var(--danger); color: #fff; }
.bot-btn-add {
  align-self: flex-start; padding: .5rem 1rem; border: 1px solid var(--border);
  border-radius: var(--radius-sm); background: var(--surface); color: var(--text);
  cursor: pointer; font-size: .85rem; font-weight: 500; transition: all .15s;
}
.bot-btn-add:hover { background: var(--accent); color: #fff; border-color: var(--accent); }
</style>
