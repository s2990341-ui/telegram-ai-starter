"""Single-worker Telegram AI starter. Python 3.12+, standard library only."""
import json
import logging
import os
from pathlib import Path
import signal
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen

log = logging.getLogger('bot')


def post(url, payload, headers=None):
    req = Request(url, json.dumps(payload).encode(),
                  {'Content-Type': 'application/json', **(headers or {})})
    with urlopen(req, timeout=65) as response:
        return json.load(response)


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, chat INTEGER, role TEXT, content TEXT);
        CREATE TABLE IF NOT EXISTS quota(chat INTEGER, day TEXT, used INTEGER, PRIMARY KEY(chat,day));
        CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY, value INTEGER);
        ''')

    def offset(self):
        row = self.db.execute("SELECT value FROM state WHERE key='offset'").fetchone()
        return row[0] if row else 0

    def advance(self, offset):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO state VALUES('offset',?)", (offset,))

    def history(self, chat):
        rows = self.db.execute('SELECT role,content FROM messages WHERE chat=? ORDER BY id', (chat,))
        return [dict(role=r, content=c) for r, c in rows]

    def append(self, chat, question, answer):
        with self.db:
            self.db.executemany('INSERT INTO messages(chat,role,content) VALUES(?,?,?)',
                                [(chat, 'user', question), (chat, 'assistant', answer)])
            self.db.execute('DELETE FROM messages WHERE chat=? AND id NOT IN (SELECT id FROM messages WHERE chat=? ORDER BY id DESC LIMIT 12)', (chat, chat))

    def clear(self, chat):
        with self.db:
            self.db.execute('DELETE FROM messages WHERE chat=?', (chat,))

    def reserve(self, chat, limit):
        day = time.strftime('%Y-%m-%d', time.gmtime())
        with self.db:
            self.db.execute('DELETE FROM quota WHERE day<>?', (day,))
            self.db.execute('INSERT OR IGNORE INTO quota VALUES(?,?,0)', (chat, day))
            cur = self.db.execute('UPDATE quota SET used=used+1 WHERE chat=? AND day=? AND used<?', (chat, day, limit))
        return cur.rowcount == 1


class Bot:
    def __init__(self, store, telegram, ai, allowed, daily=30, global_daily=300):
        self.store, self.telegram, self.ai = store, telegram, ai
        self.allowed = allowed
        self.daily, self.global_daily = daily, global_daily

    def send(self, chat, text):
        # Limit by UTF-16 units as well as Python characters (emoji safe).
        chunk, units = '', 0
        for char in text:
            size = len(char.encode('utf-16-le')) // 2
            if units + size > 3500:
                self.telegram('sendMessage', {'chat_id': chat, 'text': chunk})
                chunk, units = '', 0
            chunk += char
            units += size
        if chunk:
            self.telegram('sendMessage', {'chat_id': chat, 'text': chunk})

    def handle(self, update):
        msg = update.get('message', {})
        chat = msg.get('chat', {})
        uid = msg.get('from', {}).get('id')
        if chat.get('type') != 'private' or uid not in self.allowed:
            return
        cid, text = chat['id'], msg.get('text', '').strip()
        command = text.split(maxsplit=1)[0].split('@')[0] if text else ''
        if command in ('/start', '/help'):
            self.send(cid, 'Напиши вопрос. /new — очистить историю; /privacy — обработка данных. Ответы создаёт ИИ и они могут содержать ошибки.')
        elif command in ('/new', '/delete'):
            self.store.clear(cid)
            self.send(cid, 'История этого чата удалена из активной базы. Суточный лимит сохранён.')
        elif command == '/privacy':
            self.send(cid, 'Текст и последние 6 пар сообщений передаются настроенному поставщику ИИ. Они хранятся в базе владельца бота. /delete удаляет историю из активной базы, но не из резервных копий или систем поставщика. Счётчик запросов хранится до смены дня UTC. Не отправляй конфиденциальные данные.')
        elif not text:
            self.send(cid, 'Пока поддерживаются только текстовые сообщения.')
        elif len(text) > 4000:
            self.send(cid, 'Сократи сообщение до 4000 символов.')
        elif not self.store.reserve(cid, self.daily):
            self.send(cid, 'Суточный лимит достигнут. Он обновляется в 00:00 UTC.')
        elif not self.store.reserve(0, self.global_daily):
            self.send(cid, 'Общий суточный лимит бота достигнут.')
        else:
            try:
                answer = self.ai(self.store.history(cid) + [{'role': 'user', 'content': text}])
                if not isinstance(answer, str) or not answer.strip():
                    raise ValueError('Empty AI response')
                answer = answer[:12000]
            except Exception:
                # Never log request URLs, API keys, prompts or exception strings.
                log.warning('AI request failed')
                self.send(cid, 'Сервис ИИ временно недоступен. Попробуй позже.')
                return
            self.store.append(cid, text, answer)
            self.send(cid, answer)


def main():
    required = ['TELEGRAM_BOT_TOKEN', 'AI_API_KEY', 'AI_BASE_URL', 'AI_MODEL', 'ALLOWED_USER_IDS']
    missing = [name for name in required if not os.getenv(name, '').strip()]
    if missing:
        raise SystemExit('Set required variables: ' + ', '.join(missing))
    base = os.environ['AI_BASE_URL'].rstrip('/')
    if not base.startswith('https://'):
        raise SystemExit('AI_BASE_URL must use HTTPS')
    allowed = {int(v.strip()) for v in os.environ['ALLOWED_USER_IDS'].split(',')}
    if not allowed or min(allowed) <= 0:
        raise SystemExit('ALLOWED_USER_IDS must contain positive Telegram user IDs')
    daily = int(os.getenv('DAILY_LIMIT', '30'))
    global_daily = int(os.getenv('GLOBAL_DAILY_LIMIT', '300'))
    if min(daily, global_daily) < 1:
        raise SystemExit('Limits must be positive')
    root = os.getenv('DATA_DIR', '/data')
    store = Store(str(Path(root) / 'bot.sqlite3'))
    stop = threading.Event()
    ready = {'at': 0.0}

    def tg(method, payload):
        response = post('https://api.telegram.org/bot' + os.environ['TELEGRAM_BOT_TOKEN'] + '/' + method, payload)
        if not response.get('ok'):
            raise RuntimeError('Telegram request failed')
        return response['result']

    def ai(messages):
        result = post(base + '/chat/completions', {
            'model': os.environ['AI_MODEL'],
            'messages': [{'role': 'system', 'content': os.getenv('SYSTEM_PROMPT', 'Be helpful and concise. Reply in the user language.')}]+messages,
            'max_tokens': 800,
        }, {'Authorization': 'Bearer ' + os.environ['AI_API_KEY']})
        return result['choices'][0]['message']['content']

    tg('getMe', {})
    if tg('getWebhookInfo', {}).get('url'):
        raise SystemExit('Bot has a webhook. Use a new bot or remove its webhook explicitly before running polling.')
    bot = Bot(store, tg, ai, allowed, daily, global_daily)
    class Health(BaseHTTPRequestHandler):
        def do_GET(self):
            healthy = time.monotonic() - ready['at'] < 120
            code = (200 if healthy else 503) if self.path == '/health' else 404
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'ok' if code == 200 else 'unavailable'}).encode())
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('0.0.0.0', int(os.getenv('PORT', '8080'))), Health)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    log.info('Bot started')
    try:
        while not stop.is_set():
            try:
                updates = tg('getUpdates', {'offset': store.offset(), 'timeout': 30, 'limit': 1, 'allowed_updates': ['message']})
                ready['at'] = time.monotonic()
                for update in updates:
                    # At-most-once processing avoids repeated charges after crashes.
                    store.advance(update['update_id'] + 1)
                    bot.handle(update)
            except Exception:
                log.warning('Polling or delivery failed; retrying')
                stop.wait(5)
    finally:
        server.shutdown()
        store.db.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    main()
