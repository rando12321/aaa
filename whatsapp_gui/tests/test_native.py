import ctypes
import unittest
from unittest.mock import Mock
from app import TecladoWindows


class NativeKeyboardTests(unittest.TestCase):
    def keyboard(self):
        teclado = TecladoWindows.__new__(TecladoWindows)
        teclado.ctypes = ctypes
        teclado.INPUT = TecladoWindows.tipos_entrada()
        teclado.api = Mock()
        teclado.api.GetForegroundWindow.return_value = 123
        teclado.janela = 123
        teclado.events = []
        def send(count, entries, size):
            self.assertEqual(size, ctypes.sizeof(teclado.INPUT))
            teclado.events.append([(e.ki.wVk, e.ki.wScan, e.ki.dwFlags) for e in entries])
            return count
        teclado.api.SendInput.side_effect = send
        return teclado

    def test_windows_input_abi(self):
        expected = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28
        self.assertEqual(ctypes.sizeof(TecladoWindows.tipos_entrada()), expected)

    def test_unicode_shortcut_and_tab(self):
        teclado = self.keyboard()
        parar = Mock()
        parar.is_set.return_value = False
        parar.wait.return_value = False
        teclado.digitar('Á😊', parar, lambda: True)
        self.assertEqual(teclado.events[0][:4], [(17, 0, 0), (65, 0, 0), (65, 0, 2), (17, 0, 2)])
        self.assertEqual(teclado.events[1], [(0, ord('Á'), 4), (0, ord('Á'), 6)])
        self.assertEqual(len(teclado.events[2]), 4)  # UTF-16 surrogate pair.
        self.assertEqual(teclado.events[3], [(9, 0, 0), (9, 0, 2)])

    def test_wrong_foreground_sends_nothing(self):
        teclado = self.keyboard()
        teclado.api.GetForegroundWindow.return_value = 999
        with self.assertRaisesRegex(RuntimeError, 'primeiro plano'):
            teclado.enviar([(65, 0, 0), (65, 0, 2)], lambda: True)
        teclado.api.SendInput.assert_not_called()

    def test_wrong_field_sends_nothing(self):
        teclado = self.keyboard()
        with self.assertRaisesRegex(RuntimeError, 'foco'):
            teclado.enviar([(65, 0, 0), (65, 0, 2)], lambda: False)
        teclado.api.SendInput.assert_not_called()

    def test_stop_before_typing(self):
        teclado = self.keyboard()
        parar = Mock()
        parar.is_set.return_value = True
        with self.assertRaises(InterruptedError):
            teclado.digitar('Ana', parar, lambda: True)
        teclado.api.SendInput.assert_not_called()

    def test_native_mouse_uses_virtual_desktop_coordinates(self):
        from app import DesktopWindows
        base = self.keyboard()
        desktop = DesktopWindows.__new__(DesktopWindows)
        desktop.__dict__.update(base.__dict__)
        desktop.rect = lambda: (0, 0, 100, 100)
        desktop.rect_anterior = desktop.rect()
        desktop.api.GetSystemMetrics.side_effect = lambda n: {76:-1920,77:0,78:3840,79:1080}[n]
        batches = []
        def send(count, entries, size):
            batches.append([(e.mi.dx,e.mi.dy,e.mi.dwFlags) for e in entries])
            return count
        desktop.api.SendInput.side_effect = send
        desktop.clicar(50, 25)
        self.assertEqual(batches[0][0][0], round((50+1920)*65535/3839))
        self.assertEqual([row[2] for row in batches[0]], [0x8000|0x4000|1, 2, 4])

    def test_moved_window_blocks_mouse_input(self):
        from app import DesktopWindows
        base = self.keyboard()
        desktop = DesktopWindows.__new__(DesktopWindows)
        desktop.__dict__.update(base.__dict__)
        desktop.rect_anterior = (0,0,100,100)
        desktop.rect = lambda: (10,0,110,100)
        with self.assertRaisesRegex(RuntimeError, 'janela foi movida'):
            desktop.clicar(50,25)
        desktop.api.SendInput.assert_not_called()

    def test_bound_window_does_not_depend_on_title_or_unique_whatsapp(self):
        teclado=self.keyboard()
        teclado.pid=444
        teclado.listar_janelas=lambda:[{'hwnd':123,'pid':444,'titulo':'Nova guia - Google Chrome'},
                                      {'hwnd':999,'pid':555,'titulo':'WhatsApp - Google Chrome'}]
        self.assertTrue(teclado.ativar('WhatsApp'))
        self.assertEqual(teclado.janela,123)

    def test_reused_window_handle_with_different_process_is_rejected(self):
        teclado=self.keyboard()
        teclado.pid=444
        teclado.listar_janelas=lambda:[{'hwnd':123,'pid':777,'titulo':'WhatsApp'}]
        with self.assertRaisesRegex(RuntimeError,'foi fechada'):
            teclado.ativar('WhatsApp')
        teclado.api.SendInput.assert_not_called()

    def test_foreground_failure_has_specific_error(self):
        from unittest.mock import patch
        teclado=self.keyboard()
        teclado.pid=444
        teclado.listar_janelas=lambda:[{'hwnd':123,'pid':444,'titulo':'WhatsApp'}]
        teclado.api.GetForegroundWindow.return_value=999
        teclado.api.IsIconic.return_value=False
        with patch('app.time.monotonic',side_effect=[0,4]):
            with self.assertRaisesRegex(RuntimeError,'Windows não colocou'):
                teclado.ativar('WhatsApp')
        teclado.api.SendInput.assert_not_called()
