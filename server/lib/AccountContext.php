<?php
declare(strict_types=1);

/** Resolve installation credentials and keep every account's token separate. */
final class AccountContext {
    public static function resolve(array $config, string $header, string $account): ?array {
        $tenant = null;
        if (Authorization::allowed($config, $header, 'upload')) { $tenant = 'owner'; }
        elseif (str_starts_with($header, 'Bearer ')) {
            $registry = $config['private_dir'] . '/clients.json';
            $clients = is_file($registry) ? json_decode((string)file_get_contents($registry), true, 16, JSON_THROW_ON_ERROR) : [];
            $hash = hash('sha256', substr($header, 7));
            foreach ($clients as $id => $client) {
                if (preg_match('/\A[a-f0-9]{32}\z/', (string)$id)
                    && is_string($client['key_hash'] ?? null) && hash_equals($client['key_hash'], $hash)) {
                    $tenant = $id; break;
                }
            }
        }
        if ($tenant === null || ($account !== '' && !preg_match('/\A[0-9]{1,32}\z/', $account))) { return null; }
        $config['tenant'] = $tenant;
        $config['account_id'] = $account;
        $config['account_key'] = $tenant . ':' . ($account ?: 'pending');
        $legacy = $config['token_path'];
        if ($tenant === 'owner' && ($account === '' || (is_file($legacy)
            && (json_decode((string)file_get_contents($legacy), true)['user_id'] ?? null) === $account))) {
            $config['account_key'] = 'owner';
        } else {
            $config['token_path'] = self::tokenPath($config, $config['account_key']);
        }
        return $config;
    }

    public static function tokenPath(array $config, string $key): string {
        if ($key === 'owner') { return $config['private_dir'] . '/token.json'; }
        if (!preg_match('/\A(owner|[a-f0-9]{32}):([0-9]{1,32}|pending)\z/', $key, $parts)) {
            throw new InvalidArgumentException('Invalid account key');
        }
        return $config['private_dir'] . '/accounts/' . $parts[1] . '/' . $parts[2] . '.json';
    }

    public static function owns(array $post, array $config): bool {
        return ($post['account_key'] ?? 'owner') === $config['account_key'];
    }

    public static function client(array $config, array $post): ?GraphInstagramClient {
        $path = self::tokenPath($config, $post['account_key'] ?? 'owner');
        return is_file($path) ? new GraphInstagramClient($path) : null;
    }

    public static function accounts(array $config): array {
        $paths = glob($config['private_dir'] . '/accounts/' . $config['tenant'] . '/*.json') ?: [];
        if ($config['tenant'] === 'owner' && is_file($config['private_dir'] . '/token.json')) {
            $paths[] = $config['private_dir'] . '/token.json';
        }
        $result = [];
        foreach ($paths as $path) {
            $token = json_decode((string)file_get_contents($path), true, 16, JSON_THROW_ON_ERROR);
            $result[] = ['id' => $token['user_id'], 'username' => $token['username'] ?? '',
                'expires_at' => $token['expires_at']];
        }
        return $result;
    }

    public static function refreshOne(array $config, int $cursor, DateTimeImmutable $now): int {
        $paths = glob($config['private_dir'] . '/accounts/*/*.json') ?: [];
        if (is_file($config['private_dir'] . '/token.json')) { $paths[] = $config['private_dir'] . '/token.json'; }
        sort($paths);
        if (!$paths) { return 0; }
        $index = $cursor % count($paths);
        try { (new GraphInstagramClient($paths[$index]))->refreshIfNeeded($now); }
        catch (Throwable $error) { /* One revoked account must not block the other accounts. */ }
        return ($index + 1) % count($paths);
    }
}
