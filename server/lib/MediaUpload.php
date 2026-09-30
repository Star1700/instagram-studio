<?php
declare(strict_types=1);
require_once __DIR__ . '/UploadValidation.php';

final class MediaUpload {
    public static function validate(array $fields, array $files, DateTimeImmutable $now): array {
        if (array_diff(array_keys($fields), ['media_type', 'caption', 'publish_at', 'alt_texts']) !== []) {
            throw new InvalidArgumentException('Unbekannte Upload-Felder.');
        }
        $type = $fields['media_type'] ?? '';
        $count = count($files);
        if (!(($type === 'video' && $count === 1) || ($type === 'carousel' && $count >= 2 && $count <= 10))) {
            throw new InvalidArgumentException('Bitte ein Video oder zwei bis zehn Bilder hochladen.');
        }
        $alts = json_decode(is_string($fields['alt_texts'] ?? null) ? $fields['alt_texts'] : '', true);
        if (!is_array($alts) || !array_is_list($alts) || count($alts) !== $count) {
            throw new InvalidArgumentException('Ungültige Alternativtexte.');
        }
        $metadata = UploadValidation::metadata(array_intersect_key($fields, array_flip(['caption', 'publish_at'])), $now);
        for ($i = 0; $i < $count; $i++) {
            $file = $files['media_' . $i] ?? null;
            if (!is_array($file) || !is_string($file['tmp_name'] ?? null) || ($file['error'] ?? -1) !== UPLOAD_ERR_OK) {
                throw new InvalidArgumentException('Eine Datei konnte nicht hochgeladen werden.');
            }
            UploadValidation::metadata(['alt_text' => $alts[$i]], $now);
            $size = filesize($file['tmp_name']);
            if (!$size || $size > ($type === 'video' ? 100000000 : 8000000)) {
                throw new InvalidArgumentException('Bilder dürfen höchstens 8 MB, Videos höchstens 100 MB groß sein.');
            }
            if ($type === 'video') {
                $head = file_get_contents($file['tmp_name'], false, null, 0, 12);
                $mime = (new finfo(FILEINFO_MIME_TYPE))->file($file['tmp_name']);
                if (substr((string)$head, 4, 4) !== 'ftyp' || !in_array($mime, ['video/mp4', 'application/mp4'], true)) {
                    throw new InvalidArgumentException('Bitte ein gültiges MP4-Video hochladen.');
                }
            } else {
                // Re-encode in place before any public file is created.
                $clean = UploadValidation::jpeg((string)file_get_contents($file['tmp_name']));
                if (file_put_contents($file['tmp_name'], $clean) !== strlen($clean)) { throw new RuntimeException('Image write failed'); }
            }
        }
        return $metadata + ['media_type' => $type, 'alt_texts' => $alts];
    }

    public static function save(array $config, PostStore $store, array $metadata, array $files, string $requestId): array {
        $saved = $store->findRequest($requestId, $config['account_key']);
        if ($saved !== null) { return $saved; }
        $posts = $store->all();
        if (count($posts) >= 1000) { throw new RuntimeException('Queue capacity reached'); }
        $id = bin2hex(random_bytes(16));
        $media = [];
        try {
            foreach ($metadata['alt_texts'] as $index => $alt) {
                $filename = $id . ($metadata['media_type'] === 'video' ? '.mp4' : '-' . $index . '.jpg');
                $path = $config['public_out_dir'] . '/' . $filename;
                $media[] = ['file' => $filename, 'url' => $config['public_base_url'] . '/' . $filename,
                            'alt_text' => $alt, 'container_id' => null];
                if (!copy($files['media_' . $index]['tmp_name'], $path)) { throw new RuntimeException('Media write failed'); }
                chmod($path, 0644);
            }
            unset($metadata['alt_texts']);
            $post = $metadata + ['id' => $id, 'account_key' => $config['account_key'], 'request_id' => $requestId,
                'status' => 'scheduled', 'media' => $media, 'image_file' => $media[0]['file'], 'image_url' => $media[0]['url'],
                'container_id' => null, 'ig_media_id' => null, 'error' => null];
            $posts[] = $post;
            $store->save($posts);
            return $post;
        } catch (Throwable $error) {
            foreach ($media as $item) { $path = $config['public_out_dir'] . '/' . $item['file']; if (is_file($path)) { unlink($path); } }
            throw $error;
        }
    }
}
