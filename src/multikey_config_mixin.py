from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QTextEdit,
    QVBoxLayout, QWidget,
)

from ai.settings import AISettings
from ai_key_workers import APIKeyTestWorker
from elite_workers import ModelDiscoveryWorker
from ui_theme import THEMES, UISettings


class MultiKeyConfigMixin:
    """v7 desktop configuration surface for provider key pools."""

    def criar_pagina_config(self):
        page = QWidget()
        layout = QVBoxLayout(page); layout.setContentsMargins(40, 26, 40, 26); layout.setSpacing(12)
        title = QLabel("Central de Configurações Elite"); title.setObjectName("titulo_pagina")
        layout.addWidget(title)

        ai_section = QLabel("Inteligência artificial · Cofre Multi-Chave"); ai_section.setObjectName("section_title")
        layout.addWidget(ai_section)

        provider_row = QHBoxLayout()
        provider_row.addWidget(QLabel("Provedor:"))
        self.combo_ai_provider = QComboBox(); self.combo_ai_provider.setObjectName("combo_box")
        providers = list(self.ai_runtime.registry.available_providers()); self.combo_ai_provider.addItems(providers)
        if self.ai_settings.provider in providers:
            self.combo_ai_provider.setCurrentText(self.ai_settings.provider)
        provider_row.addWidget(self.combo_ai_provider)
        provider_row.addWidget(QLabel("Modelo:"))
        self.combo_ai_model = QComboBox(); self.combo_ai_model.setObjectName("combo_box")
        if self.ai_settings.model:
            self.combo_ai_model.addItem(self.ai_settings.model)
        provider_row.addWidget(self.combo_ai_model, 1)
        layout.addLayout(provider_row)

        url_row = QHBoxLayout(); url_row.addWidget(QLabel("Endpoint:"))
        self.input_ai_base_url = QLineEdit(self.ai_settings.base_url)
        self.input_ai_base_url.setPlaceholderText("Somente Ollama ou endpoint OpenAI-compatible")
        url_row.addWidget(self.input_ai_base_url, 1); layout.addLayout(url_row)

        add_row = QHBoxLayout()
        add_row.addWidget(QLabel("Nova chave:"))
        self.input_ai_key = QLineEdit(); self.input_ai_key.setEchoMode(QLineEdit.Password)
        self.input_ai_key.setPlaceholderText("Cole uma nova chave; ela não será gravada no JSON")
        add_row.addWidget(self.input_ai_key, 3)
        self.input_ai_key_label = QLineEdit(); self.input_ai_key_label.setPlaceholderText("Apelido opcional")
        add_row.addWidget(self.input_ai_key_label, 1)
        self.btn_add_ai_key = QPushButton("➕ Adicionar ao cofre"); self.btn_add_ai_key.setObjectName("btn_success")
        self.btn_add_ai_key.clicked.connect(self._add_ai_key)
        add_row.addWidget(self.btn_add_ai_key)
        layout.addLayout(add_row)

        preference_row = QHBoxLayout()
        self.check_remember_key = QCheckBox("Guardar novas chaves no cofre seguro do sistema operacional")
        self.check_remember_key.setChecked(self.ai_settings.remember_api_key)
        preference_row.addWidget(self.check_remember_key)
        self.check_auto_rotate_keys = QCheckBox("🔄 Rotação automática: se uma chave falhar, tentar a próxima")
        self.check_auto_rotate_keys.setChecked(bool(self.ai_settings.auto_rotate_keys))
        self.check_auto_rotate_keys.toggled.connect(self._rotation_toggled)
        preference_row.addWidget(self.check_auto_rotate_keys)
        preference_row.addStretch()
        layout.addLayout(preference_row)

        self.ai_key_table = QTableWidget(0, 7)
        self.ai_key_table.setHorizontalHeaderLabels([
            "Ativa", "Chave mascarada", "Apelido", "Estado", "Habilitada", "Último modelo", "Último erro"
        ])
        self.ai_key_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.ai_key_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.ai_key_table.verticalHeader().setVisible(False)
        self.ai_key_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.ai_key_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.ai_key_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        for col in (0, 3, 4, 5):
            self.ai_key_table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeToContents)
        layout.addWidget(self.ai_key_table, 1)

        key_actions = QHBoxLayout()
        self.btn_use_ai_key = QPushButton("⭐ Usar selecionada")
        self.btn_use_ai_key.clicked.connect(self._use_selected_ai_key); key_actions.addWidget(self.btn_use_ai_key)
        self.btn_test_ai_key = QPushButton("🧪 Testar selecionada + carregar modelos")
        self.btn_test_ai_key.setObjectName("btn_destaque")
        self.btn_test_ai_key.clicked.connect(self._test_selected_ai_key); key_actions.addWidget(self.btn_test_ai_key)
        self.btn_toggle_ai_key = QPushButton("⏯ Ativar / desativar")
        self.btn_toggle_ai_key.clicked.connect(self._toggle_selected_ai_key); key_actions.addWidget(self.btn_toggle_ai_key)
        self.btn_delete_ai_key = QPushButton("🗑 Excluir selecionada")
        self.btn_delete_ai_key.clicked.connect(self._delete_selected_ai_key); key_actions.addWidget(self.btn_delete_ai_key)
        layout.addLayout(key_actions)

        save_actions = QHBoxLayout()
        self.btn_discover_models = QPushButton("🔎 Testar chave ativa e carregar modelos"); self.btn_discover_models.setObjectName("btn_destaque")
        self.btn_discover_models.clicked.connect(self.descobrir_modelos); save_actions.addWidget(self.btn_discover_models)
        self.btn_save_ai = QPushButton("💾 Salvar provedor / modelo"); self.btn_save_ai.setObjectName("btn_success")
        self.btn_save_ai.clicked.connect(self.salvar_config_ai); save_actions.addWidget(self.btn_save_ai)
        layout.addLayout(save_actions)

        self.ai_status_box = QTextEdit(); self.ai_status_box.setReadOnly(True); self.ai_status_box.setMaximumHeight(100)
        layout.addWidget(self.ai_status_box)

        appearance_title = QLabel("Aparência e experiência"); appearance_title.setObjectName("section_title")
        layout.addWidget(appearance_title)
        appearance_row = QHBoxLayout(); appearance_row.addWidget(QLabel("Tema:"))
        self.combo_theme = QComboBox(); self.combo_theme.addItems(list(THEMES.keys()))
        self.combo_theme.setCurrentText(self.ui_settings.theme)
        self.combo_theme.currentTextChanged.connect(self._preview_theme)
        appearance_row.addWidget(self.combo_theme)
        self.check_animations = QCheckBox("Animações e efeitos visuais")
        self.check_animations.setChecked(self.ui_settings.animations); appearance_row.addWidget(self.check_animations)
        appearance_row.addStretch()
        self.btn_save_appearance = QPushButton("✨ Salvar aparência"); self.btn_save_appearance.setObjectName("btn_primario")
        self.btn_save_appearance.clicked.connect(self.salvar_aparencia); appearance_row.addWidget(self.btn_save_appearance)
        layout.addLayout(appearance_row)

        self.combo_ai_provider.currentTextChanged.connect(self._provider_changed)
        self._provider_changed(self.combo_ai_provider.currentText())
        return page

    def _preview_theme(self, theme: str):
        from ui_theme import build_stylesheet
        self.setStyleSheet(build_stylesheet(theme))

    def salvar_aparencia(self):
        self.ui_settings = UISettings(
            theme=self.combo_theme.currentText(), compact_mode=False,
            animations=self.check_animations.isChecked(),
        )
        self.ui_store.save(self.ui_settings)
        self._apply_theme()
        self.ai_status_box.setText(f"✨ Aparência salva: {self.ui_settings.theme}")

    def _provider_changed(self, provider: str):
        provider = provider.strip().lower()
        is_ollama = provider == "ollama"
        self.input_ai_key.setEnabled(not is_ollama)
        self.input_ai_key_label.setEnabled(not is_ollama)
        self.btn_add_ai_key.setEnabled(not is_ollama)
        self.check_remember_key.setEnabled(not is_ollama)
        self.check_auto_rotate_keys.setEnabled(not is_ollama)
        self.ai_key_table.setEnabled(not is_ollama)
        for button in (self.btn_use_ai_key, self.btn_test_ai_key, self.btn_toggle_ai_key, self.btn_delete_ai_key):
            button.setEnabled(not is_ollama)
        self.input_ai_base_url.setEnabled(provider in {"openai_compatible", "ollama"})
        if is_ollama and not self.input_ai_base_url.text().strip():
            self.input_ai_base_url.setText("http://localhost:11434")
        self.check_auto_rotate_keys.blockSignals(True)
        self.check_auto_rotate_keys.setChecked(False if is_ollama else self.ai_runtime.key_pool.auto_rotate(provider))
        self.check_auto_rotate_keys.blockSignals(False)
        self._refresh_ai_key_table()

    def _settings_from_form(self) -> AISettings:
        return AISettings(
            provider=self.combo_ai_provider.currentText().strip(),
            model=self.combo_ai_model.currentText().strip(),
            base_url=self.input_ai_base_url.text().strip(),
            remember_api_key=self.check_remember_key.isChecked(),
            auto_rotate_keys=self.check_auto_rotate_keys.isChecked(),
        )

    def _refresh_ai_key_table(self):
        provider = self.combo_ai_provider.currentText().strip().lower()
        self.ai_key_table.setRowCount(0)
        if not provider or provider == "ollama":
            return
        try:
            keys = self.ai_runtime.list_api_keys(provider)
        except Exception as exc:
            self.ai_status_box.setText(f"⚠️ Não foi possível ler o cofre: {exc}")
            return
        status_icons = {"ok": "✅ OK", "warning": "⚠️ Atenção", "error": "❌ Erro", "unknown": "⚪ Não testada"}
        for row, item in enumerate(keys):
            self.ai_key_table.insertRow(row)
            values = [
                "⭐" if item.get("active") else "",
                item.get("masked", ""),
                item.get("label", ""),
                status_icons.get(item.get("status", "unknown"), item.get("status", "")),
                "SIM" if item.get("enabled", True) else "NÃO",
                item.get("last_model", "") or "—",
                item.get("last_error", "") or "—",
            ]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                if col != 6:
                    cell.setTextAlignment(Qt.AlignCenter)
                if col == 1:
                    cell.setData(Qt.UserRole, item.get("id", ""))
                if col == 6 and item.get("last_error"):
                    cell.setToolTip(item.get("last_error", ""))
                self.ai_key_table.setItem(row, col, cell)
        active_row = next((i for i, item in enumerate(keys) if item.get("active")), -1)
        if active_row >= 0:
            self.ai_key_table.selectRow(active_row)
        elif keys:
            self.ai_key_table.selectRow(0)

    def _selected_key(self) -> tuple[str, dict] | tuple[None, None]:
        row = self.ai_key_table.currentRow()
        if row < 0:
            return None, None
        cell = self.ai_key_table.item(row, 1)
        if cell is None:
            return None, None
        key_id = str(cell.data(Qt.UserRole) or "")
        provider = self.combo_ai_provider.currentText().strip().lower()
        record = next((item for item in self.ai_runtime.list_api_keys(provider) if item.get("id") == key_id), None)
        return (key_id, record) if record else (None, None)

    def _add_ai_key(self):
        provider = self.combo_ai_provider.currentText().strip().lower()
        api_key = self.input_ai_key.text().strip()
        if not api_key:
            QMessageBox.warning(self, "Chave API", "Cole uma chave antes de adicionar ao cofre.")
            return
        try:
            result = self.ai_runtime.add_api_key(
                provider,
                api_key,
                label=self.input_ai_key_label.text().strip(),
                remember=self.check_remember_key.isChecked(),
                make_active=True,
            )
            self.input_ai_key.clear(); self.input_ai_key_label.clear()
            self._refresh_ai_key_table()
            suffix = "já existia e foi selecionada" if result.get("reused") else "adicionada com segurança"
            self.ai_status_box.setText(f"✅ {result.get('masked', 'Chave')} {suffix}.")
        except Exception as exc:
            QMessageBox.critical(self, "Falha ao guardar chave", str(exc))

    def _use_selected_ai_key(self):
        key_id, record = self._selected_key()
        if not key_id:
            return
        provider = self.combo_ai_provider.currentText().strip().lower()
        self.ai_runtime.set_active_api_key(provider, key_id)
        self._refresh_ai_key_table()
        self.ai_status_box.setText(f"⭐ Chave ativa: {record.get('masked', '')}")

    def _toggle_selected_ai_key(self):
        key_id, record = self._selected_key()
        if not key_id:
            return
        provider = self.combo_ai_provider.currentText().strip().lower()
        self.ai_runtime.set_api_key_enabled(provider, key_id, not bool(record.get("enabled", True)))
        self._refresh_ai_key_table()

    def _delete_selected_ai_key(self):
        key_id, record = self._selected_key()
        if not key_id:
            return
        answer = QMessageBox.question(
            self, "Excluir chave",
            f"Excluir {record.get('masked', 'esta chave')} do cofre seguro?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        provider = self.combo_ai_provider.currentText().strip().lower()
        self.ai_runtime.delete_api_key(provider, key_id)
        self._refresh_ai_key_table()
        self.ai_status_box.setText("🗑 Chave removida do pool.")

    def _rotation_toggled(self, enabled: bool):
        provider = self.combo_ai_provider.currentText().strip().lower()
        if provider and provider != "ollama":
            self.ai_runtime.set_auto_rotation(provider, enabled)
            self.ai_status_box.setText(
                "🔄 Rotação automática ativada." if enabled else "⏸ Rotação automática desativada."
            )

    def _start_existing_key_test(self, key_id: str):
        provider = self.combo_ai_provider.currentText().strip().lower()
        self.btn_test_ai_key.setEnabled(False); self.btn_discover_models.setEnabled(False)
        self.ai_status_box.setText("🧪 Testando a chave selecionada...")
        self.key_test_worker = APIKeyTestWorker(
            self.ai_runtime, provider, key_id,
            model=self.combo_ai_model.currentText().strip(),
            base_url=self.input_ai_base_url.text().strip(),
        )
        self.key_test_worker.success.connect(self._key_test_success)
        self.key_test_worker.error.connect(self._key_test_error)
        self.key_test_worker.start()

    def _test_selected_ai_key(self):
        key_id, _record = self._selected_key()
        if not key_id:
            QMessageBox.information(self, "Chave API", "Selecione uma chave da lista.")
            return
        self._start_existing_key_test(key_id)

    def descobrir_modelos(self):
        settings = self._settings_from_form()
        raw_key = self.input_ai_key.text().strip() or None
        if raw_key:
            self.btn_discover_models.setEnabled(False); self.ai_status_box.setText("Testando a nova chave sem salvá-la...")
            self.model_worker = ModelDiscoveryWorker(self.ai_runtime, settings, raw_key)
            self.model_worker.success.connect(self._modelos_carregados)
            self.model_worker.error.connect(self._modelos_erro)
            self.model_worker.start()
            return
        if settings.provider == "ollama":
            self.btn_discover_models.setEnabled(False); self.ai_status_box.setText("Consultando Ollama local...")
            self.model_worker = ModelDiscoveryWorker(self.ai_runtime, settings, None)
            self.model_worker.success.connect(self._modelos_carregados)
            self.model_worker.error.connect(self._modelos_erro)
            self.model_worker.start()
            return
        keys = self.ai_runtime.list_api_keys(settings.provider)
        active = next((item for item in keys if item.get("active") and item.get("enabled", True)), None)
        if active is None:
            QMessageBox.warning(self, "Chave API", "Adicione ou habilite uma chave antes de testar.")
            return
        self._start_existing_key_test(active["id"])

    def _key_test_success(self, result: dict):
        self.btn_test_ai_key.setEnabled(True); self.btn_discover_models.setEnabled(True)
        models = list(result.get("models", []))
        self._populate_models(models)
        self._refresh_ai_key_table()
        self.ai_status_box.setText(f"✅ Chave válida. {len(models)} modelo(s) disponíveis.")

    def _key_test_error(self, error: str):
        self.btn_test_ai_key.setEnabled(True); self.btn_discover_models.setEnabled(True)
        self._refresh_ai_key_table()
        self.ai_status_box.setText(f"❌/⚠️ Falha na chave selecionada: {error}")

    def _populate_models(self, models: list[str]):
        previous = self.combo_ai_model.currentText()
        self.combo_ai_model.clear(); self.combo_ai_model.addItems(models)
        if previous in models:
            self.combo_ai_model.setCurrentText(previous)

    def _modelos_carregados(self, models: list):
        self.btn_discover_models.setEnabled(True)
        self._populate_models([str(item) for item in models])
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
            # If a new secret is still in the input, Save also adds it to the pool.
            raw_key = self.input_ai_key.text().strip() or None
            self.ai_runtime.save_settings(settings, raw_key)
            self.ai_settings = settings
            self.lbl_status_api.setText(self._status_ai_text())
            self.input_ai_key.clear(); self.input_ai_key_label.clear()
            self._refresh_ai_key_table()
            mode = "rotação automática" if settings.auto_rotate_keys else "chave ativa fixa"
            self.ai_status_box.setText(f"✅ Configuração salva · {mode}.")
        except Exception as exc:
            QMessageBox.critical(self, "Erro ao salvar", str(exc))
