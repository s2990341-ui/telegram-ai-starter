import tempfile
import unittest
from pathlib import Path
from bot import Bot, Store

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.tmp.name)/'db'))
        self.sent, self.calls = [], []
        def ai(messages):
            self.calls.append(messages)
            return 'Ответ'
        self.bot = Bot(self.store, lambda method,payload: self.sent.append(payload), ai, {7, 8}, 2)
    def tearDown(self):
        self.store.db.close()
        self.tmp.cleanup()
    def update(self, text='Привет', uid=7, kind='private'):
        return {'message': {'chat': {'id':uid,'type':kind}, 'from':{'id':uid}, 'text':text}}
    def test_access_denied(self):
        self.bot.handle(self.update(uid=9))
        self.bot.handle(self.update(kind='group'))
        self.assertFalse(self.calls)
        self.assertFalse(self.sent)
    def test_context_isolation(self):
        self.bot.handle(self.update())
        self.bot.handle(self.update('Второй'))
        self.bot.handle(self.update(uid=8))
        self.assertEqual(len(self.calls[1]),3)
        self.assertEqual(len(self.calls[2]),1)
    def test_delete_keeps_quota(self):
        self.bot.handle(self.update())
        self.bot.handle(self.update())
        self.bot.handle(self.update('/delete'))
        self.assertEqual(self.store.history(7),[])
        self.bot.handle(self.update())
        self.assertEqual(len(self.calls),2)
    def test_history_bounded_and_persistent(self):
        for i in range(20): self.store.append(7,str(i),'answer')
        self.store.advance(90)
        other = Store(str(Path(self.tmp.name)/'db'))
        self.assertEqual(len(other.history(7)),12)
        self.assertEqual(other.offset(),90)
        other.db.close()
    def test_provider_failure(self):
        def fail(_): raise RuntimeError('secret must not be logged')
        self.bot.ai=fail
        with self.assertLogs('bot',level='WARNING') as logs:
            self.bot.handle(self.update())
        self.assertNotIn('secret',str(logs.output))
        self.assertEqual(self.store.history(7),[])
    def test_emoji_chunking(self):
        self.bot.send(7,'😀'*4000)
        self.assertEqual(''.join(p['text'] for p in self.sent),'😀'*4000)
        self.assertTrue(all(len(p['text'].encode('utf-16-le'))//2<=3500 for p in self.sent))
    def test_global_limit(self):
        self.bot.global_daily=1
        self.bot.handle(self.update())
        self.bot.handle(self.update(uid=8))
        self.assertEqual(len(self.calls),1)
    def test_oversize(self):
        self.bot.handle(self.update('x'*4001))
        self.assertFalse(self.calls)

if __name__=='__main__': unittest.main()
