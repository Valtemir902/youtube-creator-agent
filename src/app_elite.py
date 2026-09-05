from __future__ import annotations

import os

from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from app_gui import ARQUIVO_TOKEN, BASE_DIR, JanelaPrincipal
from ai.runtime import AIRuntime
from ai.settings import AISettings
from elite_workers import EliteSEOAgentWorker, ModelDiscoveryWorker, ResearchWorker

AI_SETTINGS_FILE = os.path.join(BASE_DIR, "config", "ai_settings.json")


class JanelaElite(JanelaPrincipal):
    def __init__(self):
        self.ai_runtime = AIRuntime(AI_SETTINGS_FILE)
        self.ai_settings = self.ai_runtime.load_settings()
        super().__init__()
        self.setWindowTitle("YouTube Creator Agent Elite")
        self.lbl_status_api.setText(self._status_ai_text())

    def _status_ai_text(self) -> str:
        model = self.ai_settings.model or "modelo não selecionado"
        return f"🧠 IA: {self.ai_settings.provider.upper()} · {model}"

    def criar_pagina_config(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(50, 40, 50, 40)
        title = QLabel("Configuração Profissional de IA")
        title.setObjectName("titulo_pagina")
        layout.addWidget(title)

        note = QLabel("Escolha o provedor, informe a credencial quando necessária e carregue os modelos realmente disponíveis na conta.")
        note.setWordWrap(True)
        layout.addWidget(note)

        provider_row = QHBoxLayout()
        provider_row.addWidget(QLabel("Provedor:"))
        self.combo_ai_provider = QComboBox(); self.combo_ai_provider.setObjectName("combo_box")
        providers = list(self.ai_runtime.registry.available_providers())
        self.combo_ai_provider.addItems(providers)
        if self.ai_settings.provider in providers:
            self.combo_ai_provider.setCurrentText(self.ai_settings.provider)
        self.combo_ai_provider.currentTextChanged.connect(self._provider_changed)
        provider_row.addWidget(self.combo_ai_provider)

        provider_row.addWidget(QLabel("Modelo:"))
        self.combo_ai_model = QComboBox(); self.combo_ai_model.setObjectName("combo_box")
        if self.ai_settings.model:
            self.combo_ai_model.addItem(self.ai_settings.model)
        provider_row.addWidget(self.combo_ai_model, 1)
        layout.addLayout(provider_row)

        key_row = QHBoxLayout()
        key_row.addWidget(QLabel("Chave API:"))
        self.input_ai_key = QLineEdit(); self.input_ai_key.setEchoMode(QLineEdit.Password)
        self.input_ai_key.setPlaceholderText("Deixe vazio para usar a chave já salva no cofre do sistema")
        self.input_ai_key.setObjectName("input_pesquisa")
        key_row.addWidget(self.input_ai_key, 1)
        layout.addLayout(key_row)

        url_row = QHBoxLayout()
        url_row.addWidget(QLabel("Endpoint personalizado:"))
        self.input_ai_base_url = QLineEdit(self.ai_settings.base_url)
        self.input_ai_base_url.setPlaceholderText("Somente para endpoint OpenAI-compatible personalizado")
        self.input_ai_base_url.setObjectName("input_pesquisa")
        url_row.addWidget(self.input_ai_base_url, 1)
        layout.addLayout(url_row)

        options = QHBoxLayout()
        self.check_remember_key = QCheckBox("Guardar chave com segurança no cofre do sistema operacional")
        self.check_remember_key.setChecked(self.ai_settings.remember_api_key)
        options.addWidget(self.check_remember_key)
        options.addStretch()
        layout.addLayout(options)

        actions = QHBoxLayout()
        self.btn_discover_models = QPushButton("🔎 Testar conexão e carregar modelos")
        self.btn_discover_models.setObjectName("btn_destaque")
        self.btn_discover_models.clicked.connect(self.descobrir_modelos)
        actions.addWidget(self.btn_discover_models)
        self.btn_save_ai = QPushButton("💾 Salvar configuração")
        self.btn_save_ai.setObjectName("btn_primario")
        self.btn_save_ai.clicked.connect(self.salvar_config_ai)
        actions.addWidget(self.btn_save_ai)
        layout.addLayout(actions)

        self.ai_status_box = QTextEdit(); self.ai_status_box.setReadOnly(True); self.ai_status_box.setMaximumHeight(150)
        self.ai_status_box.setObjectName("console_limpo")
        layout.addWidget(self.ai_status_box)
        layout.addStretch()
        self._provider_changed(self.combo_ai_provider.currentText())
        return page

    def _provider_changed(self, provider: str):
        is_ollama = provider == "ollama"
        self.input_ai_key.setEnabled(not is_ollama)
        self.check_remember_key.setEnabled(not is_ollama)
        self.input_ai_base_url.setEnabled(provider in {"openai_compatible", "ollama"})
        if is_ollama and not self.input_ai_base_url.text().strip():
            self.input_ai_base_url.setText("http://localhost:11434")

    def _settings_from_form(self) -> AISettings:
        return AISettings(
            provider=self.combo_ai_provider.currentText().strip(),
            model=self.combo_ai_model.currentText().strip(),
            base_url=self.input_ai_base_url.text().strip(),
            remember_api_key=self.check_remember_key.isChecked(),
        )

    def descobrir_modelos(self):
        settings = self._settings_from_form()
        api_key = self.input_ai_key.text().strip() or None
        self.btn_discover_models.setEnabled(False)
        self.ai_status_box.setText("Testando conexão com o provedor...")
        self.model_worker = ModelDiscoveryWorker(self.ai_runtime, settings, api_key)
        self.model_worker.success.connect(self._modelos_carregados)
        self.model_worker.error.connect(self._modelos_erro)
        self.model_worker.start()

    def _modelos_carregados(self, models: list):
        self.btn_discover_models.setEnabled(True)
        previous = self.combo_ai_model.currentText()
        self.combo_ai_model.clear(); self.combo_ai_model.addItems(models)
        if previous in models:
            self.combo_ai_model.setCurrentText(previous)
        self.ai_status_box.setText(f"✅ Conexão válida. {len(models)} modelo(s) disponíveis.")

    def _modelos_erro(self, error: str):
        self.btn_discover_models.setEnabled(True)
        self.ai_status_box.setText(f"❌ {error}")

    def salvar_config_ai(self):
        settings = self._settings_from_form()
        if not settings.model:
            QMessageBox.warning(self, "Configuração incompleta", "Carregue e selecione um modelo antes de salvar.")
            return
        try:
            self.ai_runtime.save_settings(settings, self.input_ai_key.text().strip() or None)
            self.ai_settings = settings
            self.lbl_status_api.setText(self._status_ai_text())
            self.input_ai_key.clear()
            self.ai_status_box.setText("✅ Configuração salva. A chave não é gravada no JSON de preferências.")
        except Exception as exc:
            QMessageBox.critical(self, "Erro ao salvar", str(exc))

    def iniciar_busca_trends(self):
        query = self.input_nicho.text().strip()
        if not query:
            QMessageBox.warning(self, "Pesquisa", "Informe uma consulta ou assunto para validar.")
            return
        if not os.path.exists(ARQUIVO_TOKEN):
            QMessageBox.warning(self, "YouTube", "Conecte seu canal no Painel de Controle antes da pesquisa.")
            return
        self.btn_buscar_trends.setEnabled(False)
        self.console_trends.setText("Iniciando pesquisa baseada em evidências...")
        self.research_worker = ResearchWorker(ARQUIVO_TOKEN, query)
        self.research_worker.progress.connect(self.console_trends.append)
        self.research_worker.success.connect(self._research_success)
        self.research_worker.error.connect(self._research_error)
        self.research_worker.start()

    def _research_success(self, text: str):
        self.btn_buscar_trends.setEnabled(True)
        self.console_trends.setText(text)

    def _research_error(self, text: str):
        self.btn_buscar_trends.setEnabled(True)
        self.console_trends.append("\n" + text)

    def iniciar_agente(self):
        if not self.video_path:
            QMessageBox.warning(self, "Aviso", "Selecione um arquivo de vídeo primeiro.")
            return
        if not os.path.exists(ARQUIVO_TOKEN):
            QMessageBox.warning(self, "YouTube", "Conecte seu canal para validar oportunidades antes de gerar SEO.")
            return
        settings = self.ai_runtime.load_settings()
        if not settings.model:
            QMessageBox.warning(self, "IA", "Configure um provedor e modelo na aba Configurações & APIs.")
            return
        self.btn_iniciar.setEnabled(False); self.log_console.clear()
        self.elite_worker = EliteSEOAgentWorker(
            self.video_path, self.combo_formato.currentText(), ARQUIVO_TOKEN, self.ai_runtime
        )
        self.elite_worker.progress.connect(self.log_console.append)
        self.elite_worker.success.connect(self.exibir_dialogo_aprovacao)
        self.elite_worker.error.connect(self.processo_erro)
        self.elite_worker.start()


def run():
    import sys
    app = QApplication(sys.argv)
    window = JanelaElite(); window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
