from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QTextEdit,
    QVBoxLayout, QWidget,
)

from app_gui import ARQUIVO_TOKEN, BASE_DIR, JanelaPrincipal
from ai.runtime import AIRuntime
from ai.settings import AISettings
from elite_workers import EliteSEOAgentWorker, ModelDiscoveryWorker, StrategyResearchWorker
from ui_theme import THEMES, UISettings, UISettingsStore, build_stylesheet

AI_SETTINGS_FILE = os.path.join(BASE_DIR, "config", "ai_settings.json")
UI_SETTINGS_FILE = os.path.join(BASE_DIR, "config", "ui_settings.json")


class JanelaElite(JanelaPrincipal):
    def __init__(self):
        self.ai_runtime = AIRuntime(AI_SETTINGS_FILE)
        self.ai_settings = self.ai_runtime.load_settings()
        self.ui_store = UISettingsStore(UI_SETTINGS_FILE)
        self.ui_settings = self.ui_store.load()
        self.current_strategy_report = None
        super().__init__()
        self.setWindowTitle("YouTube Creator Agent Elite")
        self.setMinimumSize(1280, 800)
        self.lbl_status_api.setText(self._status_ai_text())
        self._rename_brand()
        self._apply_theme()

    def _rename_brand(self):
        for label in self.sidebar.findChildren(QLabel):
            text = label.text()
            if "META DIRECTOR" in text:
                label.setText("YOUTUBE CREATOR\nAGENT ELITE")
            if text.startswith("v3.1"):
                label.setText("v4.0 Elite Strategy\n© 2026 Creator Intelligence")

    def _apply_theme(self):
        self.setStyleSheet(build_stylesheet(self.ui_settings.theme))

    def _status_ai_text(self) -> str:
        model = self.ai_settings.model or "modelo não selecionado"
        return f"🧠 IA: {self.ai_settings.provider.upper()} · {model}"

    @staticmethod
    def _metric_card(title: str, value: str = "—"):
        card = QFrame(); card.setObjectName("metric_card")
        layout = QVBoxLayout(card); layout.setContentsMargins(16, 13, 16, 13)
        value_label = QLabel(value); value_label.setObjectName("metric_value")
        title_label = QLabel(title); title_label.setObjectName("metric_label")
        layout.addWidget(value_label); layout.addWidget(title_label)
        return card, value_label

    def criar_pagina_trends(self):
        page = QWidget()
        layout = QVBoxLayout(page); layout.setContentsMargins(36, 30, 36, 30); layout.setSpacing(14)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Radar de Oportunidades"); title.setObjectName("titulo_pagina")
        subtitle = QLabel("Transforme um assunto amplo em palavras-chave validadas por dados recentes do YouTube.")
        subtitle.setWordWrap(True)
        title_box.addWidget(title); title_box.addWidget(subtitle)
        header.addLayout(title_box, 1)
        self.lbl_research_status = QLabel("PRONTO")
        self.lbl_research_status.setObjectName("section_title")
        header.addWidget(self.lbl_research_status, 0, Qt.AlignRight | Qt.AlignVCenter)
        layout.addLayout(header)

        search_row = QHBoxLayout()
        self.input_nicho = QLineEdit(); self.input_nicho.setObjectName("input_pesquisa")
        self.input_nicho.setPlaceholderText("Ex: vida na roça, criação de galinhas, reforma de sítio...")
        self.input_nicho.returnPressed.connect(self.iniciar_busca_trends)
        self.btn_buscar_trends = QPushButton("⚡ MAPEAR OPORTUNIDADES")
        self.btn_buscar_trends.setObjectName("btn_destaque")
        self.btn_buscar_trends.clicked.connect(self.iniciar_busca_trends)
        search_row.addWidget(self.input_nicho, 1); search_row.addWidget(self.btn_buscar_trends)
        layout.addLayout(search_row)

        cards = QHBoxLayout(); cards.setSpacing(12)
        card, self.metric_best_score = self._metric_card("Melhor oportunidade"); cards.addWidget(card)
        card, self.metric_best_demand = self._metric_card("Demanda diária (índice)"); cards.addWidget(card)
        card, self.metric_best_comp = self._metric_card("Concorrência"); cards.addWidget(card)
        card, self.metric_freshness = self._metric_card("Resultados ≤30 dias"); cards.addWidget(card)
        layout.addLayout(cards)

        content = QHBoxLayout(); content.setSpacing(14)
        left = QVBoxLayout()
        ranking_title = QLabel("Ranking validado"); ranking_title.setObjectName("section_title")
        left.addWidget(ranking_title)
        self.strategy_table = QTableWidget(0, 7)
        self.strategy_table.setHorizontalHeaderLabels([
            "Keyword", "Score", "Demanda", "Concorrência", "≤7d", "≤30d", "Views/dia"
        ])
        self.strategy_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.strategy_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.strategy_table.verticalHeader().setVisible(False)
        self.strategy_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for col in range(1, 7):
            self.strategy_table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.strategy_table.itemSelectionChanged.connect(self._show_selected_opportunity)
        left.addWidget(self.strategy_table, 1)
        content.addLayout(left, 3)

        right = QVBoxLayout()
        detail_title = QLabel("Estratégia da oportunidade"); detail_title.setObjectName("section_title")
        right.addWidget(detail_title)
        self.strategy_details = QTextEdit(); self.strategy_details.setReadOnly(True)
        self.strategy_details.setPlaceholderText("Selecione uma oportunidade no ranking para ver títulos, métricas e evidências.")
        right.addWidget(self.strategy_details, 1)
        content.addLayout(right, 2)
        layout.addLayout(content, 1)

        footer = QLabel(
            "Métrica honesta: a API pública do YouTube não revela contagem exata de pesquisas diárias. "
            "O índice de demanda combina velocidade, atualidade, correspondência e capacidade de canais menores romperem o ranking."
        )
        footer.setWordWrap(True)
        footer.setObjectName("metric_label")
        layout.addWidget(footer)
        return page

    def criar_pagina_config(self):
        page = QWidget()
        layout = QVBoxLayout(page); layout.setContentsMargins(40, 30, 40, 30); layout.setSpacing(14)
        title = QLabel("Central de Configurações Elite"); title.setObjectName("titulo_pagina")
        layout.addWidget(title)

        ai_section = QLabel("Inteligência artificial"); ai_section.setObjectName("section_title")
        layout.addWidget(ai_section)
        provider_row = QHBoxLayout()
        provider_row.addWidget(QLabel("Provedor:"))
        self.combo_ai_provider = QComboBox(); self.combo_ai_provider.setObjectName("combo_box")
        providers = list(self.ai_runtime.registry.available_providers()); self.combo_ai_provider.addItems(providers)
        if self.ai_settings.provider in providers:
            self.combo_ai_provider.setCurrentText(self.ai_settings.provider)
        self.combo_ai_provider.currentTextChanged.connect(self._provider_changed)
        provider_row.addWidget(self.combo_ai_provider)
        provider_row.addWidget(QLabel("Modelo:"))
        self.combo_ai_model = QComboBox(); self.combo_ai_model.setObjectName("combo_box")
        if self.ai_settings.model: self.combo_ai_model.addItem(self.ai_settings.model)
        provider_row.addWidget(self.combo_ai_model, 1)
        layout.addLayout(provider_row)

        key_row = QHBoxLayout(); key_row.addWidget(QLabel("Chave API:"))
        self.input_ai_key = QLineEdit(); self.input_ai_key.setEchoMode(QLineEdit.Password)
        self.input_ai_key.setPlaceholderText("Deixe vazio para usar a credencial já salva")
        key_row.addWidget(self.input_ai_key, 1); layout.addLayout(key_row)

        url_row = QHBoxLayout(); url_row.addWidget(QLabel("Endpoint:"))
        self.input_ai_base_url = QLineEdit(self.ai_settings.base_url)
        self.input_ai_base_url.setPlaceholderText("Somente Ollama ou endpoint OpenAI-compatible")
        url_row.addWidget(self.input_ai_base_url, 1); layout.addLayout(url_row)

        self.check_remember_key = QCheckBox("Guardar chave no cofre seguro do sistema operacional")
        self.check_remember_key.setChecked(self.ai_settings.remember_api_key); layout.addWidget(self.check_remember_key)

        actions = QHBoxLayout()
        self.btn_discover_models = QPushButton("🔎 Testar conexão e carregar modelos"); self.btn_discover_models.setObjectName("btn_destaque")
        self.btn_discover_models.clicked.connect(self.descobrir_modelos); actions.addWidget(self.btn_discover_models)
        self.btn_save_ai = QPushButton("💾 Salvar IA"); self.btn_save_ai.setObjectName("btn_success")
        self.btn_save_ai.clicked.connect(self.salvar_config_ai); actions.addWidget(self.btn_save_ai)
        layout.addLayout(actions)

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

        self.ai_status_box = QTextEdit(); self.ai_status_box.setReadOnly(True); self.ai_status_box.setMaximumHeight(125)
        layout.addWidget(self.ai_status_box)
        layout.addStretch()
        self._provider_changed(self.combo_ai_provider.currentText())
        return page

    def _preview_theme(self, theme: str):
        self.setStyleSheet(build_stylesheet(theme))

    def salvar_aparencia(self):
        self.ui_settings = UISettings(
            theme=self.combo_theme.currentText(),
            compact_mode=False,
            animations=self.check_animations.isChecked(),
        )
        self.ui_store.save(self.ui_settings)
        self._apply_theme()
        self.ai_status_box.setText(f"✨ Aparência salva: {self.ui_settings.theme}")

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
        settings = self._settings_from_form(); api_key = self.input_ai_key.text().strip() or None
        self.btn_discover_models.setEnabled(False); self.ai_status_box.setText("Testando conexão com o provedor...")
        self.model_worker = ModelDiscoveryWorker(self.ai_runtime, settings, api_key)
        self.model_worker.success.connect(self._modelos_carregados); self.model_worker.error.connect(self._modelos_erro)
        self.model_worker.start()

    def _modelos_carregados(self, models: list):
        self.btn_discover_models.setEnabled(True); previous = self.combo_ai_model.currentText()
        self.combo_ai_model.clear(); self.combo_ai_model.addItems(models)
        if previous in models: self.combo_ai_model.setCurrentText(previous)
        self.ai_status_box.setText(f"✅ Conexão válida. {len(models)} modelo(s) disponíveis.")

    def _modelos_erro(self, error: str):
        self.btn_discover_models.setEnabled(True); self.ai_status_box.setText(f"❌ {error}")

    def salvar_config_ai(self):
        settings = self._settings_from_form()
        if not settings.model:
            QMessageBox.warning(self, "Configuração incompleta", "Carregue e selecione um modelo antes de salvar."); return
        try:
            self.ai_runtime.save_settings(settings, self.input_ai_key.text().strip() or None)
            self.ai_settings = settings; self.lbl_status_api.setText(self._status_ai_text()); self.input_ai_key.clear()
            self.ai_status_box.setText("✅ Configuração salva. A chave não é gravada no JSON de preferências.")
        except Exception as exc:
            QMessageBox.critical(self, "Erro ao salvar", str(exc))

    def iniciar_busca_trends(self):
        seed = self.input_nicho.text().strip()
        if not seed:
            QMessageBox.warning(self, "Pesquisa", "Informe um nicho, assunto ou consulta."); return
        if not os.path.exists(ARQUIVO_TOKEN):
            QMessageBox.warning(self, "YouTube", "Conecte seu canal no Painel de Controle antes da pesquisa."); return
        settings = self.ai_runtime.load_settings()
        if not settings.model:
            QMessageBox.warning(self, "IA", "Configure um provedor e modelo antes de mapear oportunidades."); return
        self.btn_buscar_trends.setEnabled(False); self.strategy_table.setRowCount(0); self.strategy_details.clear()
        self.lbl_research_status.setText("ANALISANDO...")
        self.metric_best_score.setText("—"); self.metric_best_demand.setText("—")
        self.metric_best_comp.setText("—"); self.metric_freshness.setText("—")
        self.strategy_worker = StrategyResearchWorker(ARQUIVO_TOKEN, seed, self.ai_runtime)
        self.strategy_worker.progress.connect(self.lbl_research_status.setText)
        self.strategy_worker.success.connect(self._strategy_success)
        self.strategy_worker.error.connect(self._strategy_error)
        self.strategy_worker.start()

    def _strategy_success(self, report):
        self.btn_buscar_trends.setEnabled(True); self.current_strategy_report = report
        opportunities = list(report.opportunities)
        self.strategy_table.setRowCount(len(opportunities))
        for row, item in enumerate(opportunities):
            r = item.research
            values = [
                item.keyword,
                str(r.opportunity.score),
                f"{r.estimated_daily_demand_index} · {r.demand_label}",
                r.competition_label,
                f"{r.fresh_7d_rate:.0%}",
                f"{r.fresh_30d_rate:.0%}",
                f"{r.median_views_per_day:,.0f}",
            ]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if col > 0: cell.setTextAlignment(Qt.AlignCenter)
                self.strategy_table.setItem(row, col, cell)
        if opportunities:
            best = opportunities[0].research
            self.metric_best_score.setText(f"{best.opportunity.score}/100")
            self.metric_best_demand.setText(f"{best.estimated_daily_demand_index}/100")
            self.metric_best_comp.setText(best.competition_label.upper())
            self.metric_freshness.setText(f"{best.fresh_30d_rate:.0%}")
            self.strategy_table.selectRow(0)
            self.lbl_research_status.setText(f"{len(opportunities)} OPORTUNIDADES VALIDADAS")
        else:
            self.lbl_research_status.setText("SEM OPORTUNIDADES FORTES")
            self.strategy_details.setText("Nenhuma hipótese atingiu cobertura/confiança suficiente. Isso é um resultado válido: a ferramenta não vai fabricar uma oportunidade.")

    def _strategy_error(self, error: str):
        self.btn_buscar_trends.setEnabled(True); self.lbl_research_status.setText("ERRO")
        QMessageBox.critical(self, "Falha na estratégia", error)

    def _show_selected_opportunity(self):
        if not self.current_strategy_report: return
        row = self.strategy_table.currentRow()
        opportunities = list(self.current_strategy_report.opportunities)
        if row < 0 or row >= len(opportunities): return
        item = opportunities[row]; r = item.research
        lines = [
            f"KEYWORD VALIDADA\n{item.keyword}\n",
            f"Opportunity Score: {r.opportunity.score}/100   |   Confiança: {r.opportunity.confidence}/100",
            f"Demanda diária (índice): {r.estimated_daily_demand_index}/100 ({r.demand_label})",
            f"Concorrência: {r.competition_label.upper()}   |   facilidade {r.opportunity.competition_score}/100",
            f"Atualidade: 7d {r.fresh_7d_rate:.0%} · 30d {r.fresh_30d_rate:.0%} · 90d {r.fresh_90d_rate:.0%}",
            f"Views/dia mediana: {r.median_views_per_day:,.0f}   |   P75: {r.p75_views_per_day:,.0f}",
            f"Canais menores rompendo: {r.small_channel_breakout_rate:.0%}",
            f"Consulta no título: {r.exact_title_match_rate:.0%}",
            "\nTÍTULOS SUGERIDOS",
        ]
        lines.extend(f"{i}. {title}" for i, title in enumerate(item.title_ideas, 1))
        lines.append("\nEVIDÊNCIAS REAIS")
        for evidence in r.evidence[:6]:
            lines.append(f"• {evidence.title}\n  {evidence.views:,.0f} views · {evidence.views_per_day:,.0f}/dia · {evidence.subscribers:,.0f} inscritos")
        lines.append("\nObservação: demanda diária é índice comparativo, não número exato de pesquisas.")
        self.strategy_details.setText("\n".join(lines))

    def iniciar_agente(self):
        if not self.video_path:
            QMessageBox.warning(self, "Aviso", "Selecione um arquivo de vídeo primeiro."); return
        if not os.path.exists(ARQUIVO_TOKEN):
            QMessageBox.warning(self, "YouTube", "Conecte seu canal para validar oportunidades antes de gerar SEO."); return
        settings = self.ai_runtime.load_settings()
        if not settings.model:
            QMessageBox.warning(self, "IA", "Configure um provedor e modelo na aba Configurações & APIs."); return
        self.btn_iniciar.setEnabled(False); self.log_console.clear()
        self.elite_worker = EliteSEOAgentWorker(self.video_path, self.combo_formato.currentText(), ARQUIVO_TOKEN, self.ai_runtime)
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
