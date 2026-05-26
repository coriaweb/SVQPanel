<?php
/**
 * SVQPanel Autologin Plugin para Roundcube
 *
 * Permite iniciar sesión automáticamente en Roundcube desde el panel SVQPanel
 * mediante un token de un solo uso de 60 segundos.
 *
 * Flujo:
 *   1. El panel SVQPanel genera un token  →  POST /api/mail/domains/{id}/mailboxes/{id}/webmail-token
 *   2. El panel abre en nueva pestaña:      https://servidor/webmail/?svqtoken=TOKEN
 *   3. Este plugin intercepta el startup de Roundcube
 *   4. Valida el token contra el endpoint interno del panel (solo localhost)
 *   5. Llama a $rcmail->login() con las credenciales recibidas
 *   6. Redirige a la bandeja de entrada
 *
 * Instalación (install.sh lo hace automáticamente):
 *   /usr/share/roundcube/plugins/svqpanel_autologin/svqpanel_autologin.php
 *
 * Seguridad:
 *   - El endpoint interno solo acepta peticiones desde 127.0.0.1
 *   - Cada token es UUID aleatorio de 32 caracteres hexadecimales
 *   - El token caduca a los 60 segundos
 *   - El token se invalida tras el primer uso (single-use)
 */
class svqpanel_autologin extends rcube_plugin
{
    /** Enlaza con todos los tasks para poder interceptar el startup */
    public $task = '.*';

    /** No necesita frame ni AJAX propio */
    public $noframe = true;
    public $noajax  = false;

    /** Puerto del panel SVQPanel (debe coincidir con PANEL_PORT en .env) */
    private const PANEL_PORT = 8001;

    /** Tiempo máximo de espera para la llamada al panel (segundos) */
    private const FETCH_TIMEOUT = 5;

    // ------------------------------------------------------------------

    public function init(): void
    {
        $this->add_hook('startup', [$this, 'startup']);
    }

    /**
     * Hook startup: si hay un svqtoken en la URL, intenta autologin.
     */
    public function startup(array $args): array
    {
        // Solo actuar si el parámetro svqtoken está presente
        $raw_token = $_GET['svqtoken'] ?? $_POST['svqtoken'] ?? null;
        if (!$raw_token) {
            return $args;
        }

        // Validar formato del token (UUID hex de 32 chars, sin guiones)
        $token = preg_replace('/[^a-f0-9]/', '', strtolower($raw_token));
        if (strlen($token) !== 32) {
            rcube::raise_error(
                ['code' => 403, 'type' => 'php',
                 'message' => 'svqpanel_autologin: formato de token inválido'],
                true, false
            );
            return $args;
        }

        // Obtener credenciales del panel (llamada localhost)
        $data = $this->fetch_credentials($token);
        if (!$data || empty($data['username']) || empty($data['password'])) {
            return $args;
        }

        $rcmail = rcube::get_instance();

        // Intentar login directo con las credenciales obtenidas
        $host = $data['imap_host'] ?? 'localhost';
        if ($rcmail->login($data['username'], $data['password'], $host, false)) {
            // Login exitoso: limpiar lang de sesión y redirigir al correo
            $rcmail->session->remove('user_lang');

            // Forzar cookie de sesión
            if (function_exists('rcube_utils::setcookie')) {
                rcube_utils::setcookie(
                    $rcmail->config->get('session_name', 'roundcube_sessid'),
                    session_id(),
                    0
                );
            }

            $rcmail->output->redirect(['_task' => 'mail']);
            exit;
        }

        // Si el login falla, dejar que Roundcube muestre la página normal
        return $args;
    }

    // ------------------------------------------------------------------

    /**
     * Llama al endpoint interno del panel para validar el token
     * y obtener las credenciales IMAP.
     *
     * @param  string $token  Token UUID hex de 32 chars
     * @return array|null     ['username', 'password', 'imap_host', 'imap_port'] o null
     */
    private function fetch_credentials(string $token): ?array
    {
        $url = sprintf(
            'http://127.0.0.1:%d/api/internal/webmail-token/%s',
            self::PANEL_PORT,
            rawurlencode($token)
        );

        $context = stream_context_create([
            'http' => [
                'method'         => 'GET',
                'timeout'        => self::FETCH_TIMEOUT,
                'ignore_errors'  => true,
                'header'         => "Accept: application/json\r\n",
            ],
        ]);

        $response = @file_get_contents($url, false, $context);

        if ($response === false || $response === '') {
            rcube::raise_error(
                ['code' => 500, 'type' => 'php',
                 'message' => 'svqpanel_autologin: no se pudo contactar con el panel'],
                true, false
            );
            return null;
        }

        $data = json_decode($response, true);
        if (json_last_error() !== JSON_ERROR_NONE) {
            return null;
        }

        // El panel devuelve 404/410 con {"detail": "..."} si el token no es válido
        if (isset($data['detail'])) {
            return null;
        }

        return $data;
    }
}
