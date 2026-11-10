"""Process startup/HTTP smoke test with mocked external Telegram transport."""
import multiprocessing
import os
import socket
import tempfile
import time
from urllib.request import urlopen
import bot


def worker(directory, port):
    os.environ.update(TELEGRAM_BOT_TOKEN='test', AI_API_KEY='test',
        AI_BASE_URL='https://example.invalid/v1', AI_MODEL='test',
        ALLOWED_USER_IDS='7', DATA_DIR=directory, PORT=str(port))
    def fake(url, payload, headers=None):
        if url.endswith('/getUpdates'):
            time.sleep(.05)
            return {'ok':True, 'result':[]}
        return {'ok':True, 'result':{}}
    bot.post = fake
    bot.main()


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as directory:
        with socket.socket() as s:
            s.bind(('127.0.0.1',0))
            port=s.getsockname()[1]
        proc=multiprocessing.Process(target=worker,args=(directory,port))
        proc.start()
        try:
            for _ in range(50):
                try:
                    with urlopen(f'http://127.0.0.1:{port}/health',timeout=1) as r:
                        assert r.status==200
                        assert r.read()==b'{"status": "ok"}'
                    break
                except OSError:
                    time.sleep(.1)
            else:
                raise AssertionError('Health did not become ready')
        finally:
            proc.terminate()
            proc.join(5)
            if proc.is_alive():
                proc.kill()
                raise AssertionError('Graceful shutdown failed')
        assert proc.exitcode==0, proc.exitcode
        print('PASS: process startup, HTTP health and graceful shutdown (mock Telegram)')
