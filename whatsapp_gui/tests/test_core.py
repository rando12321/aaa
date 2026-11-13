import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from core import normalize_phone, read_contacts, wait_seconds


class CoreTests(unittest.TestCase):
    def test_normalization(self):
        for value, expected in [('93984108321', '5593984108321'),
                                ('5593984108321', '5593984108321'),
                                ('(11) 2345-6789', '551123456789'),
                                ('+55 (11) 2345-6789', '551123456789')]:
            with self.subTest(value=value):
                self.assertEqual(normalize_phone(value), expected)

    def test_excluded(self):
        for value in ['11999999999', '5511999999999']:
            self.assertIsNone(normalize_phone(value))

    def test_invalid_not_silently_cleaned(self):
        for value in ['abc93984108321', '123', '1e10', '５５９３９８４１０８３２１', '4493984108321']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_phone(value)

    def test_csv(self):
        for delimiter in [',', ';']:
            with self.subTest(delimiter=delimiter), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'contacts.csv'
                path.write_text('\ufeffphone' + delimiter + 'name\n93984108321' + delimiter + '\n5593984108321' + delimiter + 'Duplicado\n11999999999' + delimiter + 'Ignorado\nabc' + delimiter + 'Inválido\n' + delimiter + '\n', encoding='utf-8')
                contacts, errors = read_contacts(path)
                self.assertEqual(len(contacts), 1)
                self.assertEqual(contacts[0].phone, '5593984108321')
                self.assertTrue(contacts[0].name.startswith('Contato '))
                self.assertEqual(len(errors), 1)

    def test_missing_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bad.csv'
            path.write_text('phone\n93984108321\n')
            with self.assertRaises(ValueError):
                read_contacts(path)

    def test_wait(self):
        for extra in (60, 180):
            rng = Mock()
            rng.randint.return_value = extra
            self.assertEqual(wait_seconds(30, rng), 30 + extra)
            rng.randint.assert_called_once_with(60, 180)
        with self.assertRaises(ValueError):
            wait_seconds(-1)


if __name__ == '__main__':
    unittest.main()
