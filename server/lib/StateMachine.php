<?php
declare(strict_types=1);
require_once __DIR__ . '/InstagramClient.php';

final class StudioState {
    public static function tick(array $post, DateTimeImmutable $now, InstagramClient $ig, bool $allowLive): array {
        $post['delete_image'] = false;
        if ($post['status'] === 'scheduled') {
            if (new DateTimeImmutable($post['publish_at']) > $now) { return $post; }
            $type = $post['media_type'] ?? 'image';
            if ($type === 'carousel') {
                if (!$ig instanceof MediaInstagramClient) { throw new RuntimeException('Media client required'); }
                // At most one network request per step; persist every child before continuing.
                foreach ($post['media'] as $index => $item) {
                    if (empty($item['container_id'])) {
                        $post['media'][$index]['container_id'] = $ig->createCarouselItem($item['url'], $item['alt_text']);
                        return $post;
                    }
                    if (($item['container_status'] ?? '') !== 'FINISHED') {
                        $status = $ig->containerStatus($item['container_id']);
                        $post['media'][$index]['container_status'] = $status;
                        if (in_array($status, ['ERROR', 'EXPIRED'], true)) {
                            $post['status'] = 'failed';
                            $post['error'] = 'Instagram konnte ein Karussellbild nicht verarbeiten.';
                        }
                        return $post;
                    }
                }
                $post['container_id'] = $ig->createCarousel(array_column($post['media'], 'container_id'), $post['caption']);
            } elseif ($type === 'video') {
                if (!$ig instanceof MediaInstagramClient) { throw new RuntimeException('Media client required'); }
                $post['container_id'] = $ig->createReel($post['image_url'], $post['caption']);
            } else {
                $post['container_id'] = $ig->createContainer($post['image_url'], $post['caption'], $post['alt_text']);
            }
            $post['status'] = 'container_pending';
            $post['container_status'] = 'IN_PROGRESS';
        } elseif ($post['status'] === 'container_pending') {
            if (($post['container_status'] ?? null) === 'FINISHED') {
                if ($allowLive) {
                    $post['ig_media_id'] = $ig->publish($post['container_id']);
                    $post['status'] = 'sent';
                    $post['delete_image'] = true;
                }
                return $post;
            }
            $status = $ig->containerStatus($post['container_id']);
            $post['container_status'] = $status;
            if ($status === 'FINISHED' && $allowLive) {
                $post['ig_media_id'] = $ig->publish($post['container_id']);
                $post['status'] = 'sent';
                $post['delete_image'] = true;
            } elseif (in_array($status, ['ERROR', 'EXPIRED'], true)) {
                $post['status'] = 'failed';
                $post['error'] = $status === 'ERROR' ? 'Instagram konnte die Medien nicht verarbeiten.' : 'Der Instagram-Container ist abgelaufen.';
            }
        }
        return $post;
    }
}
