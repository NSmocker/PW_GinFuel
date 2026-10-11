import tempfile
import unittest
from pathlib import Path

from clean_arch.infrastructure.string_tables import load_game_string_tables, load_stf


class StringTableTests(unittest.TestCase):
    def test_load_stf_reads_utf16_tab_quoted_entries(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.stf"
            path.write_text('1\t"Привіт"\n2\t"%s готово"\n',
                            encoding="utf-16")
            self.assertEqual(load_stf(str(path)),
                             {1: "Привіт", 2: "%s готово"})

    def test_msgbox_can_live_beside_other_tables(self):
        with tempfile.TemporaryDirectory() as folder:
            for name in ("ingame.stf", "loginui.stf", "msgbox.stf"):
                Path(folder, name).write_text('1\t"Текст"\n', encoding="utf-16")
            tables = load_game_string_tables(folder)
            self.assertEqual(tables["msgbox"], {1: "Текст"})
