<?php
declare(strict_types=1);
require_once __DIR__ . '/PostStore.php';
require_once __DIR__ . '/StateMachine.php';
require_once __DIR__ . '/PostMedia.php';

final class QueueRunner {
    public function __construct(private array $config, private PostStore $store,
        private ?InstagramClient $client = null, private ?Closure $clientFactory = null,
        private ?Closure $maintenance = null) {}

    public function run(?DateTimeImmutable $now = null): bool {
        return $this->store->withLock(fn() => $this->runLocked($now), true) !== false;
    }

    public function runLocked(?DateTimeImmutable $now = null): bool {
        $now ??= new DateTimeImmutable('now', new DateTimeZone('UTC'));
        $now = $now->setTimezone(new DateTimeZone('UTC'));
        $heartbeat = $this->store->readJson('scheduler-state.json');
        $cursor = (int)($heartbeat['next_cursor'] ?? 0);
        $tokenCursor = (int)($heartbeat['token_cursor'] ?? 0);
        if ($this->maintenance !== null) { $tokenCursor = ($this->maintenance)($tokenCursor, $now); }
        $processed = 0;
        // No client/token means absolutely no queue read or write, even for due posts.
        if ($this->client !== null || $this->clientFactory !== null) {
            if ($this->client instanceof RefreshableInstagramClient) { $this->client->refreshIfNeeded($now); }
            $posts = $this->store->all();
            $count = count($posts);
            $limit = max(1, min(25, (int)($this->config['max_batch'] ?? 10)));
            $deadline = microtime(true) + max(0.01, min(20.0, (float)($this->config['max_seconds'] ?? 10)));
            for ($visited = 0; $visited < $count && $processed < $limit && microtime(true) < $deadline; $visited++) {
                $index = $cursor % $count;
                $cursor = ($index + 1) % $count;
                $post = $posts[$index];
                if (!in_array($post['status'], ['scheduled', 'container_pending'], true)) { continue; }
                if (new DateTimeImmutable($post['publish_at']) > $now) { continue; }
                $allowLive = ($this->config['allow_live_publish'] ?? false) === true;
                if (!$allowLive && $post['status'] === 'container_pending'
                    && ($post['container_status'] ?? null) === 'FINISHED') { continue; }
                $client = $this->clientFactory !== null ? ($this->clientFactory)($post) : $this->client;
                if ($client === null) { continue; }
                if ($this->clientFactory !== null && $client instanceof RefreshableInstagramClient) {
                    try { $client->refreshIfNeeded($now); }
                    catch (Throwable $error) { $processed++; continue; }
                }
                // Continue ready carousel children within this run, saving after each call.
                // Never poll an unfinished child twice in one minute's run.
                for ($step = 0; $step < 21 && microtime(true) < $deadline; $step++) {
                    try {
                        $next = StudioState::tick($post, $now, $client, $allowLive);
                    } catch (Throwable $error) {
                        $post['error'] = 'Instagram ist gerade nicht erreichbar oder die Freigabe ist ungültig. Bitte prüfe die Verbindung.';
                        $posts[$index] = $post;
                        $this->store->save($posts);
                        break;
                    }
                    $delete = $next['delete_image']; unset($next['delete_image']);
                    $posts[$index] = $next;
                    $this->store->save($posts);
                    if ($delete) { PostMedia::cleanup($post, $this->config['public_out_dir']); }
                    if (($next['media_type'] ?? '') !== 'carousel' || $next['status'] !== 'scheduled') { break; }
                    $waiting = false;
                    foreach ($next['media'] as $item) {
                        if (($item['container_status'] ?? '') === 'IN_PROGRESS') { $waiting = true; break; }
                    }
                    if ($waiting || $next === $post) { break; }
                    $post = $next;
                }
                $processed++;
            }
        }
        $this->store->writeJson('scheduler-state.json', [
            'last_success_at' => $now->format('Y-m-d\TH:i:s.u\Z'),
            'successful_runs' => (int)($heartbeat['successful_runs'] ?? 0) + 1,
            'next_cursor' => $cursor, 'last_processed' => $processed, 'token_cursor' => $tokenCursor,
        ]);
        return true;
    }
}
