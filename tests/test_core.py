# -*- coding: utf-8 -*-
"""Automated test suite for Colab Model Hub."""

from __future__ import annotations

import ast
import json
import os
import pathlib
import sys
import tempfile
import unittest
from types import SimpleNamespace

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class CoreTests(unittest.TestCase):
    def test_ast_and_no_unused_imports(self) -> None:
        py_files = sorted(
            [str(p) for p in ROOT.glob("*.py")]
            + [str(p) for p in (ROOT / "gui").glob("*.py")]
        )
        self.assertGreaterEqual(len(py_files), 10)
        for f in py_files:
            src = pathlib.Path(f).read_text(encoding="utf-8")
            tree = ast.parse(src, filename=f)
            imported = {}
            used = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for a in node.names:
                        imported[a.asname or a.name.split(".")[0]] = node.lineno
                elif isinstance(node, ast.ImportFrom):
                    if node.module == "__future__":
                        continue
                    for a in node.names:
                        imported[a.asname or a.name] = node.lineno
                elif isinstance(node, ast.Name):
                    used.add(node.id)
            unused = [(k, v) for k, v in imported.items() if k not in used]
            self.assertEqual(unused, [], f"Unused imports in {f}: {unused}")

    def test_i18n_key_parity(self) -> None:
        from i18n import TRANSLATIONS, tr

        zh_keys = set(TRANSLATIONS["zh"].keys())
        en_keys = set(TRANSLATIONS["en"].keys())
        self.assertEqual(zh_keys, en_keys)
        self.assertIn("Deploy", tr("btn_deploy", lang="en"))
        self.assertIn("部署", tr("btn_deploy", lang="zh"))

    def test_vram_tiers_and_mmproj_filter(self) -> None:
        from hf_explorer import HFExplorer, evaluate_vram

        _, st_t4, txt_t4, _ = evaluate_vram(14.0, 4096, gpu_type="T4", lang="en")
        _, st_l4, txt_l4, _ = evaluate_vram(14.0, 4096, gpu_type="L4", lang="en")
        _, st_a100, _, _ = evaluate_vram(14.0, 4096, gpu_type="A100", lang="en")
        _, st_cpu, txt_cpu, _ = evaluate_vram(4.5, 4096, gpu_type="CPU", lang="en")

        self.assertEqual(st_t4, "overload")
        self.assertIn("15.00 GB", txt_t4)
        self.assertEqual(st_l4, "safe")
        self.assertIn("22.50 GB", txt_l4)
        self.assertEqual(st_a100, "safe")
        self.assertEqual(st_cpu, "safe")
        self.assertIn("CPU Mode", txt_cpu)

        exp = HFExplorer()
        fake_siblings = [
            SimpleNamespace(rfilename="mmproj-model-f16.gguf", size=1024**3),
            SimpleNamespace(rfilename="README.md", size=1024),
            SimpleNamespace(rfilename="model-Q8_0.gguf", size=8 * 1024**3),
            SimpleNamespace(rfilename="model-Q4_K_M.gguf", size=4 * 1024**3),
        ]
        exp.api = SimpleNamespace(
            model_info=lambda repo_id, files_metadata=True: SimpleNamespace(siblings=fake_siblings)
        )
        quants = exp.get_model_quants("test/repo", ctx_size=4096, gpu_type="L4", lang="en")
        self.assertEqual([q.filename for q in quants], ["model-Q4_K_M.gguf", "model-Q8_0.gguf"])

    def test_config_manager_empty_ssh_key_and_defaults(self) -> None:
        from config_manager import ConfigManager

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = pathlib.Path(tmpdir) / "config.json"
            cm = ConfigManager(config_path=cfg_path)
            cm.config.ssh_key_path = ""
            resolved = cm.ensure_ssh_key()
            self.assertTrue(resolved and resolved != "." and pathlib.Path(resolved).is_file())

    def test_orchestrator_template_and_session_parsing(self) -> None:
        import colab_orchestrator as co

        rendered = (
            co.REMOTE_DEPLOY_TEMPLATE.replace("__REPO_ID__", json.dumps('org/repo-"test"'))
            .replace("__FILENAME__", json.dumps("model\\part.gguf"))
            .replace("__MODEL_ALIAS__", json.dumps('alias"x'))
            .replace("__CTX_SIZE__", "4096")
            .replace("__API_KEY__", json.dumps('sk-"test\\key'))
            .replace("__HF_TOKEN__", json.dumps(""))
            .replace("__ENABLE_GDRIVE__", "True")
            .replace("__LLAMA_CPP_TAG__", json.dumps("b12556"))
        )
        ast.parse(rendered, filename="rendered_deploy_template.py")
        self.assertIn(": 10,", rendered)
        self.assertIn("timeout=180", rendered)
        self.assertIn("crashed_early", rendered)

        sample = (
            "[colab-llm-server] gpu-t4-s-abc123 | Hardware: T4 | Shape: Standard | Variant: GPU\n"
            "[?] gpu-t4-s-orphan99 | Hardware: T4 | Shape: Standard | Variant: GPU\n"
        )
        named, orphans = co.ColabOrchestrator.parse_sessions_output(sample)
        self.assertEqual(named, ["colab-llm-server"])
        self.assertEqual(orphans, ["gpu-t4-s-orphan99"])

    def test_gui_bilingual_and_edge_cases(self) -> None:
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication
        from config_manager import config_mgr
        from gui.main_window import MainWindow
        from gui.theme import setup_theme
        from hf_explorer import QuantFileInfo

        app = QApplication.instance() or QApplication([])
        setup_theme(app)
        win = MainWindow()
        win.show()
        app.processEvents()

        # Stale quant error ignored
        win._quants_req_id = 5
        win.quant_combo.clear()
        win.quant_combo.addItem("loading...")
        win.current_quants = []
        win.on_quants_error(4, "stale")
        self.assertEqual(win.quant_combo.currentText(), "loading...")

        # Valid quant load + language toggle
        orig_lang = config_mgr.config.language
        orig_port = config_mgr.config.api_port
        try:
            q_dummy = QuantFileInfo("dummy.gguf", 100, 4.0, "Q4_K_M", 6.9, "safe", "ok", "#10b981")
            win.on_quants_loaded(5, [q_dummy])
            self.assertEqual(len(win.current_quants), 1)

            config_mgr.config.language = "en"
            config_mgr.config.api_port = 19999
            win.retranslate_ui()
            self.assertEqual(win.btn_tab_outgoing.text(), "Chat Playground")
            self.assertIn("19999", win.chat_widget.status_lbl.text())

            win.switch_tab("chat")
            app.processEvents()
            self.assertFalse(win.autoscroll_check.isVisible())
            QTest.keyClicks(win.chat_widget.msg_input, "abc")
            self.assertEqual(win.chat_widget.msg_input.text(), "abc")

            cw = win.chat_widget
            cw.messages = [{"role": "user", "content": "hi"}]
            cw._stream_gen = 2
            cw.on_token(1, "STALE")
            self.assertEqual(cw._current_reply, "")
            cw.on_error(2, "Connection refused (10061)")
            self.assertEqual(cw.messages, [])
            self.assertTrue(cw.btn_send.isEnabled())
        finally:
            config_mgr.config.language = orig_lang
            config_mgr.config.api_port = orig_port
            win.retranslate_ui()
            win.close()


if __name__ == "__main__":
    unittest.main()
