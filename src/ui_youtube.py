import os
import sys
import requests
from datetime import datetime
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QMessageBox
from analista_metricas import AnalistaCanal

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) if not getattr(sys, 'frozen', False) else os.path.dirname(os.path.dirname(sys.executable))
PASTA_CONFIG = os.path.join(BASE_DIR, "config")
ARQUIVO_TOKEN = os.path.join(PASTA_CONFIG, "token.json")
ARQUIVO_SECRET = os.path.join(PASTA_CONFIG, "client_secret.json")

class ComponenteYouTube(QFrame):
    def __init__(self, lista_chaves, parent=None):
        super().__init__(parent)
        self.setObjectName("card_status")
        self.lista_chaves = lista_chaves
        
        layout_yt = QVBoxLayout(self)
        self.lbl_status_yt = QLabel("🔴 YouTube: Desconectado")
        self.lbl_status_yt.setObjectName("txt_card")
        layout_yt.addWidget(self.lbl_status_yt)
        
        self.frame_perfil = QFrame()
        self.frame_perfil.setVisible(False)
        layout_perfil = QHBoxLayout(self.frame_perfil)
        layout_perfil.setContentsMargins(0, 10, 0, 15)
        
        self.img_canal = QLabel()
        self.img_canal.setFixedSize(80, 80)
        self.img_canal.setStyleSheet("background-color: #282C36; border-radius: 40px;")
        layout_perfil.addWidget(self.img_canal)
        
        info_layout = QVBoxLayout()
        self.lbl_nome_canal = QLabel("Nome do Canal")
        self.lbl_nome_canal.setStyleSheet("color: #FFFFFF; font-size: 18px; font-weight: bold;")
        self.lbl_stats_canal = QLabel("Inscritos: -- | Criado em: --")
        self.lbl_stats_canal.setStyleSheet("color: #94A3B8; font-size: 13px;")
        
        info_layout.addWidget(self.lbl_nome_canal)
        info_layout.addWidget(self.lbl_stats_canal)
        info_layout.addStretch()
        layout_perfil.addLayout(info_layout)
        layout_yt.addWidget(self.frame_perfil)
        
        self.btn_conectar_yt = QPushButton("🔗 Conectar YouTube")
        self.btn_conectar_yt.setObjectName("btn_acao_card")
        self.btn_conectar_yt.clicked.connect(self.conectar_youtube)
        layout_yt.addWidget(self.btn_conectar_yt)
        
        self.btn_desconectar_yt = QPushButton("❌ Desconectar Canal")
        self.btn_desconectar_yt.setObjectName("btn_acao_perigo")
        self.btn_desconectar_yt.clicked.connect(self.desconectar_youtube)
        layout_yt.addWidget(self.btn_desconectar_yt)
        
        self.atualizar_status()

    def atualizar_status(self):
        if os.path.exists(ARQUIVO_TOKEN):
            self.lbl_status_yt.setText("🟢 YouTube: Conectado")
            self.btn_conectar_yt.setVisible(False)
            self.btn_desconectar_yt.setVisible(True)
            self.frame_perfil.setVisible(True)
            self.carregar_dados_canal()
        else:
            self.lbl_status_yt.setText("🔴 YouTube: Desconectado")
            self.btn_conectar_yt.setVisible(True)
            self.btn_desconectar_yt.setVisible(False)
            self.frame_perfil.setVisible(False)

    def carregar_dados_canal(self):
        try:
            analista = AnalistaCanal(ARQUIVO_TOKEN, self.lista_chaves)
            youtube_data, _ = analista.obter_clientes_youtube()
            resposta = youtube_data.channels().list(part="snippet,statistics", mine=True).execute()
            
            if resposta.get('items'):
                canal = resposta['items'][0]
                data_limpa = canal['snippet']['publishedAt'].split('.')[0] + "Z" if '.' in canal['snippet']['publishedAt'] else canal['snippet']['publishedAt']
                
                self.lbl_nome_canal.setText(canal['snippet']['title'])
                self.lbl_stats_canal.setText(f"👥 Inscritos: {canal['statistics'].get('subscriberCount', '0')} | 📅 Criado: {datetime.strptime(data_limpa, '%Y-%m-%dT%H:%M:%SZ').strftime('%d/%m/%Y')}")
                
                pixmap = QPixmap()
                pixmap.loadFromData(requests.get(canal['snippet']['thumbnails']['default']['url']).content)
                self.img_canal.setPixmap(pixmap.scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                self.img_canal.setStyleSheet("border-radius: 40px; border: 2px solid #2563EB;")
        except Exception as e:
            self.lbl_nome_canal.setText("Erro de Carregamento")

    def conectar_youtube(self):
        if not os.path.exists(ARQUIVO_SECRET):
            QMessageBox.warning(self, "Aviso", "Arquivo client_secret.json não encontrado.")
            return
        try:
            AnalistaCanal(ARQUIVO_TOKEN, self.lista_chaves).obter_clientes_youtube()
            self.atualizar_status()
            QMessageBox.information(self, "Sucesso", "YouTube conectado com sucesso!")
        except Exception as e:
            QMessageBox.critical(self, "Erro", str(e))

    def desconectar_youtube(self):
        if os.path.exists(ARQUIVO_TOKEN): os.remove(ARQUIVO_TOKEN)
        self.atualizar_status()