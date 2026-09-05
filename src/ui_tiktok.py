import os
import sys
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QMessageBox
from publicador_tiktok import PublicadorTikTok

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) if not getattr(sys, 'frozen', False) else os.path.dirname(os.path.dirname(sys.executable))
PASTA_CONFIG = os.path.join(BASE_DIR, "config")
ARQUIVO_TOKEN_TIKTOK = os.path.join(PASTA_CONFIG, "tiktok_token.json")

class ComponenteTikTok(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card_status")
        
        layout_tk = QVBoxLayout(self)
        self.lbl_status_tk = QLabel("🔴 TikTok: Desconectado")
        self.lbl_status_tk.setObjectName("txt_card")
        layout_tk.addWidget(self.lbl_status_tk)
        
        self.frame_perfil_tk = QFrame()
        self.frame_perfil_tk.setVisible(False)
        layout_perfil_tk = QHBoxLayout(self.frame_perfil_tk)
        layout_perfil_tk.setContentsMargins(0, 10, 0, 15)
        
        self.img_canal_tk = QLabel("🎵")
        self.img_canal_tk.setFixedSize(80, 80)
        self.img_canal_tk.setStyleSheet("background-color: #000000; border-radius: 40px; color: #25F4EE; font-size: 30px;")
        self.img_canal_tk.setAlignment(Qt.AlignCenter)
        layout_perfil_tk.addWidget(self.img_canal_tk)
        
        info_layout_tk = QVBoxLayout()
        self.lbl_nome_canal_tk = QLabel("Conta TikTok Ativa")
        self.lbl_nome_canal_tk.setStyleSheet("color: #FFFFFF; font-size: 18px; font-weight: bold;")
        self.lbl_stats_canal_tk = QLabel("🔒 Modo Sandbox | Dados Bloqueados")
        self.lbl_stats_canal_tk.setStyleSheet("color: #94A3B8; font-size: 13px;")
        
        info_layout_tk.addWidget(self.lbl_nome_canal_tk)
        info_layout_tk.addWidget(self.lbl_stats_canal_tk)
        info_layout_tk.addStretch()
        layout_perfil_tk.addLayout(info_layout_tk)
        layout_tk.addWidget(self.frame_perfil_tk)
        
        self.btn_conectar_tk = QPushButton("🔗 Conectar TikTok")
        self.btn_conectar_tk.setObjectName("btn_acao_card")
        self.btn_conectar_tk.clicked.connect(self.conectar_tiktok)
        layout_tk.addWidget(self.btn_conectar_tk)
        
        self.btn_desconectar_tk = QPushButton("❌ Desconectar TikTok")
        self.btn_desconectar_tk.setObjectName("btn_acao_perigo")
        self.btn_desconectar_tk.clicked.connect(self.desconectar_tiktok)
        layout_tk.addWidget(self.btn_desconectar_tk)
        
        self.atualizar_status()

    def atualizar_status(self):
        if os.path.exists(ARQUIVO_TOKEN_TIKTOK):
            self.lbl_status_tk.setText("🟢 TikTok: Conectado")
            self.btn_conectar_tk.setVisible(False)
            self.btn_desconectar_tk.setVisible(True)
            self.frame_perfil_tk.setVisible(True)
        else:
            self.lbl_status_tk.setText("🔴 TikTok: Desconectado")
            self.btn_conectar_tk.setVisible(True)
            self.btn_desconectar_tk.setVisible(False)
            self.frame_perfil_tk.setVisible(False)

    def conectar_tiktok(self):
        try:
            bot = PublicadorTikTok()
            bot.autenticar()
            self.atualizar_status()
            QMessageBox.information(self, "Sucesso", "TikTok conectado com sucesso!")
        except Exception as e:
            QMessageBox.critical(self, "Erro", str(e))
            
    def desconectar_tiktok(self):
        if os.path.exists(ARQUIVO_TOKEN_TIKTOK): os.remove(ARQUIVO_TOKEN_TIKTOK)
        self.atualizar_status()