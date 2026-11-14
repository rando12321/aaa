import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
import app as modulo
from app import App,HistoricoTXT,NumeroRecusado,ler_csv,numero_brasileiro


class HistoryTests(unittest.TestCase):
    def test_file_is_beside_script_not_current_directory(self):
        self.assertEqual(HistoricoTXT().caminho,Path(modulo.__file__).resolve().parent/'enviados.txt')

    def test_persistent_normalized_deduplication_and_no_last_newline(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'enviados.txt'
            path.write_text('\ufeff(93) 98410-8321',encoding='utf-8')
            history=HistoricoTXT(path)
            history.registrar('5593984108321')
            history.registrar('551123456789')
            history.registrar('11987654321')
            self.assertEqual(HistoricoTXT(path).ler(),{'5593984108321','551123456789','5511987654321'})
            self.assertEqual(len(path.read_text(encoding='utf-8-sig').splitlines()),3)

    def test_invalid_history_stops_before_touching_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'enviados.txt';path.write_text('abc\n')
            with self.assertRaisesRegex(ValueError,'linha 1'):
                HistoricoTXT(path).preparar()
            self.assertEqual(path.read_text(),'abc\n')

    def test_csv_allows_same_name_for_different_phones(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'contatos.csv';path.write_text('phone;name\n93984108321;Ana\n11987654321;Ana\n')
            contacts,_=ler_csv(path)
            self.assertEqual([c['name'] for c in contacts],['Ana','Ana'])

    def test_brazilian_number(self):
        self.assertEqual(numero_brasileiro('93984108321'),'5593984108321')
        self.assertEqual(numero_brasileiro('+55 (93) 98410-8321'),'5593984108321')
        with self.assertRaises(ValueError):numero_brasileiro('abc93984108321')


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.app=App.__new__(App)
        self.app.driver=Mock();self.app.parar=threading.Event();self.app.log=Mock()
        self.app.historico=HistoricoTXT(Path(self.tmp.name)/'enviados.txt')
        self.app.envio_incerto=False;self.app.numero_atual=None;self.app.etapa=''
        self.app.contatos=[{'phone':'5593984108321','name':'Ana'},{'phone':'5511987654321','name':'Pedro'},{'phone':'551123456789','name':'Clara'}]
        self.app.mensagem=Mock();self.app.mensagem.get.return_value='Olá, {name}!'
        self.app.intervalo=Mock();self.app.intervalo.get.return_value='30'
        self.app.executar=lambda task:task()
        self.app.abrir_e_detectar=Mock();self.app.enviar=Mock();self.app.fechar_aviso_numero=Mock();self.app.aguardar_proximo=Mock()

    def tearDown(self):self.tmp.cleanup()
    def run_batch(self):
        with patch('app.messagebox.askyesno',return_value=True):self.app.iniciar()

    def test_already_sent_skipped_before_navigation_and_persisted_after_send(self):
        self.app.historico.registrar('93984108321')
        self.run_batch()
        self.assertEqual(self.app.abrir_e_detectar.call_args_list[0].args,('5511987654321',))
        self.assertEqual(self.app.abrir_e_detectar.call_count,2)
        self.assertEqual(self.app.enviar.call_count,2)
        self.app.aguardar_proximo.assert_called_once_with(30)
        self.assertEqual(self.app.historico.ler(),{c['phone'] for c in self.app.contatos})
        self.app.abrir_e_detectar.reset_mock();self.app.enviar.reset_mock();self.app.aguardar_proximo.reset_mock()
        self.run_batch()
        self.app.abrir_e_detectar.assert_not_called();self.app.enviar.assert_not_called();self.app.aguardar_proximo.assert_not_called()

    def test_no_wait_if_remaining_contacts_already_recorded(self):
        for c in self.app.contatos[1:]:self.app.historico.registrar(c['phone'])
        self.run_batch()
        self.app.enviar.assert_called_once_with(self.app.contatos[0],'Olá, Ana!')
        self.app.aguardar_proximo.assert_not_called()

    def test_refusal_is_not_recorded(self):
        self.app.contatos=self.app.contatos[:1]
        self.app.abrir_e_detectar.side_effect=NumeroRecusado('Inválido')
        self.run_batch()
        self.app.enviar.assert_not_called();self.app.aguardar_proximo.assert_not_called()
        self.app.fechar_aviso_numero.assert_called_once()
        self.assertEqual(self.app.historico.ler(),set())

    def test_failed_send_is_not_recorded(self):
        self.app.enviar.side_effect=RuntimeError('Não confirmado')
        with self.assertRaisesRegex(RuntimeError,'Não confirmado'):self.run_batch()
        self.assertEqual(self.app.historico.ler(),set())

    def test_storage_failure_stops_and_blocks_repeat(self):
        self.app.historico.registrar=Mock(side_effect=OSError('sem permissão'))
        with self.assertRaisesRegex(RuntimeError,'falhou a gravação'):self.run_batch()
        self.assertTrue(self.app.envio_incerto)
        self.assertEqual(self.app.historico.ler(),set())
        self.app.enviar.assert_called_once()
        with patch('app.messagebox.showerror') as error:
            self.app.iniciar()
            error.assert_called_once()
        self.app.enviar.assert_called_once()

    def setup_actual_send(self,outgoing):
        self.app.contatos=self.app.contatos[:1]
        contact=self.app.contatos[0]
        self.app.abrir_e_detectar=Mock(side_effect=lambda phone:setattr(self.app,'numero_atual',phone))
        self.app.enviar=App.enviar.__get__(self.app,App)
        field=Mock();field.get_attribute.return_value=''
        self.app.campo_mensagem=Mock(return_value=field)
        self.app.driver.execute_script.return_value='Olá, Ana!'
        self.app.mensagens_saida=Mock(side_effect=[{},outgoing])
        def wait(fn,seconds=30):
            value=fn(self.app.driver)
            if not value:raise RuntimeError('Sem confirmação')
            return value
        self.app.esperar=wait
        return field

    def test_new_outgoing_bubble_is_required_before_writing_txt(self):
        field=self.setup_actual_send({'new-id':'Olá, Ana!'})
        self.run_batch()
        self.assertEqual(self.app.historico.ler(),{'5593984108321'})
        self.assertFalse(self.app.envio_incerto)
        self.assertTrue(any(call.args==('\ue007',) for call in field.send_keys.call_args_list))

    def test_empty_composer_without_new_bubble_is_not_recorded(self):
        self.setup_actual_send({})
        with self.assertRaisesRegex(RuntimeError,'ENVIO INCERTO'):self.run_batch()
        self.assertTrue(self.app.envio_incerto)
        self.assertEqual(self.app.historico.ler(),set())

    def test_multiline_message_is_entered_and_recorded_after_confirmation(self):
        texto='Olá, Ana!\nSegunda linha'
        field=self.setup_actual_send({'new-id':texto})
        self.app.mensagem.get.return_value='Olá, {name}!\nSegunda linha'
        self.app.driver.execute_script.return_value=texto
        self.run_batch()
        self.assertTrue(any(call.args==('\ue008','\ue007') for call in field.send_keys.call_args_list))
        self.assertEqual(self.app.historico.ler(),{'5593984108321'})
