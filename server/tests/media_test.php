<?php
declare(strict_types=1);
require_once __DIR__ . '/helpers.php';
require_once __DIR__ . '/../lib/QueueRunner.php';
require_once __DIR__ . '/../lib/MediaUpload.php';

final class FakeMediaIg implements MediaInstagramClient {
    public array $calls = [];
    public string $status = 'FINISHED';
    public function createContainer(string $url, string $caption, string $alt): string { throw new RuntimeException('wrong image branch'); }
    public function createReel(string $url, string $caption): string { $this->calls[] = ['reel', $url, $caption]; return '901'; }
    public function createCarouselItem(string $url, string $alt): string { $this->calls[] = ['child', $url, $alt]; return (string)(100 + count($this->calls)); }
    public function createCarousel(array $children, string $caption): string { $this->calls[] = ['parent', $children, $caption]; return '900'; }
    public function containerStatus(string $id): string { $this->calls[] = ['status', $id]; return $this->status; }
    public function publish(string $id): string { $this->calls[] = ['publish', $id]; return '999'; }
}

$root = __DIR__ . '/media-' . bin2hex(random_bytes(8)); mkdir($root, 0700); mkdir($root . '/images');
$config = testConfig($root) + ['account_key' => 'owner'];
$store = new PostStore($root); $now = new DateTimeImmutable('2026-09-28T12:00:00Z');
try {
    $image = imagecreatetruecolor(1080, 1350); imagefill($image, 0, 0, imagecolorallocate($image, 90, 120, 80));
    imagejpeg($image, $root . '/source.jpg'); imagedestroy($image);
    $files = ['media_0' => ['tmp_name' => $root . '/source.jpg', 'error' => UPLOAD_ERR_OK],
              'media_1' => ['tmp_name' => $root . '/source.jpg', 'error' => UPLOAD_ERR_OK]];
    $fields = ['media_type' => 'carousel', 'caption' => 'Caption', 'alt_texts' => '["First","Second"]', 'publish_at' => '2026-09-28T10:00:00Z'];
    $metadata = MediaUpload::validate($fields, $files, $now);
    $post = $store->withLock(fn() => MediaUpload::save($config, $store, $metadata, $files, str_repeat('b', 32)));
    check(count($post['media']) === 2 && $post['media'][1]['alt_text'] === 'Second', 'carousel and alternative texts saved');
    foreach (PostMedia::files($post) as $file) { check(is_file($root . '/images/' . $file), 'each carousel JPEG exists'); }
    $retry = $store->withLock(fn() => MediaUpload::save($config, $store, $metadata, $files, str_repeat('b', 32)));
    check($retry['id'] === $post['id'] && count($store->withLock(fn() => $store->all())) === 1, 'lost reply retry never creates second post');
    foreach ([['alt_texts' => '["Only one"]'], ['media_type' => 'unknown'], ['surprise' => 'no']] as $bad) {
        $rejected = false;
        try { MediaUpload::validate(array_replace($fields, $bad), $files, $now); } catch (InvalidArgumentException $error) { $rejected = true; }
        check($rejected, 'invalid media metadata rejected');
    }
    $ig = new FakeMediaIg(); $next = $post;
    for ($step = 0; $step < 5; $step++) {
        $before = count($ig->calls); $next = StudioState::tick($next, $now, $ig, false);
        check(count($ig->calls) - $before === 1, 'one bounded request per state step');
    }
    check(array_column($ig->calls, 0) === ['child', 'status', 'child', 'status', 'parent'], 'children are ready before ordered parent creation');
    check($ig->calls[4][1] === ['101', '103'], 'parent child order matches preview');
    $next = StudioState::tick($next, $now, $ig, false);
    check($next['container_status'] === 'FINISHED' && $next['status'] === 'container_pending', 'live gate also guards carousel');
    $ig->calls = []; $parked = StudioState::tick($next, $now, $ig, false);
    check($ig->calls === [] && !$parked['delete_image'], 'finished carousel is parked without publishing');
    $failedIg = new FakeMediaIg(); $failedIg->status = 'ERROR';
    $failed = StudioState::tick(StudioState::tick($post, $now, $failedIg, false), $now, $failedIg, false);
    check($failed['status'] === 'failed' && !$failed['delete_image'], 'failed child retains all media');
    $store->withLock(fn() => $store->save([$post]));
    $batchIg = new FakeMediaIg();
    (new QueueRunner($config, $store, $batchIg))->run($now);
    check(array_column($batchIg->calls, 0) === ['child', 'status', 'child', 'status', 'parent'], 'ready children progress in one bounded run');
    $store->withLock(fn() => $store->save([$post]));
    $waitingIg = new FakeMediaIg(); $waitingIg->status = 'IN_PROGRESS';
    $waitingRunner = new QueueRunner($config, $store, $waitingIg);
    $waitingRunner->run($now);
    check(count($waitingIg->calls) === 2, 'unfinished child is polled once per run');
    $waitingRunner->run($now);
    check(count($waitingIg->calls) === 3, 'unfinished child resumes without recreation or busy polling');
    $store->withLock(fn() => $store->save([$next]));
    $liveConfig = $config; $liveConfig['allow_live_publish'] = true;
    (new QueueRunner($liveConfig, $store, $ig))->run($now);
    check($ig->calls === [['publish', '900']], 'only fake parent published');
    foreach (PostMedia::files($post) as $file) { check(!is_file($root . '/images/' . $file), 'successful carousel cleans all images'); }
    check(PostMedia::files(['image_file' => '../private.mp4']) === [], 'cleanup stays inside generated media names');

    $reel = samplePost(); $reel['media_type'] = 'video'; $reel['image_file'] = $reel['id'] . '.mp4';
    $reel['image_url'] = 'https://example.test/' . $reel['image_file'];
    $future = $reel; $future['publish_at'] = '2099-01-01T00:00:00Z'; $ig = new FakeMediaIg();
    StudioState::tick($future, $now, $ig, true); check($ig->calls === [], 'future reel makes no API calls');
    $pending = StudioState::tick($reel, $now, $ig, false);
    check($ig->calls[0][0] === 'reel' && $pending['container_id'] === '901', 'video uses reel branch');
    $ready = StudioState::tick($pending, $now, $ig, false);
    check($ready['status'] === 'container_pending' && count($ig->calls) === 2, 'video live gate');

    file_put_contents($root . '/token.json', json_encode(['access_token' => str_repeat('t',40), 'user_id' => '123', 'issued_at' => '2026-09-28', 'expires_at' => '2099-01-01']));
    $calls = [];
    $graph = new GraphInstagramClient($root . '/token.json', static function($method, $url, $fields) use (&$calls) { $calls[] = [$method, $url, $fields]; return ['id' => '123']; });
    $graph->createReel('https://example.test/reel.mp4', 'Caption');
    $graph->createCarouselItem('https://example.test/image.jpg', 'Alt');
    $graph->createCarousel(['123', '456'], 'Carousel caption');
    check(str_starts_with($calls[0][1], 'https://graph.instagram.com/v26.0/'), 'Instagram Login host preserved');
    check($calls[0][2]['media_type'] === 'REELS' && $calls[0][2]['share_to_feed'] === 'true' && !isset($calls[0][2]['alt_text']), 'reel API contract');
    check($calls[1][2]['is_carousel_item'] === 'true' && $calls[1][2]['alt_text'] === 'Alt', 'child API contract');
    check($calls[2][2]['children'] === '123,456' && $calls[2][2]['media_type'] === 'CAROUSEL', 'parent API contract');
    echo "media upload, reels and carousels: ok\n";
} finally {
    $iterator = new RecursiveIteratorIterator(new RecursiveDirectoryIterator($root, FilesystemIterator::SKIP_DOTS), RecursiveIteratorIterator::CHILD_FIRST);
    foreach ($iterator as $item) { $item->isDir() ? rmdir($item->getPathname()) : unlink($item->getPathname()); }
    rmdir($root);
}
