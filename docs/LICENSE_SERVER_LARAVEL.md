# Servidor de licencias SVQPanel — Spec para el Laravel de SVQHost

Este documento describe lo que hay que añadir al sistema Laravel de svqhost.com
(el "WHMCS propio") para emitir y validar licencias de SVQPanel.

El panel (servidor del cliente) llama a este endpoint para validar su licencia.
Laravel responde **firmando con Ed25519** (clave privada en `.env`). El panel
verifica la firma con la clave pública embebida. Sin firma válida, el panel
entra en modo restringido.

> ⚠️ La **clave privada** NO está en este documento ni en el repo. Se entrega
> aparte (canal privado). NUNCA se sube a git ni se distribuye con el panel.

---

## 1. Migración: tabla `licenses`

```php
Schema::create('licenses', function (Blueprint $table) {
    $table->id();
    $table->string('key', 64)->unique();          // la license key (token)
    $table->foreignId('client_id')->nullable()    // FK a tu tabla de clientes
          ->constrained('clients')->nullOnDelete();
    $table->string('plan', 32)->default('beta');   // beta | pro | ...
    $table->enum('status', ['active','suspended','expired'])->default('active');
    $table->timestamp('expires_at')->nullable();   // null = sin caducidad
    $table->string('fingerprint', 128)->nullable();// se fija en la 1ª activación
    $table->unsignedInteger('max_servers')->default(1);
    $table->timestamp('last_validated_at')->nullable();
    $table->string('last_ip', 45)->nullable();
    $table->string('last_version', 32)->nullable();
    $table->timestamps();
});
```

## 2. Modelo `License`

```php
class License extends Model
{
    protected $fillable = [
        'key','client_id','plan','status','expires_at',
        'fingerprint','max_servers','last_validated_at','last_ip','last_version',
    ];
    protected $casts = [
        'expires_at' => 'datetime',
        'last_validated_at' => 'datetime',
    ];

    public function isUsable(): bool
    {
        if ($this->status !== 'active') return false;
        if ($this->expires_at && $this->expires_at->isPast()) return false;
        return true;
    }
}
```

## 3. Endpoint `POST /api/license/validate`

Ruta (en `routes/api.php`):

```php
Route::post('/license/validate', [LicenseController::class, 'validate']);
```

Controlador `LicenseController`:

```php
public function validate(Request $request)
{
    $data = $request->validate([
        'key'         => 'required|string|max:64',
        'fingerprint' => 'required|string|max:128',
        'version'     => 'nullable|string|max:32',
    ]);

    $license = License::where('key', $data['key'])->first();

    // Construir el payload de respuesta (lo que el panel necesita saber)
    $now = now();
    $valid = false;
    $reason = 'not_found';
    $plan = null;
    $expires = null;

    if ($license) {
        // Atar al primer servidor que la activa (anti-reuso simple)
        if (!$license->fingerprint) {
            $license->fingerprint = $data['fingerprint'];
        }
        $fingerprintOk = hash_equals($license->fingerprint, $data['fingerprint']);

        if (!$license->isUsable()) {
            $reason = $license->status === 'active' ? 'expired' : $license->status;
        } elseif (!$fingerprintOk) {
            $reason = 'fingerprint_mismatch';
        } else {
            $valid = true;
            $reason = 'ok';
            $plan = $license->plan;
            $expires = optional($license->expires_at)->toIso8601String();
        }

        // Telemetría mínima
        $license->last_validated_at = $now;
        $license->last_ip = $request->ip();
        $license->last_version = $data['version'] ?? null;
        $license->save();
    }

    // El "payload" es lo que se firma. El panel verifica la firma sobre ESTO.
    $payload = [
        'valid'   => $valid,
        'reason'  => $reason,
        'plan'    => $plan,
        'expires' => $expires,
        'key'     => $data['key'],            // ata la firma a esta key
        'fingerprint' => $data['fingerprint'],// y a este servidor
        'issued_at' => $now->toIso8601String(),
        'ttl_hours' => 72,                    // el panel cacheará hasta 72h
    ];

    // Firmar el JSON canónico con Ed25519 (clave privada del .env)
    $message = json_encode($payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    $privRaw = base64_decode(config('license.private_key')); // 32 bytes (seed)
    $keypair = sodium_crypto_sign_seed_keypair($privRaw);
    $secret  = sodium_crypto_sign_secretkey($keypair);
    $sigRaw  = sodium_crypto_sign_detached($message, $secret);

    return response()->json([
        'payload'   => $payload,
        'signature' => base64_encode($sigRaw),
    ]);
}
```

> **Importante sobre la firma:** el panel reconstruye el `message` exactamente
> igual (mismo JSON, mismas claves, mismo orden) para verificar. Para evitar
> problemas de orden/serialización, el panel firma/verifica sobre el `message`
> string TAL CUAL lo manda Laravel — por eso el panel guarda y verifica el
> `payload` serializado que devuelve el servidor (no lo re-serializa por su
> cuenta). Ver `scripts/license_client.py`.

## 4. Config `config/license.php`

```php
return [
    // Clave PRIVADA Ed25519 (seed de 32 bytes) en base64. SOLO en .env, NUNCA en git.
    'private_key' => env('LICENSE_PRIVATE_KEY'),
];
```

En `.env` (valor real entregado por canal privado):

```
LICENSE_PRIVATE_KEY=<seed_base64_de_32_bytes>
```

## 5. Emitir licencias (comando artisan)

```php
// php artisan license:issue {client_id} --plan=beta --days=90
public function handle()
{
    $key = Str::random(40); // o un formato bonito tipo SVQ-XXXX-XXXX-XXXX
    License::create([
        'key' => $key,
        'client_id' => $this->argument('client_id'),
        'plan' => $this->option('plan') ?? 'beta',
        'status' => 'active',
        'expires_at' => $this->option('days')
            ? now()->addDays((int)$this->option('days')) : null,
        'max_servers' => 1,
    ]);
    $this->info("Licencia emitida: {$key}");
}
```

Idealmente, además: un botón en el **área de cliente** que llame a esto para que
el propio cliente (beta-tester) obtenga su key tras registrarse.

## 6. Flujo completo

1. El cliente se registra en el área de SVQHost → se le emite una licencia
   (`plan=beta`, caduca en X días).
2. Al instalar SVQPanel, introduce la key (la pide `install.sh`, o la mete en la
   pantalla de activación del panel).
3. El panel llama a `POST /api/license/validate` con `{key, fingerprint, version}`.
4. Laravel valida y devuelve `{payload, signature}` firmado.
5. El panel verifica la firma con la clave pública, cachea 72h y desbloquea.
6. Cada ~12h revalida. Si revocas/suspendes la licencia en Laravel, a las ≤72h
   el panel deja de validar y entra en modo restringido.

## 7. Notas de seguridad

- La firma Ed25519 impide falsificar una respuesta "valid:true" sin la clave
  privada. Esa es la garantía fuerte.
- El `fingerprint` ata la licencia a un servidor (anti-compartir). `max_servers`
  permite licencias multi-servidor si algún día las quieres.
- El panel envía SOLO: key + fingerprint + versión. Ningún dato de los clientes
  finales del usuario. Conviene mencionarlo en la doc del panel (transparencia).
- Para producción real, regenerar el par de claves en un entorno privado (las de
  desarrollo/beta no deben ser las definitivas si se han compartido en chats).
