<?php
declare(strict_types=1);
require_once __DIR__ . '/PostStore.php';
require_once __DIR__ . '/AccountContext.php';

/** Hosted code exchange. App credentials never leave this server. */
final class OAuthBroker {
    private Closure $transport;
    public function __construct(private array $config, private PostStore $store, ?Closure $transport = null) {
        $this->transport = $transport ?? Closure::fromCallable([$this, 'request']);
    }

    public function begin(array $input, ?array $context): array {
        if (($this->config['oauth_broker_enabled'] ?? false) !== true
            || empty($this->config['instagram_app_id']) || empty($this->config['instagram_app_secret'])) {
            throw new RuntimeException('Die zentrale Instagram-Anmeldung ist noch nicht aktiviert. Bitte wende dich an den App-Betreiber.');
        }
        foreach (['state', 'verifier_hash', 'key_hash'] as $field) {
            if (!is_string($input[$field] ?? null) || !preg_match('/\A[a-f0-9]{64}\z/', $input[$field])) {
                throw new InvalidArgumentException('Ungültige Verbindungsanfrage.');
            }
        }
        if ($context === null && ($this->config['oauth_signup_allowed'] ?? false) !== true) {
            throw new RuntimeException('Neue Installationen sind noch nicht freigeschaltet. Bitte wende dich an den App-Betreiber.');
        }
        return $this->store->withLock(function () use ($input, $context): array {
            $directory = $this->config['private_dir'] . '/oauth-codes';
            if (!is_dir($directory)) { mkdir($directory, 0700, true); }
            $active = 0;
            foreach (glob($directory . '/*') ?: [] as $file) {
                if (is_file($file) && filemtime($file) < time() - 1800) { unlink($file); }
                else { $active++; }
            }
            if ($active >= 100) { throw new RuntimeException('Zu viele Anmeldungen. Bitte versuche es später erneut.'); }
            if ($context === null && count($this->store->readJson('clients.json')) >= 100) {
                throw new RuntimeException('Neue Installationen sind vorübergehend nicht möglich.');
            }
            $tenant = $context['tenant'] ?? bin2hex(random_bytes(16));
            $path = $directory . '/' . $input['state'] . '.pending';
            if (is_file($path) || is_file($directory . '/' . $input['state'] . '.result')) {
                throw new InvalidArgumentException('Diese Anmeldung wurde bereits gestartet.');
            }
            $this->write($path, ['tenant' => $tenant, 'new_installation' => $context === null,
                'verifier_hash' => $input['verifier_hash'], 'key_hash' => $input['key_hash'], 'created_at' => time()]);
            return ['url' => 'https://www.instagram.com/oauth/authorize?' . http_build_query([
                'client_id' => $this->config['instagram_app_id'], 'redirect_uri' => $this->config['redirect_uri'],
                'response_type' => 'code', 'scope' => 'instagram_business_basic,instagram_business_content_publish',
                'state' => $input['state'], 'force_reauth' => 'true', 'enable_fb_login' => 'false',
            ], '', '&', PHP_QUERY_RFC3986)];
        });
    }

    public function pickup(string $state, string $verifier): ?array {
        if (!preg_match('/\A[a-f0-9]{64}\z/', $state) || !preg_match('/\A[a-f0-9]{64}\z/', $verifier)) {
            throw new InvalidArgumentException('Ungültige Verbindungsanfrage.');
        }
        return $this->store->withLock(function () use ($state, $verifier): ?array {
            $path = $this->config['private_dir'] . '/oauth-codes/' . $state . '.result';
            if (!is_file($path)) { return null; }
            $saved = json_decode((string)file_get_contents($path), true, 16, JSON_THROW_ON_ERROR);
            if (($saved['created_at'] ?? 0) < time() - 1800
                || !hash_equals($saved['verifier_hash'] ?? '', hash('sha256', $verifier))) { return null; }
            if (isset($saved['error'])) { return ['state' => 'denied']; }
            if (isset($saved['completed'])) { return $saved['completed']; }
            try {
                if (!isset($saved['token'])) {
                    $short = ($this->transport)('POST', 'https://api.instagram.com/oauth/access_token', [
                        'client_id' => $this->config['instagram_app_id'], 'client_secret' => $this->config['instagram_app_secret'],
                        'grant_type' => 'authorization_code', 'redirect_uri' => $this->config['redirect_uri'], 'code' => $saved['code'],
                    ]);
                    $short = $short['data'][0] ?? $short;
                    $permissions = $short['permissions'] ?? '';
                    if (is_string($permissions)) { $permissions = explode(',', $permissions); }
                    if (!is_array($permissions) || array_diff(['instagram_business_basic', 'instagram_business_content_publish'], $permissions)) {
                        throw new RuntimeException('Bitte erlaube in Instagram sowohl den Profilzugriff als auch das Veröffentlichen.');
                    }
                    $long = ($this->transport)('GET', 'https://graph.instagram.com/access_token', [
                        'grant_type' => 'ig_exchange_token', 'client_secret' => $this->config['instagram_app_secret'],
                        'access_token' => $short['access_token'],
                    ]);
                    if (!is_string($long['access_token'] ?? null) || strlen($long['access_token']) < 20
                        || !is_int($long['expires_in'] ?? null) || $long['expires_in'] < 3600) { throw new RuntimeException('Invalid token'); }
                    $saved['token'] = $long;
                    unset($saved['code']);
                    $this->write($path, $saved);
                }
                $token = $saved['token'];
                $who = ($this->transport)('GET', 'https://graph.instagram.com/v26.0/me', [
                    'fields' => 'user_id,username,account_type', 'access_token' => $token['access_token'],
                ]);
                $id = (string)($who['user_id'] ?? '');
                if (!preg_match('/\A[0-9]{1,32}\z/', $id) || !is_string($who['username'] ?? null)
                    || !in_array($who['account_type'] ?? '', ['BUSINESS', 'MEDIA_CREATOR'], true)) { throw new RuntimeException('Invalid professional account'); }
                $context = $this->config + ['tenant' => $saved['tenant']];
                $existing = AccountContext::accounts($context);
                if (count($existing) >= 20 && !in_array($id, array_column($existing, 'id'), true)) { throw new RuntimeException('Account capacity'); }
                $key = $saved['tenant'] . ':' . $id;
                $legacy = $this->config['private_dir'] . '/token.json';
                if ($saved['tenant'] === 'owner' && is_file($legacy)
                    && (json_decode((string)file_get_contents($legacy), true)['user_id'] ?? '') === $id) { $key = 'owner'; }
                $tokenPath = AccountContext::tokenPath($this->config, $key);
                if (!is_dir(dirname($tokenPath))) { mkdir(dirname($tokenPath), 0700, true); }
                $now = new DateTimeImmutable('now', new DateTimeZone('UTC'));
                $this->write($tokenPath, ['user_id' => $id, 'username' => $who['username'], 'access_token' => $token['access_token'],
                    'issued_at' => $now->format('Y-m-d\TH:i:s\Z'),
                    'expires_at' => $now->modify('+' . $token['expires_in'] . ' seconds')->format('Y-m-d\TH:i:s\Z')]);
                if ($saved['new_installation']) {
                    $clients = $this->store->readJson('clients.json');
                    $clients[$saved['tenant']] = ['key_hash' => $saved['key_hash'], 'created_at' => $now->format(DATE_ATOM)];
                    $this->store->writeJson('clients.json', $clients);
                }
                $result = ['state' => 'connected', 'installation_id' => $saved['tenant'],
                    'account' => ['id' => $id, 'username' => $who['username']]];
                unset($saved['token']);
                $saved['completed'] = $result; $this->write($path, $saved);
                return $result;
            } catch (Throwable $error) {
                // Do not expose provider responses, codes, URLs or credentials.
                throw new RuntimeException('Instagram konnte die Verbindung nicht bestätigen. Verwende ein Creator- oder Business-Konto, nimm die Instagram-Tester-Einladung an und erlaube beide angefragten Rechte. Starte die Verbindung anschließend erneut.');
            }
        });
    }

    private function write(string $path, array $value): void {
        $temp = $path . '.' . bin2hex(random_bytes(8)) . '.tmp';
        try {
            $json = json_encode($value, JSON_THROW_ON_ERROR);
            if (file_put_contents($temp, $json, LOCK_EX) !== strlen($json)) { throw new RuntimeException('write'); }
            chmod($temp, 0600);
            if (!rename($temp, $path)) { throw new RuntimeException('rename'); }
        } finally { if (is_file($temp)) { unlink($temp); } }
    }

    private function request(string $method, string $url, array $parameters): array {
        $header = "Accept: application/json\r\n";
        if (isset($parameters['access_token']) && !isset($parameters['grant_type'])) {
            $header .= 'Authorization: Bearer ' . $parameters['access_token'] . "\r\n";
            unset($parameters['access_token']);
        }
        $options = ['http' => ['method' => $method, 'timeout' => 8, 'ignore_errors' => true, 'header' => $header]];
        if ($method === 'POST') {
            $options['http']['content'] = http_build_query($parameters);
            $options['http']['header'] .= "Content-Type: application/x-www-form-urlencoded\r\n";
        } else { $url .= '?' . http_build_query($parameters); }
        $raw = @file_get_contents($url, false, stream_context_create($options));
        $result = $raw !== false ? json_decode($raw, true) : null;
        if (!is_array($result) || isset($result['error']) || isset($result['error_type'])) { throw new RuntimeException('OAuth failed'); }
        return $result;
    }
}
