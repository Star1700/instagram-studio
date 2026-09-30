<?php
declare(strict_types=1);
require_once __DIR__ . '/helpers.php';
require_once __DIR__ . '/../lib/StateMachine.php';

final class FakeIg implements InstagramClient {
    public array $calls = [];
    public string $status = 'FINISHED';
    public function createContainer(string $url, string $caption, string $alt): string {
        $this->calls[] = 'create'; return 'container-1';
    }
    public function containerStatus(string $id): string { $this->calls[] = 'status'; return $this->status; }
    public function publish(string $id): string { $this->calls[] = 'publish'; return 'media-1'; }
}

$ig = new FakeIg(); $post = samplePost(); $now = new DateTimeImmutable('2026-09-27T12:00:00Z');
$future = $post; $future['publish_at'] = '2027-01-01T00:00:00Z';
check(StudioState::tick($future, $now, $ig, true)['status'] === 'scheduled', 'future stays queued');
check($ig->calls === [], 'future must not call Instagram');
$pending = StudioState::tick($post, $now, $ig, false);
check($pending['container_id'] === 'container-1' && $pending['status'] === 'container_pending', 'create once');
check($ig->calls === ['create'], 'one step per tick');
$ig->calls = [];
$ready = StudioState::tick($pending, $now, $ig, false);
check($ready['status'] === 'container_pending' && $ready['container_status'] === 'FINISHED', 'ready but not live');
check($ig->calls === ['status'] && $ready['delete_image'] === false, 'no publish or deletion');
$ig->calls = [];
$parked = StudioState::tick($ready, $now, $ig, false);
check($parked['status'] === 'container_pending' && $ig->calls === [], 'finished container rests behind gate');
$sentReady = StudioState::tick($ready, $now, $ig, true);
check($sentReady['status'] === 'sent' && $ig->calls === ['publish'], 'finished container can publish later without recheck');
$ig->calls = [];
$sent = StudioState::tick($pending, $now, $ig, true);
check($sent['status'] === 'sent' && $sent['ig_media_id'] === 'media-1' && $sent['delete_image'], 'fake live transition');
foreach (['ERROR', 'EXPIRED'] as $status) {
    $ig->status = $status; $ig->calls = [];
    $failed = StudioState::tick($pending, $now, $ig, true);
    check($failed['status'] === 'failed' && !$failed['delete_image'], 'failed image retained');
    check($ig->calls === ['status'], 'failed cannot publish');
}
$ig->status = 'IN_PROGRESS';
check(StudioState::tick($pending, $now, $ig, true)['status'] === 'container_pending', 'wait for readiness');
$ig->calls = [];
StudioState::tick($sent, $now, $ig, true);
check($ig->calls === [], 'terminal post is never published twice');
echo "state_machine: ok\n";
