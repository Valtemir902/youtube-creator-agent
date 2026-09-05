import sys
import os
import traceback
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPixmap, QFont, QCursor, QImage
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTextEdit, QFileDialog, QMessageBox, 
    QStackedWidget, QFrame, QComboBox, QLineEdit
)
from moviepy import VideoFileClip
from dotenv import load_dotenv

from ui_youtube import ComponenteYouTube
from motor_threads import (
    DialogoAprovacao, DialogoAuditoria, AgenteWorker, 
    PublicarWorker, AuditoriaWorker, AplicarCirurgiaWorker, TrendHunterWorker
)

# =====================================================================
# CONFIGURAÇÕES DE DIRETÓRIOS E AMBIENTE
# =====================================================================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) if not getattr(sys, 'frozen', False) else os.path.dirname(os.path.dirname(sys.executable))
PASTA_CONFIG = os.path.join(BASE_DIR, "config")
ARQUIVO_ENV = os.path.join(PASTA_CONFIG, ".env")
ARQUIVO_TOKEN = os.path.join(PASTA_CONFIG, "token.json")

load_dotenv(ARQUIVO_ENV)
GEMINI_API_KEYS_STRING = os.getenv("GEMINI_API_KEYS", "")

class JanelaPrincipal(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Meta Director Pro - YouTube Edition")
        self.setMinimumSize(1100, 750)
        
        self.video_path = ""
        self.thumb_path = ""
        self.lista_chaves = [c.strip() for c in GEMINI_API_KEYS_STRING.split(",") if c.strip()]
        QApplication.setFont(QFont("Segoe UI", 10))

        widget_central = QWidget()
        layout_mestre = QHBoxLayout(widget_central)
        layout_mestre.setContentsMargins(0, 0, 0, 0)
        layout_mestre.setSpacing(0)

        # BARRA LATERAL
        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(280)
        layout_sidebar = QVBoxLayout(self.sidebar)
        layout_sidebar.setContentsMargins(20, 40, 20, 30)

        lbl_logo = QLabel("META DIRECTOR\nPRO (YOUTUBE)")
        lbl_logo.setObjectName("logo")
        lbl_logo.setAlignment(Qt.AlignCenter)
        layout_sidebar.addWidget(lbl_logo)
        
        linha = QFrame(); linha.setFrameShape(QFrame.HLine); linha.setObjectName("linha_divisoria")
        layout_sidebar.addWidget(linha)
        layout_sidebar.addSpacing(20)

        self.botoes_nav = []
        self.btn_nav_dashboard = self.criar_botao_nav("🎛️ Painel de Controle", 0)
        self.btn_nav_trend = self.criar_botao_nav("🔥 Caçador de Tendências", 1)
        self.btn_nav_upload = self.criar_botao_nav("🚀 Otimizar & Publicar", 2)
        self.btn_nav_auditoria = self.criar_botao_nav("📊 Auditoria de Canal", 3)
        self.btn_nav_config = self.criar_botao_nav("⚙️ Configurações & APIs", 4)

        for btn in [self.btn_nav_dashboard, self.btn_nav_trend, self.btn_nav_upload, self.btn_nav_auditoria, self.btn_nav_config]:
            layout_sidebar.addWidget(btn)

        self.btn_nav_dashboard.setChecked(True)
        layout_sidebar.addStretch()
        
        lbl_versao = QLabel("v3.1 YouTube Edition\n© 2026 Inteligência Artificial")
        lbl_versao.setObjectName("versao_txt")
        lbl_versao.setAlignment(Qt.AlignCenter)
        layout_sidebar.addWidget(lbl_versao)
        
        layout_mestre.addWidget(self.sidebar)

        # ÁREA CENTRAL
        self.stack = QStackedWidget()
        self.stack.setObjectName("area_central")
        layout_mestre.addWidget(self.stack)

        self.stack.addWidget(self.criar_pagina_dashboard())
        self.stack.addWidget(self.criar_pagina_trends())
        self.stack.addWidget(self.criar_pagina_upload())
        self.stack.addWidget(self.criar_pagina_auditoria())
        self.stack.addWidget(self.criar_pagina_config())
        
        self.setCentralWidget(widget_central)
        self.aplicar_estilos_premium()

    def criar_botao_nav(self, texto, index):
        btn = QPushButton(texto)
        btn.setObjectName("btn_nav")
        btn.setCheckable(True)
        btn.setCursor(QCursor(Qt.PointingHandCursor))
        btn.clicked.connect(lambda: [self.stack.setCurrentIndex(index), [b.setChecked(False) for b in self.botoes_nav], btn.setChecked(True)])
        self.botoes_nav.append(btn)
        return btn

    def criar_pagina_dashboard(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(50, 50, 50, 50)
        
        lbl_titulo = QLabel("Painel de Controle - Conexões")
        lbl_titulo.setObjectName("titulo_pagina")
        layout.addWidget(lbl_titulo)

        grid_cards = QHBoxLayout()
        grid_cards.setSpacing(30)
        
        self.card_yt = ComponenteYouTube(self.lista_chaves)
        grid_cards.addWidget(self.card_yt)

        card_api = QFrame()
        card_api.setObjectName("card_status")
        layout_api = QVBoxLayout(card_api)
        self.lbl_status_api = QLabel(f"🟢 Gemini: {len(self.lista_chaves)} Chave(s) Ativa(s)" if self.lista_chaves else "🔴 Gemini: Vazio")
        self.lbl_status_api.setObjectName("txt_card")
        layout_api.addWidget(self.lbl_status_api)
        
        btn_ir_api = QPushButton("⚙️ Gerenciar Chaves Gemini")
        btn_ir_api.setObjectName("btn_acao_card")
        btn_ir_api.clicked.connect(lambda: self.btn_nav_config.click())
        layout_api.addWidget(btn_ir_api)
        grid_cards.addWidget(card_api)

        layout.addLayout(grid_cards)
        layout.addStretch()
        return page

    def criar_pagina_trends(self):
        page = QWidget(); layout = QVBoxLayout(page); layout.setContentsMargins(50, 50, 50, 50)
        lbl_titulo = QLabel("Caçador de Tendências"); lbl_titulo.setObjectName("titulo_pagina"); layout.addWidget(lbl_titulo)
        
        linha_busca = QHBoxLayout()
        self.input_nicho = QLineEdit(); self.input_nicho.setPlaceholderText("Ex: Agricultura, DaVinci Resolve..."); self.input_nicho.setObjectName("input_pesquisa")
        self.btn_buscar_trends = QPushButton("🔍 Buscar Ideias"); self.btn_buscar_trends.setObjectName("btn_destaque")
        self.btn_buscar_trends.clicked.connect(self.iniciar_busca_trends)
        linha_busca.addWidget(self.input_nicho); linha_busca.addWidget(self.btn_buscar_trends); layout.addLayout(linha_busca)

        self.console_trends = QTextEdit(); self.console_trends.setReadOnly(True); self.console_trends.setObjectName("console_limpo")
        layout.addWidget(self.console_trends); return page

    def iniciar_busca_trends(self):
        nicho = self.input_nicho.text().strip()
        if not nicho: return
        self.btn_buscar_trends.setEnabled(False); self.console_trends.setText("Aguarde, varrendo vídeos em alta via YouTube Data API v3...")
        # Correção OBRIGATÓRIA: Passar o token para a API de busca real!
        self.trend_worker = TrendHunterWorker(nicho, self.lista_chaves, ARQUIVO_TOKEN)
        self.trend_worker.progresso_sinal.connect(self.console_trends.append)
        self.trend_worker.concluido_sinal.connect(lambda txt: [self.btn_buscar_trends.setEnabled(True), self.console_trends.setText(txt)])
        self.trend_worker.erro_sinal.connect(lambda err: [self.btn_buscar_trends.setEnabled(True), self.console_trends.append(f"\n{err}")])
        self.trend_worker.start()

    def criar_pagina_upload(self):
        page = QWidget(); layout = QVBoxLayout(page); layout.setContentsMargins(50, 50, 50, 50)
        lbl_titulo = QLabel("Otimização & Publicação Inteligente (YouTube)"); lbl_titulo.setObjectName("titulo_pagina"); layout.addWidget(lbl_titulo)
        
        opcoes_layout = QHBoxLayout()
        self.combo_formato = QComboBox(); self.combo_formato.setObjectName("combo_box")
        self.combo_formato.addItems(["🎬 Vídeo Longo (Horizontal)", "📱 YouTube Shorts (Vertical)", "📝 Post da Comunidade"])
        
        self.combo_publicacao = QComboBox(); self.combo_publicacao.setObjectName("combo_box")
        self.combo_publicacao.addItems(["⏰ Agendar Horário de Pico", "⚡ Publicar Agora", "💾 Apenas Salvar Arquivos Localmente"])
        
        opcoes_layout.addWidget(QLabel("Formato do Vídeo:")); opcoes_layout.addWidget(self.combo_formato)
        opcoes_layout.addWidget(QLabel("Ação:")); opcoes_layout.addWidget(self.combo_publicacao); layout.addLayout(opcoes_layout)

        frame_arquivos = QHBoxLayout()
        self.btn_sel_video = QPushButton("🎬 Selecionar Arquivo do Vídeo"); self.btn_sel_video.setObjectName("btn_secundario"); self.btn_sel_video.clicked.connect(lambda: self.selecionar_arquivo(True))
        self.preview_video = QLabel("Nenhum vídeo"); self.preview_video.setObjectName("box_preview")
        col_v = QVBoxLayout(); col_v.addWidget(self.btn_sel_video); col_v.addWidget(self.preview_video); frame_arquivos.addLayout(col_v)

        self.btn_sel_thumb = QPushButton("🖼️ Selecionar Miniatura (Thumbnail)"); self.btn_sel_thumb.setObjectName("btn_secundario"); self.btn_sel_thumb.clicked.connect(lambda: self.selecionar_arquivo(False))
        self.preview_thumb = QLabel("Nenhuma miniatura"); self.preview_thumb.setObjectName("box_preview")
        col_t = QVBoxLayout(); col_t.addWidget(self.btn_sel_thumb); col_t.addWidget(self.preview_thumb); frame_arquivos.addLayout(col_t)
        layout.addLayout(frame_arquivos)

        # -------------------------------------------------------------
        # ESTE É O BOTÃO QUE ESTAVA DANDO ERRO, E A FUNÇÃO DELE (iniciar_agente) 
        # AGORA ESTÁ 100% GARANTIDA NESTE CÓDIGO
        # -------------------------------------------------------------
        self.btn_iniciar = QPushButton("GERAR SEO E INICIAR UPLOAD NO YOUTUBE")
        self.btn_iniciar.setObjectName("btn_primario")
        self.btn_iniciar.clicked.connect(self.iniciar_agente)
        layout.addWidget(self.btn_iniciar)

        self.log_console = QTextEdit(); self.log_console.setReadOnly(True); self.log_console.setObjectName("console_tecnico")
        layout.addWidget(self.log_console)
        return page

    def selecionar_arquivo(self, is_video):
        tipo = "Todos os Vídeos (*.mp4 *.mkv *.mov *.webm *.avi);;Todos os Arquivos (*.*)" if is_video else "Imagens (*.png *.jpg *.jpeg)"
        arquivo, _ = QFileDialog.getOpenFileName(self, "Selecionar Arquivo", os.path.expanduser("~"), tipo)
        if arquivo:
            if is_video: 
                self.video_path = arquivo
                try:
                    clip = VideoFileClip(arquivo); frame = clip.get_frame(2.0); clip.close()
                    qimg = QImage(frame.data, frame.shape[1], frame.shape[0], frame.shape[2] * frame.shape[1], QImage.Format_RGB888)
                    self.preview_video.setPixmap(QPixmap.fromImage(qimg).scaled(220, 124, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                except:
                    self.preview_video.setText("✅ Arquivo Carregado")
            else: 
                self.thumb_path = arquivo
                self.preview_thumb.setPixmap(QPixmap(arquivo).scaled(220, 124, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    # =========================================================
    # AQUI ESTÁ A FUNÇÃO QUE TINHA SUMIDO E CAUSADO O ERRO!
    # =========================================================
    def iniciar_agente(self):
        if not self.video_path: 
            QMessageBox.warning(self, "Aviso", "Selecione um arquivo de vídeo primeiro.")
            return
            
        self.btn_iniciar.setEnabled(False)
        self.log_console.clear()
        
        # O AgenteWorker agora recebe o ARQUIVO_TOKEN para a API do YouTube varrer os dados reais!
        self.worker = AgenteWorker(self.video_path, self.combo_formato.currentText(), self.lista_chaves, ARQUIVO_TOKEN)
        self.worker.progresso_sinal.connect(self.log_console.append)
        self.worker.erro_sinal.connect(self.processo_erro)
        self.worker.aguardando_aprovacao_sinal.connect(self.exibir_dialogo_aprovacao) 
        self.worker.start()

    def exibir_dialogo_aprovacao(self, dados_seo):
        if DialogoAprovacao(dados_seo, self).exec():
            modo = self.combo_publicacao.currentText()
            if "Apenas Salvar" in modo:
                self.log_console.append("💾 Estratégia aprovada e salva localmente.")
                self.btn_iniciar.setEnabled(True)
            else:
                self.up_worker = PublicarWorker(self.video_path, self.thumb_path, dados_seo, self.combo_formato.currentText(), modo)
                self.up_worker.progresso_sinal.connect(self.log_console.append)
                self.up_worker.concluido_sinal.connect(self.processo_sucesso)
                self.up_worker.erro_sinal.connect(self.processo_erro)
                self.up_worker.start()
        else:
            self.log_console.append("❌ Operação cancelada pelo usuário.")
            self.btn_iniciar.setEnabled(True)

    def criar_pagina_auditoria(self):
        page = QWidget(); layout = QVBoxLayout(page); layout.setContentsMargins(50, 50, 50, 50)
        lbl_titulo = QLabel("Auditoria Analítica e Cirurgia de Canal"); lbl_titulo.setObjectName("titulo_pagina"); layout.addWidget(lbl_titulo)
        self.btn_auditoria = QPushButton("🔍 INICIAR VARREDURA PROFUNDA"); self.btn_auditoria.setObjectName("btn_primario")
        self.btn_auditoria.clicked.connect(self.iniciar_auditoria); layout.addWidget(self.btn_auditoria)
        self.log_auditoria = QTextEdit(); self.log_auditoria.setReadOnly(True); self.log_auditoria.setObjectName("console_tecnico")
        layout.addWidget(self.log_auditoria); return page

    def iniciar_auditoria(self):
        if not os.path.exists(ARQUIVO_TOKEN):
            QMessageBox.warning(self, "Aviso", "Conecte seu canal no Painel de Controle antes de rodar a auditoria.")
            return
        
        self.btn_auditoria.setEnabled(False); self.log_auditoria.clear()
        
        # O AuditoriaWorker recebe a lista de chaves e o ARQUIVO_TOKEN!
        self.aud_worker = AuditoriaWorker(self.lista_chaves, ARQUIVO_TOKEN)
        self.aud_worker.progresso_sinal.connect(self.log_auditoria.append)
        self.aud_worker.erro_sinal.connect(lambda e: [self.btn_auditoria.setEnabled(True), self.log_auditoria.append(f"\n{e}")])
        self.aud_worker.concluido_sinal.connect(self.exibir_resultado_auditoria)
        self.aud_worker.start()

    def exibir_resultado_auditoria(self, dados):
        self.btn_auditoria.setEnabled(True)
        if "aviso" in dados: self.log_auditoria.append(f"\n{dados['aviso']}"); return
        
        if DialogoAuditoria(dados, self).exec():
            videos_arrumar = dados.get('videos_para_otimizar', [])
            if videos_arrumar:
                # O AplicarCirurgiaWorker recebe os vídeos e o ARQUIVO_TOKEN!
                self.cirurgia_worker = AplicarCirurgiaWorker(videos_arrumar, ARQUIVO_TOKEN)
                self.cirurgia_worker.progresso_sinal.connect(self.log_auditoria.append)
                self.cirurgia_worker.concluido_sinal.connect(lambda m: self.log_auditoria.append(f"\n{m}"))
                self.cirurgia_worker.erro_sinal.connect(lambda e: self.log_auditoria.append(f"\n{e}"))
                self.cirurgia_worker.start()

    def criar_pagina_config(self):
        page = QWidget(); layout = QVBoxLayout(page); layout.setContentsMargins(50, 50, 50, 50)
        lbl_titulo = QLabel("Configurações das Chaves da IA (Gemini)"); lbl_titulo.setObjectName("titulo_pagina"); layout.addWidget(lbl_titulo)
        self.input_gemini = QTextEdit(); self.input_gemini.setObjectName("input_multi")
        if self.lista_chaves: self.input_gemini.setText("\n".join(self.lista_chaves))
        layout.addWidget(self.input_gemini)
        btn_salvar = QPushButton("💾 Salvar Chaves"); btn_salvar.setObjectName("btn_destaque")
        btn_salvar.clicked.connect(self.salvar_chave_gemini); layout.addWidget(btn_salvar)
        layout.addStretch(); return page

    def salvar_chave_gemini(self):
        self.lista_chaves = [c.strip() for c in self.input_gemini.toPlainText().split('\n') if c.strip()]
        with open(ARQUIVO_ENV, "w") as f: f.write(f"GEMINI_API_KEYS={','.join(self.lista_chaves)}\n")
        self.card_yt.lista_chaves = self.lista_chaves
        QMessageBox.information(self, "Sucesso", "Chaves atualizadas e salvas com sucesso!")

    def processo_sucesso(self, msg):
        self.log_console.append(msg); self.btn_iniciar.setEnabled(True)
        self.preview_video.setText("Nenhum vídeo"); self.preview_thumb.setText("Nenhuma miniatura")
        self.video_path = ""; self.thumb_path = ""

    def processo_erro(self, erro):
        self.btn_iniciar.setEnabled(True); self.log_console.append(erro)

    def aplicar_estilos_premium(self):
        self.setStyleSheet("""
        QMainWindow, #area_central, QDialog { background-color: #0F111A; }
        #sidebar { background-color: #171A21; border-right: 1px solid #282C36; }
        #linha_divisoria { background-color: #282C36; margin: 10px 0px; }
        #logo { color: #FFFFFF; font-size: 18px; font-weight: 900; letter-spacing: 1px; }
        #versao_txt { color: #64748B; font-size: 11px; margin-top: 20px; }
        QLabel { color: #CBD5E1; }
        #titulo_pagina { color: #FFFFFF; font-size: 26px; font-weight: 800; margin-bottom: 25px; border-bottom: 2px solid #2563EB; padding-bottom: 10px; }
        #btn_nav { background-color: transparent; color: #94A3B8; text-align: left; padding: 14px 20px; font-size: 14px; font-weight: 600; border-radius: 8px; border: none; margin-bottom: 6px; }
        #btn_nav:hover { background-color: #212631; color: #FFFFFF; }
        #btn_nav:checked { background-color: #2563EB; color: #FFFFFF; font-weight: bold; }
        #card_status { background-color: #1A1D24; border: 1px solid #282C36; border-radius: 12px; padding: 30px; }
        #txt_card { font-size: 18px; font-weight: 700; color: #FFFFFF; margin-bottom: 20px; }
        #btn_acao_card { background-color: #334155; color: #FFFFFF; border-radius: 6px; padding: 12px; font-weight: bold; font-size: 13px; }
        #btn_acao_card:hover { background-color: #475569; }
        #btn_destaque { background-color: #2563EB; color: #FFFFFF; padding: 12px 25px; border-radius: 6px; font-size: 14px; font-weight: bold; }
        #btn_primario { background-color: #10B981; color: #FFFFFF; font-size: 15px; padding: 16px; border-radius: 8px; font-weight: bold; margin-top: 15px; }
        #btn_secundario { background-color: #1F2937; color: #E5E7EB; border: 1px solid #374151; padding: 12px; border-radius: 6px; font-weight: bold; margin-bottom: 5px; }
        #input_pesquisa, #input_multi, #combo_box { background-color: #171A21; color: #FFFFFF; padding: 12px; border: 1px solid #282C36; border-radius: 6px; font-size: 13px; }
        #box_preview { background-color: #171A21; color: #64748B; border: 1px dashed #374151; border-radius: 6px; padding: 10px; qproperty-alignment: AlignCenter; min-height: 124px; }
        #console_limpo { background-color: #171A21; color: #E2E8F0; padding: 20px; border: 1px solid #282C36; border-radius: 8px; margin-top: 15px; }
        #console_tecnico { background-color: #0B0D12; color: #10B981; font-family: 'Consolas', 'Courier New'; padding: 15px; border: 1px solid #282C36; border-radius: 6px; margin-top: 15px; }
        QScrollBar:vertical { background-color: #0F111A; width: 12px; }
        QScrollBar::handle:vertical { background-color: #282C36; border-radius: 6px; min-height: 20px; }
        """)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    janela = JanelaPrincipal()
    janela.show()
    sys.exit(app.exec())