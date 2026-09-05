from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QHeaderView, QLabel, QTextEdit, QVBoxLayout, QWidget

from intelligence.continuous_strategy import ContinuousStrategyEngine


class ContinuousStrategyMixin:
    """Adds momentum and post-action learning to the v5 Command Center UI."""

    def criar_pagina_auditoria(self):
        page = super().criar_pagina_auditoria()

        history_page = QWidget()
        root = QVBoxLayout(history_page)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        summary = QHBoxLayout()
        card, self.cs_health_delta = self._cc_card("Δ saúde vs execução anterior")
        summary.addWidget(card)
        card, self.cs_best_day = self._cc_card("Melhor dia observado")
        summary.addWidget(card)
        card, self.cs_day_confidence = self._cc_card("Confiança do dia")
        summary.addWidget(card)
        card, self.cs_tracked = self._cc_card("Keywords com histórico")
        summary.addWidget(card)
        root.addLayout(summary)

        root.addWidget(QLabel("Momentum das oportunidades"))
        self.cs_momentum_table = self._prepare_table([
            "Keyword", "Atual", "Anterior", "Δ", "Status", "Amostras"
        ])
        self.cs_momentum_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        root.addWidget(self.cs_momentum_table, 2)

        bottom = QHBoxLayout()
        observations_col = QVBoxLayout()
        observations_col.addWidget(QLabel("Acompanhamento pós-ação"))
        self.cs_outcome_table = self._prepare_table([
            "Alvo", "Status", "Δ velocidade", "Δ engajamento"
        ])
        observations_col.addWidget(self.cs_outcome_table)
        bottom.addLayout(observations_col, 3)

        notes_col = QVBoxLayout()
        notes_col.addWidget(QLabel("Leitura estratégica"))
        self.cs_notes = QTextEdit()
        self.cs_notes.setReadOnly(True)
        self.cs_notes.setPlaceholderText(
            "Depois de duas ou mais análises, o sistema passa a mostrar aceleração, queda e mudanças observadas."
        )
        notes_col.addWidget(self.cs_notes)
        bottom.addLayout(notes_col, 2)
        root.addLayout(bottom, 2)

        self.cc_tabs.addTab(history_page, "🧭 Momentum & aprendizado")
        return page

    @staticmethod
    def _format_delta(value: int | float | None, suffix: str = "") -> str:
        if value is None:
            return "—"
        prefix = "+" if value > 0 else ""
        return f"{prefix}{value}{suffix}"

    def _command_center_success(self, report):
        super()._command_center_success(report)

        previous = getattr(report, "previous_run", None)
        health_delta = None
        if previous:
            health_delta = int(report.health_score) - int(previous.get("health_score", report.health_score))
        self.cs_health_delta.setText(self._format_delta(health_delta))

        timing = getattr(report, "timing", None)
        if timing:
            self.cs_best_day.setText(str(timing.best_day).upper())
            self.cs_day_confidence.setText(f"{timing.confidence}/100")
        else:
            self.cs_best_day.setText("—")
            self.cs_day_confidence.setText("—")

        momentum = list(getattr(report, "momentum", ()))
        self.cs_momentum_table.setRowCount(0)
        tracked = 0
        for row, item in enumerate(momentum):
            if item.samples > 1:
                tracked += 1
            self._set_row(self.cs_momentum_table, row, [
                item.keyword,
                item.current_score,
                item.previous_score if item.previous_score is not None else "—",
                self._format_delta(item.delta),
                item.status,
                item.samples,
            ])
        self.cs_tracked.setText(str(tracked))

        observations = list(getattr(report, "observations", ()))
        self.cs_outcome_table.setRowCount(0)
        for row, item in enumerate(observations):
            self._set_row(self.cs_outcome_table, row, [
                item.target_id,
                item.status,
                self._format_delta(item.velocity_delta_pct, "%"),
                self._format_delta(item.engagement_delta_pct, "%"),
            ])

        notes = []
        if previous:
            previous_search = float(previous.get("search_share", 0.0) or 0.0)
            search_delta = (float(report.search_share) - previous_search) * 100.0
            notes.append(
                f"Busca: {report.search_share:.1%} das views recentes, variação de {self._format_delta(round(search_delta, 1), ' p.p.')} vs execução anterior."
            )
            if previous.get("dominant_format") != report.dominant_format:
                notes.append(
                    f"O formato dominante mudou de {previous.get('dominant_format')} para {report.dominant_format}."
                )
        else:
            notes.append("Primeiro snapshot estratégico salvo. O momentum fica mais útil a partir da próxima execução.")

        if timing:
            notes.append(f"Melhor dia observado: {timing.best_day}, confiança {timing.confidence}/100, amostra {timing.sample_size} vídeo(s).")
            notes.append(timing.note)

        rising = [item.keyword for item in momentum if item.status in {"ACELERANDO", "SUBINDO"}]
        falling = [item.keyword for item in momentum if item.status in {"PERDENDO FORÇA", "CAINDO"}]
        if rising:
            notes.append("Acelerando/subindo: " + ", ".join(rising[:5]))
        if falling:
            notes.append("Perdendo força/caindo: " + ", ".join(falling[:5]))

        if observations:
            notes.append(
                "As mudanças pós-ação são observações, não prova de causalidade. O sistema evita atribuir toda melhora ou queda a uma alteração de metadata."
            )
        else:
            notes.append("Ainda não há ações antigas o bastante para avaliação pós-mudança.")

        self.cs_notes.setText("\n\n".join(notes))

    def _audit_apply_done(self, message: str):
        super()._audit_apply_done(message)
        if not getattr(self, "current_command_report", None):
            return
        try:
            from app_gui import ARQUIVO_TOKEN

            engine = ContinuousStrategyEngine(ARQUIVO_TOKEN, self.ai_runtime)
            action_ids = engine.record_metadata_actions(self.current_command_report)
            if action_ids:
                self.log_auditoria.append(
                    f"\n🧭 {len(action_ids)} alteração(ões) registrada(s) para acompanhamento nas próximas análises."
                )
        except Exception as exc:
            self.log_auditoria.append(f"\n⚠️ Não foi possível registrar o acompanhamento histórico: {exc}")
