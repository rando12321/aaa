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
