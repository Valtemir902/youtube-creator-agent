from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from channel_command_worker import ChannelCommandCenterWorker
from motor_threads import AplicarCirurgiaWorker, DialogoAuditoria


class ChannelCommandCenterMixin:
    """Premium channel-audit UI mixed into JanelaElite."""

    @staticmethod
    def _cc_card(title: str, value: str = "—"):
        frame = QFrame(); frame.setObjectName("metric_card")
        box = QVBoxLayout(frame); box.setContentsMargins(15, 12, 15, 12)
        value_label = QLabel(value); value_label.setObjectName("metric_value")
        label = QLabel(title); label.setObjectName("metric_label")
        box.addWidget(value_label); box.addWidget(label)
        return frame, value_label

    @staticmethod
    def _prepare_table(columns: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for col in range(1, len(columns)):
            table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeToContents)
        return table

    def criar_pagina_auditoria(self):
        page = QWidget()
        root = QVBoxLayout(page); root.setContentsMargins(34, 28, 34, 28); root.setSpacing(13)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Channel Intelligence Command Center"); title.setObjectName("titulo_pagina")
        subtitle = QLabel(
            "Analytics real + termos de busca + formato + mercado atual para transformar diagnóstico em plano de ação."
        )
        subtitle.setWordWrap(True)
        title_box.addWidget(title); title_box.addWidget(subtitle)
        header.addLayout(title_box, 1)
        self.lbl_cc_status = QLabel("PRONTO"); self.lbl_cc_status.setObjectName("section_title")
        header.addWidget(self.lbl_cc_status, 0, Qt.AlignRight | Qt.AlignVCenter)
        root.addLayout(header)

        action_row = QHBoxLayout()
        self.btn_auditoria = QPushButton("🧠 ANALISAR CANAL E CRIAR PLANO DE 7 DIAS")
        self.btn_auditoria.setObjectName("btn_destaque")
        self.btn_auditoria.clicked.connect(self.iniciar_auditoria)
        action_row.addWidget(self.btn_auditoria, 1)
        self.btn_apply_audit = QPushButton("🛠️ REVISAR CORREÇÕES DE VÍDEOS")
        self.btn_apply_audit.setObjectName("btn_success")
        self.btn_apply_audit.setEnabled(False)
        self.btn_apply_audit.clicked.connect(self._review_audit_corrections)
        action_row.addWidget(self.btn_apply_audit)
        root.addLayout(action_row)

        cards = QHBoxLayout(); cards.setSpacing(10)
        card, self.cc_health = self._cc_card("Saúde recente"); cards.addWidget(card)
        card, self.cc_search = self._cc_card("Views via busca"); cards.addWidget(card)
        card, self.cc_format = self._cc_card("Formato dominante"); cards.addWidget(card)
        card, self.cc_opps = self._cc_card("Oportunidades validadas"); cards.addWidget(card)
        root.addLayout(cards)

        self.cc_tabs = QTabWidget(); self.cc_tabs.setObjectName("command_tabs")

        plan_page = QWidget(); plan_layout = QVBoxLayout(plan_page)
        self.cc_plan_table = self._prepare_table(["Prioridade", "Dia", "Formato", "Keyword", "Score", "Conf."])
        self.cc_plan_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.cc_plan_table.itemSelectionChanged.connect(self._show_plan_details)
        plan_layout.addWidget(self.cc_plan_table, 2)
        self.cc_plan_details = QTextEdit(); self.cc_plan_details.setReadOnly(True)
        self.cc_plan_details.setPlaceholderText("O plano editorial aparecerá aqui depois da análise.")
        plan_layout.addWidget(self.cc_plan_details, 1)
        self.cc_tabs.addTab(plan_page, "⚡ Plano de 7 dias")

        search_page = QWidget(); search_layout = QVBoxLayout(search_page)
        self.cc_search_table = self._prepare_table(["Termo real de busca", "Views", "% busca", "Min. assistidos"])
        search_layout.addWidget(self.cc_search_table)
        self.cc_tabs.addTab(search_page, "🔎 Buscas reais")

        winners_page = QWidget(); winners_layout = QHBoxLayout(winners_page)
        winners_col = QVBoxLayout(); winners_col.addWidget(QLabel("Vídeos vencedores recentes"))
        self.cc_top_table = self._prepare_table(["Título", "Formato", "Views 28d", "Velocidade", "Engaj."])
        winners_col.addWidget(self.cc_top_table); winners_layout.addLayout(winners_col, 1)
        weak_col = QVBoxLayout(); weak_col.addWidget(QLabel("Vídeos que pedem atenção"))
        self.cc_weak_table = self._prepare_table(["Título", "Formato", "Views 28d", "Velocidade", "Engaj."])
        weak_col.addWidget(self.cc_weak_table); winners_layout.addLayout(weak_col, 1)
        self.cc_tabs.addTab(winners_page, "📈 Vencedores × atenção")

        opp_page = QWidget(); opp_layout = QVBoxLayout(opp_page)
        self.cc_opp_table = self._prepare_table(["Keyword", "Score", "Fit canal", "Demanda", "Concorrência", "≤30d", "Formato"])
        self.cc_opp_table.itemSelectionChanged.connect(self._show_opportunity_details)
        opp_layout.addWidget(self.cc_opp_table, 2)
        self.cc_opp_details = QTextEdit(); self.cc_opp_details.setReadOnly(True)
        opp_layout.addWidget(self.cc_opp_details, 1)
        self.cc_tabs.addTab(opp_page, "🎯 Oportunidades")

        diagnosis_page = QWidget(); diagnosis_layout = QVBoxLayout(diagnosis_page)
        self.log_auditoria = QTextEdit(); self.log_auditoria.setReadOnly(True)
        self.log_auditoria.setPlaceholderText("Diagnóstico baseado em evidências aparecerá aqui.")
        diagnosis_layout.addWidget(self.log_auditoria)
        self.cc_tabs.addTab(diagnosis_page, "🩺 Diagnóstico")

        root.addWidget(self.cc_tabs, 1)
        self.current_command_report = None
        return page

    def iniciar_auditoria(self):
        from app_gui import ARQUIVO_TOKEN

        if not os.path.exists(ARQUIVO_TOKEN):
            QMessageBox.warning(self, "YouTube", "Conecte seu canal antes de iniciar o Command Center.")
            return
        settings = self.ai_runtime.load_settings()
        if not settings.model:
            QMessageBox.warning(self, "IA", "Configure um provedor e modelo antes de analisar o canal.")
            return

        self.btn_auditoria.setEnabled(False); self.btn_apply_audit.setEnabled(False)
        self.lbl_cc_status.setText("COLETANDO ANALYTICS...")
        self.log_auditoria.clear(); self.cc_plan_table.setRowCount(0); self.cc_search_table.setRowCount(0)
        self.cc_top_table.setRowCount(0); self.cc_weak_table.setRowCount(0); self.cc_opp_table.setRowCount(0)
        self.cc_health.setText("—"); self.cc_search.setText("—"); self.cc_format.setText("—"); self.cc_opps.setText("—")

        self.cc_worker = ChannelCommandCenterWorker(ARQUIVO_TOKEN, self.ai_runtime)
        self.cc_worker.progress.connect(self.lbl_cc_status.setText)
        self.cc_worker.success.connect(self._command_center_success)
        self.cc_worker.error.connect(self._command_center_error)
        self.cc_worker.start()

    @staticmethod
    def _set_row(table: QTableWidget, row: int, values: list[str]):
        table.insertRow(row)
        for col, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            if col > 0:
                item.setTextAlignment(Qt.AlignCenter)
            table.setItem(row, col, item)

    def _command_center_success(self, report):
        self.current_command_report = report
        self.btn_auditoria.setEnabled(True)
        self.lbl_cc_status.setText("ANÁLISE CONCLUÍDA")
        self.cc_health.setText(f"{report.health_score}/100")
        self.cc_search.setText(f"{report.search_share:.0%}")
        self.cc_format.setText(report.dominant_format.upper())
        self.cc_opps.setText(str(len(report.opportunities)))

        self.cc_plan_table.setRowCount(0)
        for row, action in enumerate(report.editorial_plan):
            self._set_row(self.cc_plan_table, row, [
                action.priority, action.day_slot, action.format, action.keyword,
                action.opportunity_score, action.confidence,
            ])
        if report.editorial_plan:
            self.cc_plan_table.selectRow(0)

        self.cc_search_table.setRowCount(0)
        for row, item in enumerate(report.top_search_terms):
            self._set_row(self.cc_search_table, row, [
                item.get("term", ""), f"{item.get('views', 0):,}",
                f"{float(item.get('share_of_search_views', 0)):.1%}",
                f"{float(item.get('estimated_minutes_watched', 0)):,.0f}",
            ])

        self.cc_top_table.setRowCount(0)
        for row, item in enumerate(report.top_videos):
            self._set_row(self.cc_top_table, row, [
                item.get("title", ""), item.get("format", ""), f"{item.get('views_28d', 0):,}",
                f"{float(item.get('velocity_28d', 0)):,.1f}/dia", f"{float(item.get('engagement_rate_28d', 0)):.1%}",
            ])

        self.cc_weak_table.setRowCount(0)
        for row, item in enumerate(report.weak_videos):
            self._set_row(self.cc_weak_table, row, [
                item.get("title", ""), item.get("format", ""), f"{item.get('views_28d', 0):,}",
                f"{float(item.get('velocity_28d', 0)):,.1f}/dia", f"{float(item.get('engagement_rate_28d', 0)):.1%}",
            ])

        self.cc_opp_table.setRowCount(0)
        for row, item in enumerate(report.opportunities):
            self._set_row(self.cc_opp_table, row, [
                item.keyword, item.score, f"{item.channel_fit}/100", item.demand_index,
                item.competition_label.upper(), f"{item.fresh_30d_rate:.0%}", item.recommended_format,
            ])
        if report.opportunities:
            self.cc_opp_table.selectRow(0)

        audit = report.audit or {}
        diagnosis = [
            f"CANAL: {report.channel_title}",
            f"Saúde recente: {report.health_score}/100 ({report.health_label})",
            f"Formato dominante: {report.dominant_format}",
            f"Participação recente: Shorts {report.shorts_share:.1%} | Longos {report.long_share:.1%}",
            f"Tráfego via pesquisa: {report.search_share:.1%}",
            "",
            "DIAGNÓSTICO DA IA BASEADO EM EVIDÊNCIAS",
            str(audit.get("diagnostico_geral", "Sem diagnóstico adicional.")),
        ]
        if report.topic_terms:
            diagnosis.extend(["", "TEMAS QUE O CANAL JÁ SINALIZA", ", ".join(report.topic_terms[:15])])
        if report.warnings:
            diagnosis.extend(["", "ALERTAS"] + [f"• {warning}" for warning in report.warnings])
        self.log_auditoria.setText("\n".join(diagnosis))

        videos = list(audit.get("videos_para_otimizar", []))
        self.btn_apply_audit.setEnabled(bool(videos))

    def _command_center_error(self, error: str):
        self.btn_auditoria.setEnabled(True); self.btn_apply_audit.setEnabled(False)
        self.lbl_cc_status.setText("ERRO")
        QMessageBox.critical(self, "Command Center", error)

    def _show_plan_details(self):
        if not self.current_command_report:
            return
        row = self.cc_plan_table.currentRow()
        plan = list(self.current_command_report.editorial_plan)
        if row < 0 or row >= len(plan):
            return
        item = plan[row]
        self.cc_plan_details.setText("\n".join([
            f"PRIORIDADE {item.priority} · {item.day_slot}",
            f"Formato: {item.format}",
            f"Keyword validada: {item.keyword}",
            f"Score personalizado: {item.opportunity_score}/100 · Confiança {item.confidence}/100",
            "",
            f"TÍTULO DE TRABALHO\n{item.working_title}",
            "",
            f"OBJETIVO\n{item.objective}",
            "",
            f"POR QUE ENTRA NO PLANO\n{item.evidence_reason}",
        ]))

    def _show_opportunity_details(self):
        if not self.current_command_report:
            return
        row = self.cc_opp_table.currentRow()
        items = list(self.current_command_report.opportunities)
        if row < 0 or row >= len(items):
            return
        item = items[row]
        lines = [
            f"KEYWORD: {item.keyword}",
            f"Score personalizado: {item.score}/100 | Confiança: {item.confidence}/100",
            f"Fit com o canal: {item.channel_fit}/100",
            f"Demanda observável: {item.demand_index}/100",
            f"Concorrência: {item.competition_label.upper()}",
            f"Resultados recentes ≤30d: {item.fresh_30d_rate:.0%}",
            f"Mediana observada: {item.views_per_day:,.0f} views/dia",
            f"Formato recomendado: {item.recommended_format}",
            "",
            "EVIDÊNCIAS DE MERCADO",
        ]
        lines.extend(f"• {title}" for title in item.evidence_titles)
        self.cc_opp_details.setText("\n".join(lines))

    def _review_audit_corrections(self):
        from app_gui import ARQUIVO_TOKEN

        if not self.current_command_report:
            return
        audit = self.current_command_report.audit or {}
        videos = list(audit.get("videos_para_otimizar", []))
        if not videos:
            QMessageBox.information(self, "Auditoria", "Nenhuma alteração de metadata atingiu evidência suficiente.")
            return
        if DialogoAuditoria(audit, self).exec():
            confirm = QMessageBox.question(
                self,
                "Confirmar alterações",
                f"Aplicar as alterações revisadas em {len(videos)} vídeo(s) do canal?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if confirm != QMessageBox.Yes:
                return
            self.btn_apply_audit.setEnabled(False)
            self.cirurgia_worker = AplicarCirurgiaWorker(videos, ARQUIVO_TOKEN)
            self.cirurgia_worker.progresso_sinal.connect(self.log_auditoria.append)
            self.cirurgia_worker.concluido_sinal.connect(self._audit_apply_done)
            self.cirurgia_worker.erro_sinal.connect(self._audit_apply_error)
            self.cirurgia_worker.start()

    def _audit_apply_done(self, message: str):
        self.log_auditoria.append(f"\n{message}")
        self.btn_apply_audit.setEnabled(False)

    def _audit_apply_error(self, error: str):
        self.log_auditoria.append(f"\n{error}")
        self.btn_apply_audit.setEnabled(True)
