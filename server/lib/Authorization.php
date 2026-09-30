<?php
declare(strict_types=1);

final class Authorization {
    public static function allowed(array $config, string $header, string $kind): bool {
        $upload = $config['upload_password'] ?? '';
        $scheduler = $config['scheduler_secret'] ?? '';
        if (!is_string($upload) || !is_string($scheduler) || strlen($upload) < 16 || strlen($scheduler) < 32 || hash_equals($upload, $scheduler)) { return false; }
        if (!in_array($kind, ['upload', 'scheduler'], true)) { return false; }
        return hash_equals('Bearer ' . ($kind === 'scheduler' ? $scheduler : $upload), $header);
    }
}
