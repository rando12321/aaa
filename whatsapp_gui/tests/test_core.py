import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
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
            app.aguardar_proximo(30, resultado="enviado")
            rng.assert_called_once_with(60, 180)
            wait.assert_called_once_with(90)
        app.parar.set()
        with self.assertRaises(InterruptedError):
            app.aguardar_proximo(30, resultado="enviado")

    def test_xpath_escaping(self):
        self.assertEqual(literal('nome'), "'nome'")
        self.assertTrue(literal('A\'na "Teste"').startswith('concat('))

    def test_no_wait_without_confirmed_send(self):
        app = App.__new__(App)
        app.log = lambda text: None
        app.parar = Mock()
        for resultado in (None, "existente", "recusado", "incerto"):
            app.aguardar_proximo(500, resultado=resultado)
        app.parar.wait.assert_not_called()

    def test_batch_waits_only_after_new_send(self):
        for existing_only in (True, False):
            with self.subTest(existing_only=existing_only):
                app = App.__new__(App)
                app.contatos = [{'phone': str(i), 'name': f'Nome {i}'} for i in range(3)]
                app.driver = Mock()
                app.mensagem = Mock()
                app.mensagem.get.return_value = 'Olá, {name}'
                app.intervalo = Mock()
                app.intervalo.get.return_value = '500'
                app.executar = lambda tarefa: tarefa()
                app.log = Mock()
                app.conferir_parada = Mock()
                app.abrir_e_detectar = Mock(side_effect=[False, not existing_only, False])
                app.cadastrar = Mock()
                app.enviar = Mock()
                app.aguardar_proximo = Mock()
                with patch('app.messagebox.askyesno', return_value=True):
                    app.iniciar()
                self.assertEqual(app.abrir_e_detectar.call_count, 3)
                if existing_only:
                    app.aguardar_proximo.assert_not_called()
                    app.enviar.assert_not_called()
                else:
                    app.aguardar_proximo.assert_called_once_with(500.0, resultado='enviado')
                    app.enviar.assert_called_once_with(app.contatos[1], 'Olá, Nome 1')

    def test_generated_names_short_and_unique_even_if_random_collides(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'contacts.csv'
            path.write_text('phone,name\n' + '\n'.join(f'119{n:08d},' for n in range(129)))
            with patch('app.gerar_nome', return_value='Ana 0001'):
                contacts, ignored = ler_csv(path)
            names = [c['name'] for c in contacts]
            self.assertEqual(len(names), 129)
            self.assertEqual(len(set(names)), 129)
            self.assertTrue(all(len(name) <= 12 for name in names))
