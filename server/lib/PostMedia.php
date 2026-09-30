<?php
declare(strict_types=1);

final class PostMedia {
    public static function files(array $post): array {
        $files = isset($post['media']) ? array_column($post['media'], 'file') : [$post['image_file'] ?? ''];
        return array_values(array_filter($files, static fn($name): bool => is_string($name)
            && preg_match('/\A[a-f0-9]{32}(?:-[0-9])?\.(?:jpg|mp4)\z/', $name) === 1));
    }

    public static function cleanup(array $post, string $directory): void {
        foreach (self::files($post) as $name) {
            $path = $directory . '/' . $name;
            if (is_file($path) && !unlink($path)) { throw new RuntimeException('Media cleanup failed'); }
        }
    }
}
