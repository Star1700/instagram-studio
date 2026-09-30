<?php
declare(strict_types=1);

function check(bool $condition, string $message): void {
    if (!$condition) { throw new RuntimeException($message); }
}

function testConfig(string $root): array {
    return ['private_dir' => $root, 'public_out_dir' => $root . '/images',
        'public_base_url' => 'https://www.starseven.at/ig-out',
        'upload_password' => str_repeat('u', 40), 'scheduler_secret' => str_repeat('s', 40),
        'allow_live_publish' => false, 'max_batch' => 2, 'max_seconds' => 2.0];
}

function samplePost(string $id = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'): array {
    return ['id' => $id, 'status' => 'scheduled', 'caption' => 'Test', 'alt_text' => 'Testbild',
        'image_file' => $id . '.jpg', 'image_url' => 'https://www.starseven.at/ig-out/' . $id . '.jpg',
        'publish_at' => '2026-01-01T00:00:00Z', 'container_id' => null,
        'ig_media_id' => null, 'error' => null];
}
