"""Direct, certificate-verified FTPS operations. Never print credentials."""
from contextlib import contextmanager
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import base64
import ftplib
import hashlib
import io
import json
import secrets
import ssl
import sys

ROOT = Path(__file__).resolve().parents[1]
WEBROOT = '/home/.sites/809/site139/web'
BASE = 'https://www.starseven.at'


def local_config():
    return json.loads((ROOT / 'notebook/config.local.json').read_text(encoding='utf-8-sig'))


@contextmanager
def ftp_connection():
    cfg = local_config()['ftp']
    if cfg.get('protocol') != 'ftps':
        raise ValueError('FTPS required')
    client = ftplib.FTP_TLS(context=ssl.create_default_context(), timeout=30)
    try:
        client.connect(cfg['host'], cfg['port'])
        client.login(cfg['username'], cfg['password'])
        client.prot_p()
        client.cwd('/')
        yield client
    finally:
        client.close()


def http(path, *, method='GET', key=None, data=None, headers=None):
    supplied = dict(headers or {})
    if key:
        supplied['Authorization'] = 'Bearer ' + key
    request = Request(BASE + path, data=data, method=method, headers=supplied)
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, dict(response.headers), response.read(1_000_000)
    except HTTPError as error:
        return error.code, dict(error.headers), error.read(1_000_000)


def mkdir(client, path):
    try:
        client.mkd(path)
    except ftplib.error_perm:
        client.cwd(path)
        client.cwd('/')


def put(client, path, content):
    if not path.startswith(('ig-private/', 'ig-api/', 'ig-out/')):
        raise ValueError('Upload target outside Studio directories')
    temporary = path + '.upload-' + secrets.token_hex(8)
    try:
        client.storbinary('STOR ' + temporary, io.BytesIO(content))
        client.rename(temporary, path)
    finally:
        try:
            client.delete(temporary)
        except ftplib.error_perm:
            pass


def read(client, path):
    result = io.BytesIO()
    client.retrbinary('RETR ' + path, result.write)
    return result.getvalue()


def deploy():
    cfg = local_config()
    password = cfg.get('upload_password', '')
    if not isinstance(password, str) or len(password) < 16:
        raise ValueError('Upload password must contain at least 16 characters')
    secret_file = ROOT / 'server/private/deploy-secrets.json'
    if secret_file.exists():
        deployment = json.loads(secret_file.read_text())
    else:
        deployment = {'scheduler_secret': secrets.token_hex(32), 'allow_live_publish': False}
        secret_file.write_text(json.dumps(deployment, indent=2) + '\n', encoding='utf-8')
    if secrets.compare_digest(password, deployment['scheduler_secret']):
        raise ValueError('Upload and scheduler keys must differ')
    server_cfg = {'upload_password': password, 'scheduler_secret': deployment['scheduler_secret'],
                  'allow_live_publish': bool(deployment.get('allow_live_publish', False)),
                  'private_dir': WEBROOT + '/ig-private',
                  'public_out_dir': WEBROOT + '/ig-out', 'public_base_url': BASE + '/ig-out',
                  'token_path': WEBROOT + '/ig-private/token.json', 'max_batch': 1, 'max_seconds': 10.0}
    # Activation requires the operator's explicit approval to change the local-secret rule.
    enabled = deployment.get('oauth_broker_enabled') is True
    server_cfg.update(oauth_broker_enabled=enabled, oauth_signup_allowed=enabled,
                      redirect_uri=BASE + '/ig-api/oauth-callback.php')
    if enabled:
        if not cfg.get('instagram_app_id') or not cfg.get('instagram_app_secret'):
            raise ValueError('Operator app credentials missing')
        server_cfg.update(instagram_app_id=cfg['instagram_app_id'], instagram_app_secret=cfg['instagram_app_secret'])
    encoded = base64.b64encode(json.dumps(server_cfg).encode()).decode()
    php_config = ("<?php\ndeclare(strict_types=1);\nreturn json_decode(base64_decode('" + encoded + "'), true, 512, JSON_THROW_ON_ERROR);\n").encode()
    (ROOT / 'server/private/config.php').write_bytes(php_config)
    with ftp_connection() as client:
        mkdir(client, 'ig-private')
        # Denial is installed and checked before any private configuration is transferred.
        put(client, 'ig-private/.htaccess', (ROOT / 'server/private/.htaccess').read_bytes())
        probe = 'ig-private/access-check-' + secrets.token_hex(12) + '.txt'
        try:
            put(client, probe, b'private-storage-check')
            directory_status = http('/ig-private/')[0]
            file_status = http('/' + probe)[0]
            if directory_status not in (403, 404) or file_status not in (403, 404):
                raise RuntimeError('Private storage is not protected')
            print(json.dumps({'private_directory_http': directory_status, 'private_file_http': file_status}), flush=True)
        finally:
            client.delete(probe)
        mkdir(client, 'ig-private/lib')
        mkdir(client, 'ig-private/tests')
        mkdir(client, 'ig-private/oauth-codes')
        for path in sorted((ROOT / 'server/lib').glob('*.php')):
            put(client, 'ig-private/lib/' + path.name, path.read_bytes())
        for path in sorted((ROOT / 'server/tests').glob('*.php')):
            put(client, 'ig-private/tests/' + path.name, path.read_bytes())
        put(client, 'ig-private/config.php', php_config)
        # PHP runs as the site's web process and must be able to read the file.
        # HTTP access is independently blocked by the directory .htaccess.
        client.sendcmd('SITE CHMOD 640 ig-private/config.php')
        for directory in ('ig-out', 'ig-api'):
            mkdir(client, directory)
            for path in sorted((ROOT / 'server/public' / directory).iterdir()):
                if path.is_file():
                    put(client, directory + '/' + path.name, path.read_bytes())
    live_state = 'enabled' if server_cfg['allow_live_publish'] else 'disabled'
    print('DEPLOY_OK: private storage, libraries and endpoints; live publishing ' + live_state, flush=True)


def php_tests():
    token = secrets.token_hex(32)
    digest = hashlib.sha256(token.encode()).hexdigest()
    name = 'ig-api/test-' + secrets.token_hex(16) + '.php'
    staging = 'ig-private/check-' + secrets.token_hex(12)
    source = '''<?php
ini_set('display_errors','0'); header('Cache-Control: no-store');
if ($_SERVER['REQUEST_METHOD'] !== 'POST' || !hash_equals('__HASH__',hash('sha256',$_SERVER['HTTP_X_STUDIO_TEST'] ?? ''))) {http_response_code(404);exit;}
header('Content-Type: application/json');
ob_start();
try {
    $staging = dirname(__DIR__).'/__STAGING__';
    $files = new RecursiveIteratorIterator(new RecursiveDirectoryIterator($staging, FilesystemIterator::SKIP_DOTS));
    foreach ($files as $file) { if ($file->getExtension() === 'php') { token_get_all(file_get_contents($file->getPathname()), TOKEN_PARSE); } }
    require $staging.'/tests/accounts_test.php';
    require $staging.'/tests/media_test.php';
    $text=ob_get_clean();
    echo json_encode(['ok'=>true,'results'=>$text,'gd_available'=>function_exists('imagejpeg'),'upload_max_filesize'=>ini_get('upload_max_filesize'),'post_max_size'=>ini_get('post_max_size')]);
} catch(Throwable $error) {
    ob_end_clean(); http_response_code(500);
    echo json_encode(['ok'=>false,'type'=>get_class($error),'test_message'=>$error->getMessage()]);
}
'''.replace('__HASH__', digest).replace('__STAGING__', staging)
    # __DIR__ is /web/ig-api; its parent is the webroot.
    with ftp_connection() as client:
        uploaded = []
        directories = [staging, staging + '/lib', staging + '/tests', staging + '/endpoints']
        try:
            for directory in directories:
                mkdir(client, directory)
            for local, remote in [('lib', 'lib'), ('tests', 'tests'), ('public/ig-api', 'endpoints')]:
                for path in sorted((ROOT / 'server' / local).glob('*.php')):
                    target = staging + '/' + remote + '/' + path.name
                    put(client, target, path.read_bytes())
                    uploaded.append(target)
            put(client, name, source.encode())
            uploaded.append(name)
            status, _, data = http('/' + name, method='POST', data=b'', headers={'X-Studio-Test': token})
            result = json.loads(data)
            print(json.dumps({'http': status, **result}), flush=True)
            if status != 200 or not result.get('ok'):
                raise RuntimeError('PHP tests failed')
        finally:
            for path in reversed(uploaded):
                client.delete(path)
            for directory in reversed(directories):
                client.rmd(directory)
            print('ISOLATED_TEST_FILES_REMOVED', flush=True)


def deploy_media():
    """Update reviewed media sources without rewriting configuration or queue data."""
    sources = [
        ('lib', 'PostMedia.php'), ('lib', 'MediaUpload.php'),
        ('lib', 'InstagramClient.php'), ('lib', 'StateMachine.php'), ('lib', 'QueueRunner.php'),
        ('public/ig-api', 'delete.php'), ('public/ig-api', 'status.php'), ('public/ig-api', 'media-upload.php'),
    ]
    backup = 'ig-private/media-backup-' + secrets.token_hex(12)
    with ftp_connection() as client:
        config_hash = hashlib.sha256(read(client, 'ig-private/config.php')).digest()
        mkdir(client, backup)
        # New dependencies are installed before the worker or endpoints can use them.
        for folder, name in sources:
            target = ('ig-private/lib/' if folder == 'lib' else 'ig-api/') + name
            try:
                previous = read(client, target)
            except ftplib.error_perm as error:
                if not str(error).startswith('550'):
                    raise
            else:
                put(client, backup + '/' + name, previous)
            source = (ROOT / 'server' / folder / name).read_bytes()
            put(client, target, source)
            if hashlib.sha256(read(client, target)).digest() != hashlib.sha256(source).digest():
                raise RuntimeError('Source verification failed')
        if hashlib.sha256(read(client, 'ig-private/config.php')).digest() != config_hash:
            raise RuntimeError('Unexpected configuration change')
    print('MEDIA_DEPLOY_OK: 8 source files verified; configuration preserved; protected source backup saved', flush=True)


def cleanup_phase_one():
    token = secrets.token_hex(32)
    digest = hashlib.sha256(token.encode()).hexdigest()
    name = 'ig-api/cleanup-' + secrets.token_hex(16) + '.php'
    source = '''<?php
ini_set('display_errors','0'); header('Cache-Control: no-store'); header('Content-Type: application/json');
if ($_SERVER['REQUEST_METHOD'] !== 'POST' || !hash_equals('__HASH__',hash('sha256',$_SERVER['HTTP_X_STUDIO_TEST'] ?? ''))) {http_response_code(404);exit;}
try {
    $root=dirname(__DIR__); $config=require $root.'/ig-private/config.php';
    require_once $root.'/ig-private/lib/PostStore.php'; $store=new PostStore($config['private_dir']);
    $removed=$store->withLock(function() use($store,$config) {
        $kept=[]; $count=0;
        foreach($store->all() as $post) {
            if (($post['caption'] ?? '') === 'Phase-1-Wegwerftest') {
                $file=$post['image_file'] ?? '';
                if (is_string($file) && preg_match('/\\A[a-f0-9]{32}\\.jpg\\z/',$file)) {
                    $path=$config['public_out_dir'].'/'.$file; if(is_file($path)){unlink($path);}
                }
                $count++; continue;
            }
            $kept[]=$post;
        }
        $store->save($kept); return $count;
    });
    echo json_encode(['ok'=>true,'removed'=>$removed]);
} catch(Throwable $error) {http_response_code(500);echo json_encode(['ok'=>false]);}
'''.replace('__HASH__', digest)
    with ftp_connection() as client:
        put(client, name, source.encode())
        try:
            status, _, data = http('/' + name, method='POST', data=b'', headers={'X-Studio-Test': token})
            result = json.loads(data)
            if status != 200 or not result.get('ok'):
                raise RuntimeError('Phase 1 cleanup failed')
            print(json.dumps({'phase_one_posts_removed': result['removed']}), flush=True)
        finally:
            client.delete(name)
            print('TEMPORARY_CLEANUP_ENDPOINT_REMOVED', flush=True)


if __name__ == '__main__':
    try:
        {'deploy': deploy, 'deploy-media': deploy_media, 'php-tests': php_tests, 'cleanup-phase-one': cleanup_phase_one}[sys.argv[1]]()
    except Exception as error:
        # Errors can contain echoed server credentials; deliberately print only the type.
        print('HOST_OPERATION_FAILED: ' + type(error).__name__, file=sys.stderr)
        sys.exit(1)
