import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from app import App, numero_brasileiro, ler_csv, literal


class CoreTests(unittest.TestCase):
    def test_normalization(self):
        for value, expected in [('93984108321', '5593984108321'), ('5593984108321', '5593984108321'),
                                ('(11) 2345-6789', '551123456789'), ('+55 (11) 2345-6789', '551123456789')]:
            with self.subTest(value=value):
                self.assertEqual(numero_brasileiro(value), expected)

    def test_invalid(self):
        for value in ['abc93984108321', '123', '1e10', '５５９３９８４１０８３２１', '4493984108321']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                numero_brasileiro(value)

    def test_csv(self):
        for delimiter in [',', ';']:
            with self.subTest(delimiter=delimiter), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'contacts.csv'
                path.write_text('\ufeffphone' + delimiter + 'name\n93984108321' + delimiter + '\n5593984108321' + delimiter + 'Duplicado\n11999999999' + delimiter + 'Ignorado\n' + delimiter + '\n', encoding='utf-8')
                contacts, ignored = ler_csv(path)
                self.assertEqual(len(contacts), 1)
                self.assertEqual(contacts[0]['phone'], '5593984108321')
                self.assertTrue(contacts[0]['nome_gerado'])
                self.assertEqual(ignored, 1)

    def test_missing_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bad.csv'
            path.write_text('phone\n93984108321\n')
            with self.assertRaises(ValueError):
                ler_csv(path)

    def test_wait_and_stop(self):
        app = App.__new__(App)
        app.log = lambda text: None
        app.parar = threading.Event()
        with patch('app.random.randint', return_value=60) as rng, patch.object(app.parar, 'wait', return_value=False) as wait:
            app.aguardar_proximo(30)
            rng.assert_called_once_with(60, 180)
            wait.assert_called_once_with(90)
        app.parar.set()
        with self.assertRaises(InterruptedError):
            app.aguardar_proximo(30)

    def test_xpath_escaping(self):
        self.assertEqual(literal('nome'), "'nome'")
        self.assertTrue(literal('A\'na "Teste"').startswith('concat('))
