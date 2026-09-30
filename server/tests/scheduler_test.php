<?php
declare(strict_types=1);
require_once __DIR__ . '/state_machine_test.php';
require_once __DIR__ . '/instagram_client_test.php';
require_once __DIR__ . '/../lib/QueueRunner.php';
require_once __DIR__ . '/../lib/Authorization.php';
require_once __DIR__ . '/../lib/UploadValidation.php';

$root = __DIR__ . '/work-' . bin2hex(random_bytes(8));
mkdir($root, 0700); mkdir($root . '/images', 0700);
$config = testConfig($root); $store = new PostStore($root);
try {
    check(Authorization::allowed($config, 'Bearer ' . $config['scheduler_secret'], 'scheduler'), 'scheduler key works');
    check(!Authorization::allowed($config, 'Bearer ' . $config['upload_password'], 'scheduler'), 'upload key cannot tick');
    check(!Authorization::allowed($config, 'Bearer ' . $config['scheduler_secret'], 'upload'), 'scheduler cannot upload');
    foreach (['', 'wrong'] as $header) { check(!Authorization::allowed($config, $header, 'scheduler'), 'invalid header fails closed'); }
    $bad = $config; $bad['scheduler_secret'] = $bad['upload_password'];
    check(!Authorization::allowed($bad, 'Bearer ' . $bad['upload_password'], 'scheduler'), 'identical keys rejected');
    $bad['scheduler_secret'] = '';
    check(!Authorization::allowed($bad, 'Bearer ', 'scheduler'), 'empty key rejected');
    $posts = [samplePost(), samplePost(str_repeat('b',32)), samplePost(str_repeat('c',32))];
    $store->withLock(fn() => $store->save($posts));
    $before = file_get_contents($root . '/posts.json');
    (new QueueRunner($config, $store))->run();
    check(file_get_contents($root . '/posts.json') === $before, 'no token leaves queue byte-identical');
    $heartbeat = file_get_contents($root . '/scheduler-state.json');
    check(json_decode($heartbeat, true)['successful_runs'] === 1, 'no-token heartbeat recorded');
    $lock = fopen($root . '/processing.lock','c+b'); flock($lock, LOCK_EX);
    check(!(new QueueRunner($config, $store, new FakeIg()))->run(), 'competing scheduler skips');
    check(file_get_contents($root . '/scheduler-state.json') === $heartbeat, 'busy worker does not claim success');
    check(file_get_contents($root . '/posts.json') === $before, 'busy worker does not mutate queue');
    flock($lock, LOCK_UN); fclose($lock);
    $ig = new FakeIg(); $runner = new QueueRunner($config, $store, $ig);
    $runner->run();
    check($ig->calls === ['create','create'], 'bounded batch');
    $runner->run();
    check(count(array_filter($ig->calls, fn($v) => $v === 'create')) === 3, 'next tick reaches remaining post');
    check(!in_array('publish',$ig->calls,true), 'live gate enforced');
    $saved = $store->withLock(fn() => $store->all());
    check(count($saved) === 3 && $saved[2]['container_id'] !== null, 'progress persisted');
    $future = samplePost(); $future['publish_at'] = '2999-01-01T00:00:00Z';
    $store->withLock(fn() => $store->save([$future])); $ig->calls=[]; $runner->run();
    check($ig->calls === [], 'future posts untouched by runner');
    $pending = samplePost(); $pending['status']='container_pending'; $pending['container_id']='c1';
    $store->withLock(fn() => $store->save([$pending]));
    file_put_contents($root.'/images/'.$pending['image_file'],'disposable');
    $ig->status='ERROR'; $runner->run();
    check(is_file($root.'/images/'.$pending['image_file']), 'failed image retained');
    $parked = $pending; $parked['container_status']='FINISHED';
    $store->withLock(fn() => $store->save([$parked])); $ig->calls=[]; $runner->run();
    check($ig->calls === [], 'finished container does not consume API calls while live gate is closed');
    $store->withLock(fn() => $store->save([$pending])); $ig->status='FINISHED'; $live=$config; $live['allow_live_publish']=true;
    (new QueueRunner($live,$store,$ig))->run();
    check(!is_file($root.'/images/'.$pending['image_file']), 'fake sent image deleted');
    $ig->calls=[]; (new QueueRunner($live,$store,$ig))->run(); check($ig->calls===[], 'sent not repeated');
    $metadata = UploadValidation::metadata(['caption'=>'Größe','alt_text'=>'weiß','publish_at'=>'2026-09-27T12:00:00Z'],new DateTimeImmutable());
    check($metadata['caption']==='Größe','unicode preserved');
    foreach ([['publish_at'=>'2026-02-30T12:00:00Z'],['caption'=>str_repeat('ä',2201)],['allow_live_publish'=>'true']] as $invalid) {
        $rejected=false;
        try { UploadValidation::metadata($invalid,new DateTimeImmutable()); } catch(InvalidArgumentException) { $rejected=true; }
        check($rejected,'invalid metadata rejected');
    }
    $rejected=false; try { UploadValidation::jpeg('not a jpeg'); } catch(InvalidArgumentException) { $rejected=true; }
    check($rejected,'bad image rejected');
    echo "scheduler: ok\n";
} finally {
    foreach (glob($root . '/images/*') as $path) { unlink($path); }
    rmdir($root . '/images');
    foreach (glob($root . '/*') as $path) { unlink($path); }
    rmdir($root);
}
