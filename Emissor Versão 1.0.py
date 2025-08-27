# -*- coding: utf-8 -*-
"""
Modelo de Emissor de NFS-e (Interface completa + cálculos + certificado) com integração ao ERP (SQLite)
e porcentagens para retenções (digitou a %, calcula na hora sobre o total bruto da nota).

Autor: ChatGPT
Requisitos:
    pip install PyQt5 cryptography
"""

import os
import json
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from functools import partial

from PyQt5.QtCore import Qt, QDate
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget, QFormLayout, QGridLayout,
    QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QLineEdit, QComboBox, QDateEdit,
    QCheckBox, QPushButton, QFileDialog, QMessageBox, QSpinBox, QDoubleSpinBox
)

# Certificado (.PFX) - leitura básica (sujeito e validade)
from cryptography.hazmat.primitives.serialization.pkcs12 import load_key_and_certificates


# ----------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------
def so_digitos(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())

def brl(v: float) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def ensure_dir(p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)

def _fmt_tipo_pessoa(doc: str) -> str:
    d = so_digitos(doc)
    return "PJ" if len(d) == 14 else "PF"

def _first_phone(*vals) -> str:
    for v in vals:
        d = so_digitos(v or "")
        if d:
            return d
    return ""

def _parse_percent(texto: str) -> float:
    """
    Aceita '10', '10%', '10,5 %', etc. Retorna 10.0, 10.5...
    Limita de 0 a 100.
    """
    s = (texto or "").strip().replace("%", "").replace(" ", "")
    s = s.replace(",", ".")
    try:
        v = float(s)
        if v < 0: v = 0.0
        if v > 100: v = 100.0
        return v
    except Exception:
        return 0.0


# ----------------------------------------------------------------------
# Integração ERP (SQLite)
# ----------------------------------------------------------------------
class ERPDB:
    """Camada mínima para ler companies e entities."""
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or self._find_db()
        self.conn = None
        if self.db_path and Path(self.db_path).exists():
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row

    @staticmethod
    def _find_db() -> str | None:
        root = Path(__file__).resolve().parent
        for p in root.rglob("erp_financeiro.db"):
            return str(p)
        return None

    def ok(self) -> bool:
        return self.conn is not None

    # --- queries ---
    def companies(self):
        if not self.ok(): return []
        sql = """SELECT id, cnpj, razao_social, rua, bairro, numero, cep, uf, cidade, email
                 FROM companies WHERE active=1 ORDER BY razao_social"""
        return self.conn.execute(sql).fetchall()

    def company_by_id(self, cid: int):
        if not self.ok(): return None
        return self.conn.execute("SELECT * FROM companies WHERE id=?", (cid,)).fetchone()

    def clientes(self):
        if not self.ok(): return []
        sql = """SELECT id, cnpj_cpf, razao_social, contato1, contato2,
                        rua, bairro, numero, cep, uf, cidade, email, kind
                   FROM entities
                  WHERE active=1 AND (kind='CLIENTE' OR kind='AMBOS')
               ORDER BY razao_social"""
        return self.conn.execute(sql).fetchall()

    def entity_by_id(self, eid: int):
        if not self.ok(): return None
        return self.conn.execute("SELECT * FROM entities WHERE id=?", (eid,)).fetchone()


# ----------------------------------------------------------------------
# Dados (estruturados)
# ----------------------------------------------------------------------
@dataclass
class Prestador:
    tipo_pessoa: str = "PJ"
    cpf_cnpj: str = ""
    inscricao_municipal: str = ""
    razao_social: str = ""
    nome_fantasia: str = ""
    regime_tributacao: str = "Normal"
    optante_simples: bool = False
    incentivador_cultural: bool = False
    endereco_cep: str = ""
    endereco_logradouro: str = ""
    endereco_numero: str = ""
    endereco_complemento: str = ""
    endereco_bairro: str = ""
    endereco_municipio: str = ""
    endereco_uf: str = ""
    endereco_cod_ibge: str = ""

@dataclass
class Tomador:
    tipo_pessoa: str = "PJ"
    cpf_cnpj: str = ""
    inscricao_municipal: str = ""
    inscricao_estadual: str = ""
    razao_social: str = ""
    email: str = ""
    telefone: str = ""
    endereco_cep: str = ""
    endereco_logradouro: str = ""
    endereco_numero: str = ""
    endereco_complemento: str = ""
    endereco_bairro: str = ""
    endereco_municipio: str = ""
    endereco_uf: str = ""
    endereco_cod_ibge: str = ""

@dataclass
class RPS:
    tipo: str = "RPS"
    serie: str = "A"
    numero: int = 1
    data_emissao: date = date.today()
    natureza_operacao: str = "1 - Tributação no município"
    exigibilidade_iss: str = "1 - Exigível"
    municipio_incidencia_cod_ibge: str = ""

@dataclass
class Servico:
    codigo_lista_servicos: str = ""
    cnae: str = ""
    item_lc116: str = ""
    discriminacao: str = ""
    aliquota_iss: float = 0.00
    iss_retido: bool = False

@dataclass
class Valores:
    valor_servicos: float = 0.0
    valor_deducoes: float = 0.0
    descontos_incondicionais: float = 0.0
    descontos_condicionais: float = 0.0
    outras_despesas: float = 0.0
    outros_acrescimos: float = 0.0
    ret_iss: float = 0.0
    ret_ir: float = 0.0
    ret_csll: float = 0.0
    ret_inss: float = 0.0
    ret_pis: float = 0.0
    ret_cofins: float = 0.0
    base_iss: float = 0.0
    valor_iss: float = 0.0
    total_retencoes: float = 0.0
    valor_liquido: float = 0.0


# ----------------------------------------------------------------------
# Janela principal
# ----------------------------------------------------------------------
class EmissorNFSWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Modelo de Emissor de NFS-e (com ERP + % de retenções)")
        self.resize(1140, 840)

        # ERP
        self.erp = ERPDB()
        if not self.erp.ok():
            QMessageBox.warning(
                self, "Banco de Dados",
                "Não localizei o arquivo 'erp_financeiro.db' na pasta ou subpastas.\n"
                "A integração ficará inativa até o arquivo estar disponível."
            )

        # Dados
        self.prestador = Prestador()
        self.tomador = Tomador()
        self.rps = RPS()
        self.servico = Servico()
        self.valores = Valores()

        # UI
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self._build_tab_prestador()
        self._build_tab_tomador()
        self._build_tab_rps()
        self._build_tab_servico()
        self._build_tab_valores()
        self._build_tab_certificado()
        self._build_footer_totais()

        # Carregar combos do ERP
        self._load_erp_into_ui()

    # ---------------------- PRESTADOR ----------------------
    def _build_tab_prestador(self):
        w = QWidget(); layout = QFormLayout(w)

        # seletor ERP
        top_row = QHBoxLayout()
        self.cmb_prestador_empresa = QComboBox()
        self.bt_recarrega_empresas = QPushButton("Recarregar do ERP")
        self.bt_recarrega_empresas.clicked.connect(self._load_empresas)
        top_row.addWidget(self.cmb_prestador_empresa, 1)
        top_row.addWidget(self.bt_recarrega_empresas)
        layout.addRow(QLabel("Selecionar Empresa (ERP):"), QWidget())
        s_top = QWidget(); s_top.setLayout(top_row)
        layout.addRow("", s_top)

        # campos
        self.cmb_prest_tipo = QComboBox(); self.cmb_prest_tipo.addItems(["PJ", "PF"])
        self.ed_prest_cpf_cnpj = QLineEdit()
        self.ed_prest_im = QLineEdit()
        self.ed_prest_razao = QLineEdit()
        self.ed_prest_fantasia = QLineEdit()
        self.cmb_regime = QComboBox(); self.cmb_regime.addItems(["Normal","Simples Nacional","MEI","Outros"])
        self.chk_prest_simples = QCheckBox("Optante pelo Simples Nacional")
        self.chk_prest_incent = QCheckBox("Incentivador Cultural")

        g_end = QGroupBox("Endereço do Prestador")
        grid = QGridLayout(g_end)
        self.ed_prest_cep = QLineEdit()
        self.ed_prest_logr = QLineEdit()
        self.ed_prest_num = QLineEdit()
        self.ed_prest_comp = QLineEdit()
        self.ed_prest_bairro = QLineEdit()
        self.ed_prest_mun = QLineEdit()
        self.ed_prest_uf = QLineEdit()
        self.ed_prest_codibge = QLineEdit()
        grid.addWidget(QLabel("CEP"), 0,0); grid.addWidget(self.ed_prest_cep,0,1)
        grid.addWidget(QLabel("Logradouro"), 0,2); grid.addWidget(self.ed_prest_logr,0,3)
        grid.addWidget(QLabel("Número"), 1,0); grid.addWidget(self.ed_prest_num,1,1)
        grid.addWidget(QLabel("Complemento"), 1,2); grid.addWidget(self.ed_prest_comp,1,3)
        grid.addWidget(QLabel("Bairro"), 2,0); grid.addWidget(self.ed_prest_bairro,2,1)
        grid.addWidget(QLabel("Município"), 2,2); grid.addWidget(self.ed_prest_mun,2,3)
        grid.addWidget(QLabel("UF"), 3,0); grid.addWidget(self.ed_prest_uf,3,1)
        grid.addWidget(QLabel("Cód. IBGE Município"), 3,2); grid.addWidget(self.ed_prest_codibge,3,3)

        layout.addRow("Tipo de Pessoa:", self.cmb_prest_tipo)
        layout.addRow("CPF/CNPJ:", self.ed_prest_cpf_cnpj)
        layout.addRow("Inscrição Municipal:", self.ed_prest_im)
        layout.addRow("Razão Social / Nome:", self.ed_prest_razao)
        layout.addRow("Nome Fantasia:", self.ed_prest_fantasia)
        layout.addRow("Regime de Tributação:", self.cmb_regime)
        layout.addRow(self.chk_prest_simples)
        layout.addRow(self.chk_prest_incent)
        layout.addRow(g_end)

        self.tabs.addTab(w, "Prestador")
        self.cmb_prestador_empresa.currentIndexChanged.connect(self._on_select_empresa)

    # ---------------------- TOMADOR ----------------------
    def _build_tab_tomador(self):
        w = QWidget(); layout = QFormLayout(w)

        # seletor ERP
        top_row = QHBoxLayout()
        self.cmb_tomador = QComboBox()
        self.bt_recarrega_tomadores = QPushButton("Recarregar do ERP")
        self.bt_recarrega_tomadores.clicked.connect(self._load_tomadores)
        top_row.addWidget(self.cmb_tomador, 1)
        top_row.addWidget(self.bt_recarrega_tomadores)
        layout.addRow(QLabel("Selecionar Tomador (ERP):"), QWidget())
        s_top = QWidget(); s_top.setLayout(top_row)
        layout.addRow("", s_top)

        # campos
        self.cmb_tom_tipo = QComboBox(); self.cmb_tom_tipo.addItems(["PJ","PF"])
        self.ed_tom_cpf_cnpj = QLineEdit()
        self.ed_tom_im = QLineEdit()
        self.ed_tom_ie = QLineEdit()
        self.ed_tom_razao = QLineEdit()
        self.ed_tom_email = QLineEdit()
        self.ed_tom_tel = QLineEdit()

        g_end = QGroupBox("Endereço do Tomador")
        grid = QGridLayout(g_end)
        self.ed_tom_cep = QLineEdit()
        self.ed_tom_logr = QLineEdit()
        self.ed_tom_num = QLineEdit()
        self.ed_tom_comp = QLineEdit()
        self.ed_tom_bairro = QLineEdit()
        self.ed_tom_mun = QLineEdit()
        self.ed_tom_uf = QLineEdit()
        self.ed_tom_codibge = QLineEdit()
        grid.addWidget(QLabel("CEP"), 0,0); grid.addWidget(self.ed_tom_cep,0,1)
        grid.addWidget(QLabel("Logradouro"), 0,2); grid.addWidget(self.ed_tom_logr,0,3)
        grid.addWidget(QLabel("Número"), 1,0); grid.addWidget(self.ed_tom_num,1,1)
        grid.addWidget(QLabel("Complemento"), 1,2); grid.addWidget(self.ed_tom_comp,1,3)
        grid.addWidget(QLabel("Bairro"), 2,0); grid.addWidget(self.ed_tom_bairro,2,1)
        grid.addWidget(QLabel("Município"), 2,2); grid.addWidget(self.ed_tom_mun,2,3)
        grid.addWidget(QLabel("UF"), 3,0); grid.addWidget(self.ed_tom_uf,3,1)
        grid.addWidget(QLabel("Cód. IBGE Município"), 3,2); grid.addWidget(self.ed_tom_codibge,3,3)

        layout.addRow("Tipo de Pessoa:", self.cmb_tom_tipo)
        layout.addRow("CPF/CNPJ:", self.ed_tom_cpf_cnpj)
        layout.addRow("Inscrição Municipal:", self.ed_tom_im)
        layout.addRow("Inscrição Estadual:", self.ed_tom_ie)
        layout.addRow("Razão Social / Nome:", self.ed_tom_razao)
        layout.addRow("E-mail:", self.ed_tom_email)
        layout.addRow("Telefone:", self.ed_tom_tel)
        layout.addRow(g_end)

        self.tabs.addTab(w, "Tomador")
        self.cmb_tomador.currentIndexChanged.connect(self._on_select_tomador)

    # ---------------------- RPS / NFS-e ----------------------
    def _build_tab_rps(self):
        w = QWidget(); layout = QFormLayout(w)
        self.cmb_rps_tipo = QComboBox(); self.cmb_rps_tipo.addItems(["RPS","Cupom","NFConjugada","Outros"])
        self.ed_rps_serie = QLineEdit("A")
        self.sp_rps_numero = QSpinBox(); self.sp_rps_numero.setMaximum(999999999); self.sp_rps_numero.setValue(1)
        self.dt_rps_emissao = QDateEdit(QDate.currentDate()); self.dt_rps_emissao.setDisplayFormat("dd/MM/yyyy"); self.dt_rps_emissao.setCalendarPopup(True)
        self.cmb_natureza = QComboBox(); self.cmb_natureza.addItems([
            "1 - Tributação no município", "2 - Tributação fora do município", "3 - Isenção",
            "4 - Imune", "5 - Exigibilidade suspensa por decisão judicial",
            "6 - Exigibilidade suspensa por procedimento administrativo"
        ])
        self.cmb_exig_iss = QComboBox(); self.cmb_exig_iss.addItems([
            "1 - Exigível", "2 - Não incidência", "3 - Isenção", "4 - Exportação",
            "5 - Imunidade", "6 - Exigibilidade suspensa por decisão judicial",
            "7 - Exigibilidade suspensa por procedimento administrativo"
        ])
        self.ed_mun_incid_ibge = QLineEdit()

        layout.addRow("Tipo de RPS:", self.cmb_rps_tipo)
        layout.addRow("Série:", self.ed_rps_serie)
        layout.addRow("Número:", self.sp_rps_numero)
        layout.addRow("Data de Emissão:", self.dt_rps_emissao)
        layout.addRow("Natureza da Operação:", self.cmb_natureza)
        layout.addRow("Exigibilidade do ISS:", self.cmb_exig_iss)
        layout.addRow("Município de Incidência (Cód. IBGE):", self.ed_mun_incid_ibge)
        self.tabs.addTab(w, "RPS / NFS-e")

    # ---------------------- SERVIÇO ----------------------
    def _build_tab_servico(self):
        w = QWidget(); layout = QFormLayout(w)
        self.ed_cod_lista = QLineEdit()
        self.ed_cnae = QLineEdit()
        self.ed_item_lc = QLineEdit()
        self.ed_discriminacao = QLineEdit()
        self.sb_aliq_iss = QDoubleSpinBox(); self.sb_aliq_iss.setSuffix(" %"); self.sb_aliq_iss.setDecimals(2); self.sb_aliq_iss.setMaximum(100.0)
        self.chk_iss_retido = QCheckBox("ISS Retido (responsável: Tomador)")
        layout.addRow("Código Lista de Serviços / Item LC 116:", self.ed_cod_lista)
        layout.addRow("CNAE (se aplicável):", self.ed_cnae)
        layout.addRow("Item Complementar:", self.ed_item_lc)
        layout.addRow("Discriminação dos Serviços:", self.ed_discriminacao)
        layout.addRow("Alíquota ISS:", self.sb_aliq_iss)
        layout.addRow(self.chk_iss_retido)
        self.tabs.addTab(w, "Serviço")

    # ---------------------- VALORES + RETENÇÕES (com % ao lado) ----------------------
    def _build_tab_valores(self):
        w = QWidget(); main = QVBoxLayout(w)

        # Valores do serviço
        g_val = QGroupBox("Valores do Serviço")
        form = QFormLayout(g_val)
        self.sb_val_serv = QDoubleSpinBox(); self._money(self.sb_val_serv)
        self.sb_val_ded = QDoubleSpinBox(); self._money(self.sb_val_ded)
        self.sb_desc_incond = QDoubleSpinBox(); self._money(self.sb_desc_incond)
        self.sb_desc_cond = QDoubleSpinBox(); self._money(self.sb_desc_cond)
        self.sb_outras_desp = QDoubleSpinBox(); self._money(self.sb_outras_desp)
        self.sb_outros_acres = QDoubleSpinBox(); self._money(self.sb_outros_acres)
        form.addRow("Valor dos Serviços:", self.sb_val_serv)
        form.addRow("Deduções:", self.sb_val_ded)
        form.addRow("Descontos Incondicionais:", self.sb_desc_incond)
        form.addRow("Descontos Condicionais:", self.sb_desc_cond)
        form.addRow("Outras Despesas (não tributáveis):", self.sb_outras_desp)
        form.addRow("Outros Acréscimos:", self.sb_outros_acres)

        # Retenções com % ao lado (caixinhas verdes da imagem)
        g_ret = QGroupBox("Retenções")
        grid = QGridLayout(g_ret)

        # % (QLineEdit) + valor (QDoubleSpinBox)
        def _mk_pct_box():
            ed = QLineEdit()
            ed.setPlaceholderText("%")
            ed.setMaximumWidth(60)  # parecido com a “caixa verde” da imagem
            return ed

        self.ed_pct_ret_iss = _mk_pct_box();   self.sb_ret_iss = QDoubleSpinBox(); self._money(self.sb_ret_iss)
        self.ed_pct_ret_ir  = _mk_pct_box();   self.sb_ret_ir  = QDoubleSpinBox(); self._money(self.sb_ret_ir)
        self.ed_pct_ret_csll= _mk_pct_box();   self.sb_ret_csll= QDoubleSpinBox(); self._money(self.sb_ret_csll)
        self.ed_pct_ret_inss= _mk_pct_box();   self.sb_ret_inss= QDoubleSpinBox(); self._money(self.sb_ret_inss)
        self.ed_pct_ret_pis = _mk_pct_box();   self.sb_ret_pis = QDoubleSpinBox(); self._money(self.sb_ret_pis)
        self.ed_pct_ret_cof = _mk_pct_box();   self.sb_ret_cofins=QDoubleSpinBox(); self._money(self.sb_ret_cofins)

        # Layout em 6 colunas: Label | % | Valor | Label | % | Valor
        # Linha 0
        grid.addWidget(QLabel("ISS Retido"), 0,0)
        grid.addWidget(self.ed_pct_ret_iss, 0,1)
        grid.addWidget(self.sb_ret_iss,     0,2)
        grid.addWidget(QLabel("IRRF"),      0,3)
        grid.addWidget(self.ed_pct_ret_ir,  0,4)
        grid.addWidget(self.sb_ret_ir,      0,5)
        # Linha 1
        grid.addWidget(QLabel("CSLL"),      1,0)
        grid.addWidget(self.ed_pct_ret_csll,1,1)
        grid.addWidget(self.sb_ret_csll,    1,2)
        grid.addWidget(QLabel("INSS"),      1,3)
        grid.addWidget(self.ed_pct_ret_inss,1,4)
        grid.addWidget(self.sb_ret_inss,    1,5)
        # Linha 2
        grid.addWidget(QLabel("PIS"),       2,0)
        grid.addWidget(self.ed_pct_ret_pis, 2,1)
        grid.addWidget(self.sb_ret_pis,     2,2)
        grid.addWidget(QLabel("COFINS"),    2,3)
        grid.addWidget(self.ed_pct_ret_cof, 2,4)
        grid.addWidget(self.sb_ret_cofins,  2,5)

        # Cálculos
        g_calc = QGroupBox("Cálculos")
        form2 = QFormLayout(g_calc)
        self.lbl_base_iss = QLabel("R$ 0,00")
        self.lbl_val_iss = QLabel("R$ 0,00")
        self.lbl_total_ret = QLabel("R$ 0,00")
        self.lbl_liquido = QLabel("R$ 0,00")
        form2.addRow("Base de Cálculo ISS:", self.lbl_base_iss)
        form2.addRow("Valor do ISS:", self.lbl_val_iss)
        form2.addRow("Total de Retenções:", self.lbl_total_ret)
        form2.addRow("Valor Líquido da NFS-e:", self.lbl_liquido)

        # Botões
        hb = QHBoxLayout()
        self.bt_recalcular = QPushButton("Recalcular Totais")
        self.bt_recalcular.clicked.connect(self._recalcular)
        self.bt_gerar_json = QPushButton("Gerar JSON (DPS)")
        self.bt_gerar_json.clicked.connect(self._gerar_json_dps)
        hb.addWidget(self.bt_recalcular); hb.addStretch(1); hb.addWidget(self.bt_gerar_json)

        main.addWidget(g_val); main.addWidget(g_ret); main.addWidget(g_calc); main.addLayout(hb)

        # qualquer alteração nos valores recalcula
        for sb in [self.sb_val_serv, self.sb_val_ded, self.sb_desc_incond, self.sb_desc_cond,
                   self.sb_outras_desp, self.sb_outros_acres, self.sb_ret_iss, self.sb_ret_ir,
                   self.sb_ret_csll, self.sb_ret_inss, self.sb_ret_pis, self.sb_ret_cofins,
                   self.sb_aliq_iss]:
            sb.valueChanged.connect(self._recalcular)

        # ligar % → aplica de imediato
        self.ed_pct_ret_iss.textChanged.connect(partial(self._on_percent_change, "iss"))
        self.ed_pct_ret_ir.textChanged.connect(partial(self._on_percent_change, "ir"))
        self.ed_pct_ret_csll.textChanged.connect(partial(self._on_percent_change, "csll"))
        self.ed_pct_ret_inss.textChanged.connect(partial(self._on_percent_change, "inss"))
        self.ed_pct_ret_pis.textChanged.connect(partial(self._on_percent_change, "pis"))
        self.ed_pct_ret_cof.textChanged.connect(partial(self._on_percent_change, "cofins"))

        self.tabs.addTab(w, "Valores e Retenções")

    def _money(self, sb: QDoubleSpinBox):
        sb.setDecimals(2); sb.setMaximum(10_000_000.00); sb.setPrefix("R$ "); sb.setSingleStep(1.00)

    # ---------------------- CERTIFICADO ----------------------
    def _build_tab_certificado(self):
        w = QWidget(); v = QVBoxLayout(w)
        self.bt_sel_pfx = QPushButton("Selecionar Certificado (.PFX)")
        self.bt_sel_pfx.clicked.connect(self._selecionar_pfx)
        self.ed_pfx_path = QLineEdit(); self.ed_pfx_path.setReadOnly(True)
        self.ed_pfx_senha = QLineEdit(); self.ed_pfx_senha.setEchoMode(QLineEdit.Password)
        f = QFormLayout()
        f.addRow(self.bt_sel_pfx)
        f.addRow("Caminho do .PFX:", self.ed_pfx_path)
        f.addRow("Senha do .PFX:", self.ed_pfx_senha)
        self.lbl_pfx_sujeito = QLabel("-")
        self.lbl_pfx_valid = QLabel("-")
        box_info = QGroupBox("Informações do Certificado")
        ff = QFormLayout(box_info)
        ff.addRow("Sujeito:", self.lbl_pfx_sujeito)
        ff.addRow("Validade:", self.lbl_pfx_valid)
        hb = QHBoxLayout()
        self.bt_testar_pfx = QPushButton("Validar Certificado")
        self.bt_testar_pfx.clicked.connect(self._validar_pfx)
        hb.addStretch(1); hb.addWidget(self.bt_testar_pfx)
        v.addLayout(f); v.addWidget(box_info); v.addLayout(hb)
        self.tabs.addTab(w, "Certificado")

    # ---------------------- Rodapé ----------------------
    def _build_footer_totais(self):
        bar = QWidget()
        hb = QHBoxLayout(bar)
        hb.addWidget(QLabel("Base ISS:")); self.footer_base = QLabel("R$ 0,00"); hb.addWidget(self.footer_base)
        hb.addSpacing(20)
        hb.addWidget(QLabel("ISS:")); self.footer_iss = QLabel("R$ 0,00"); hb.addWidget(self.footer_iss)
        hb.addSpacing(20)
        hb.addWidget(QLabel("Retenções:")); self.footer_ret = QLabel("R$ 0,00"); hb.addWidget(self.footer_ret)
        hb.addSpacing(20)
        hb.addWidget(QLabel("Líquido:")); self.footer_liq = QLabel("R$ 0,00"); hb.addWidget(self.footer_liq)
        hb.addStretch(1)
        self.statusBar().addPermanentWidget(bar, 1)

    # ======================================================================
    # Integração ERP – carregar combos e preencher
    # ======================================================================
    def _load_erp_into_ui(self):
        self._load_empresas()
        self._load_tomadores()
        if self.cmb_prestador_empresa.count() > 0:
            self.cmb_prestador_empresa.setCurrentIndex(0)
            self._on_select_empresa()

    def _load_empresas(self):
        self.cmb_prestador_empresa.blockSignals(True)
        self.cmb_prestador_empresa.clear()
        if self.erp.ok():
            for r in self.erp.companies():
                self.cmb_prestador_empresa.addItem(r["razao_social"], r["id"])
        self.cmb_prestador_empresa.blockSignals(False)

    def _load_tomadores(self):
        self.cmb_tomador.blockSignals(True)
        self.cmb_tomador.clear()
        if self.erp.ok():
            self.cmb_tomador.addItem("(selecione)", None)
            for r in self.erp.clientes():
                self.cmb_tomador.addItem(r["razao_social"], r["id"])
        else:
            self.cmb_tomador.addItem("(ERP não disponível)", None)
        self.cmb_tomador.blockSignals(False)

    def _on_select_empresa(self):
        cid = self.cmb_prestador_empresa.currentData()
        if not (self.erp.ok() and cid):
            return
        c = self.erp.company_by_id(int(cid))
        if not c:
            return
        self.cmb_prest_tipo.setCurrentText(_fmt_tipo_pessoa(c["cnpj"]))
        self.ed_prest_cpf_cnpj.setText(so_digitos(c["cnpj"] or ""))
        self.ed_prest_razao.setText(c["razao_social"] or "")
        self.ed_prest_cep.setText(so_digitos(c["cep"] or ""))
        self.ed_prest_logr.setText(c["rua"] or "")
        self.ed_prest_num.setText(c["numero"] or "")
        self.ed_prest_comp.setText("")
        self.ed_prest_bairro.setText(c["bairro"] or "")
        self.ed_prest_mun.setText(c["cidade"] or "")
        self.ed_prest_uf.setText((c["uf"] or "").upper())

    def _on_select_tomador(self):
        eid = self.cmb_tomador.currentData()
        if not (self.erp.ok() and eid):
            self._clear_tomador_fields(); return
        e = self.erp.entity_by_id(int(eid))
        if not e:
            self._clear_tomador_fields(); return
        self.cmb_tom_tipo.setCurrentText(_fmt_tipo_pessoa(e["cnpj_cpf"]))
        self.ed_tom_cpf_cnpj.setText(so_digitos(e["cnpj_cpf"] or ""))
        self.ed_tom_razao.setText(e["razao_social"] or "")
        self.ed_tom_email.setText(e["email"] or "")
        self.ed_tom_tel.setText(_first_phone(e["contato1"], e["contato2"]))
        self.ed_tom_im.setText("")
        self.ed_tom_ie.setText("")
        self.ed_tom_cep.setText(so_digitos(e["cep"] or ""))
        self.ed_tom_logr.setText(e["rua"] or "")
        self.ed_tom_num.setText(e["numero"] or "")
        self.ed_tom_comp.setText("")
        self.ed_tom_bairro.setText(e["bairro"] or "")
        self.ed_tom_mun.setText(e["cidade"] or "")
        self.ed_tom_uf.setText((e["uf"] or "").upper())

    def _clear_tomador_fields(self):
        for w in (
            self.ed_tom_cpf_cnpj, self.ed_tom_razao, self.ed_tom_email, self.ed_tom_tel,
            self.ed_tom_im, self.ed_tom_ie, self.ed_tom_cep, self.ed_tom_logr,
            self.ed_tom_num, self.ed_tom_comp, self.ed_tom_bairro, self.ed_tom_mun,
            self.ed_tom_uf, self.ed_tom_codibge
        ):
            w.setText("")

    # ======================================================================
    # % → valor de retenção (imediato)
    # ======================================================================
    def _total_bruto_nota(self) -> float:
        """
        Base para % das retenções: 'total da nota' bruto.
        Aqui considerado: Valor dos Serviços + Outros Acréscimos.
        (Se preferir outra composição, me diga que ajusto.)
        """
        return float(self.sb_val_serv.value()) + float(self.sb_outros_acres.value())

    def _on_percent_change(self, kind: str, _txt: str):
        pct = _parse_percent(_txt)
        total = self._total_bruto_nota()
        valor = round(total * (pct / 100.0), 2)

        if kind == "iss":
            self.sb_ret_iss.blockSignals(True); self.sb_ret_iss.setValue(valor); self.sb_ret_iss.blockSignals(False)
        elif kind == "ir":
            self.sb_ret_ir.blockSignals(True); self.sb_ret_ir.setValue(valor); self.sb_ret_ir.blockSignals(False)
        elif kind == "csll":
            self.sb_ret_csll.blockSignals(True); self.sb_ret_csll.setValue(valor); self.sb_ret_csll.blockSignals(False)
        elif kind == "inss":
            self.sb_ret_inss.blockSignals(True); self.sb_ret_inss.setValue(valor); self.sb_ret_inss.blockSignals(False)
        elif kind == "pis":
            self.sb_ret_pis.blockSignals(True); self.sb_ret_pis.setValue(valor); self.sb_ret_pis.blockSignals(False)
        elif kind == "cofins":
            self.sb_ret_cofins.blockSignals(True); self.sb_ret_cofins.setValue(valor); self.sb_ret_cofins.blockSignals(False)

        # Atualiza totais sem esperar outro evento
        self._recalcular()

    # ======================================================================
    # Lógica de negócio: cálculo e JSON
    # ======================================================================
    def _coletar_campos(self):
        # Prestador
        self.prestador.tipo_pessoa = self.cmb_prest_tipo.currentText()
        self.prestador.cpf_cnpj = so_digitos(self.ed_prest_cpf_cnpj.text())
        self.prestador.inscricao_municipal = self.ed_prest_im.text().strip()
        self.prestador.razao_social = self.ed_prest_razao.text().strip()
        self.prestador.nome_fantasia = self.ed_prest_fantasia.text().strip()
        self.prestador.regime_tributacao = self.cmb_regime.currentText()
        self.prestador.optante_simples = self.chk_prest_simples.isChecked()
        self.prestador.incentivador_cultural = self.chk_prest_incent.isChecked()
        self.prestador.endereco_cep = so_digitos(self.ed_prest_cep.text())
        self.prestador.endereco_logradouro = self.ed_prest_logr.text().strip()
        self.prestador.endereco_numero = self.ed_prest_num.text().strip()
        self.prestador.endereco_complemento = self.ed_prest_comp.text().strip()
        self.prestador.endereco_bairro = self.ed_prest_bairro.text().strip()
        self.prestador.endereco_municipio = self.ed_prest_mun.text().strip()
        self.prestador.endereco_uf = self.ed_prest_uf.text().strip().upper()
        self.prestador.endereco_cod_ibge = so_digitos(self.ed_prest_codibge.text())

        # Tomador
        self.tomador.tipo_pessoa = self.cmb_tom_tipo.currentText()
        self.tomador.cpf_cnpj = so_digitos(self.ed_tom_cpf_cnpj.text())
        self.tomador.inscricao_municipal = self.ed_tom_im.text().strip()
        self.tomador.inscricao_estadual = self.ed_tom_ie.text().strip()
        self.tomador.razao_social = self.ed_tom_razao.text().strip()
        self.tomador.email = self.ed_tom_email.text().strip()
        self.tomador.telefone = so_digitos(self.ed_tom_tel.text())
        self.tomador.endereco_cep = so_digitos(self.ed_tom_cep.text())
        self.tomador.endereco_logradouro = self.ed_tom_logr.text().strip()
        self.tomador.endereco_numero = self.ed_tom_num.text().strip()
        self.tomador.endereco_complemento = self.ed_tom_comp.text().strip()
        self.tomador.endereco_bairro = self.ed_tom_bairro.text().strip()
        self.tomador.endereco_municipio = self.ed_tom_mun.text().strip()
        self.tomador.endereco_uf = self.ed_tom_uf.text().strip().upper()
        self.tomador.endereco_cod_ibge = so_digitos(self.ed_tom_codibge.text())

        # RPS
        self.rps.tipo = self.cmb_rps_tipo.currentText()
        self.rps.serie = self.ed_rps_serie.text().strip()
        self.rps.numero = int(self.sp_rps_numero.value())
        self.rps.data_emissao = self.dt_rps_emissao.date().toPyDate()
        self.rps.natureza_operacao = self.cmb_natureza.currentText()
        self.rps.exigibilidade_iss = self.cmb_exig_iss.currentText()
        self.rps.municipio_incidencia_cod_ibge = so_digitos(self.ed_mun_incid_ibge.text())

        # Serviço
        self.servico.codigo_lista_servicos = self.ed_cod_lista.text().strip()
        self.servico.cnae = self.ed_cnae.text().strip()
        self.servico.item_lc116 = self.ed_item_lc.text().strip()
        self.servico.discriminacao = self.ed_discriminacao.text().strip()
        self.servico.aliquota_iss = float(self.sb_aliq_iss.value())
        self.servico.iss_retido = self.chk_iss_retido.isChecked()

        # Valores
        self.valores.valor_servicos = float(self.sb_val_serv.value())
        self.valores.valor_deducoes = float(self.sb_val_ded.value())
        self.valores.descontos_incondicionais = float(self.sb_desc_incond.value())
        self.valores.descontos_condicionais = float(self.sb_desc_cond.value())
        self.valores.outras_despesas = float(self.sb_outras_desp.value())
        self.valores.outros_acrescimos = float(self.sb_outros_acres.value())
        self.valores.ret_iss = float(self.sb_ret_iss.value())
        self.valores.ret_ir = float(self.sb_ret_ir.value())
        self.valores.ret_csll = float(self.sb_ret_csll.value())
        self.valores.ret_inss = float(self.sb_ret_inss.value())
        self.valores.ret_pis = float(self.sb_ret_pis.value())
        self.valores.ret_cofins = float(self.sb_ret_cofins.value())

    def _recalcular(self):
        self._coletar_campos()
        v = self.valores
        aliq = self.servico.aliquota_iss / 100.0

        # base ISS (genérico)
        base = max(0.0, v.valor_servicos - v.valor_deducoes - v.descontos_incondicionais)
        valor_iss = round(base * aliq, 2)

        # Se ISS Retido marcado e SEM % digitado no ISS, sugerir o próprio ISS
        if self.servico.iss_retido and (self.ed_pct_ret_iss.text().strip() == ""):
            self.sb_ret_iss.blockSignals(True)
            self.sb_ret_iss.setValue(valor_iss)
            self.sb_ret_iss.blockSignals(False)
            v.ret_iss = float(self.sb_ret_iss.value())  # reflete nos cálculos

        total_ret = v.ret_iss + v.ret_ir + v.ret_csll + v.ret_inss + v.ret_pis + v.ret_cofins
        liquido = (v.valor_servicos + v.outros_acrescimos) - total_ret - v.descontos_condicionais

        v.base_iss = round(base, 2)
        v.valor_iss = round(valor_iss, 2)
        v.total_retencoes = round(total_ret, 2)
        v.valor_liquido = round(liquido, 2)

        self.lbl_base_iss.setText(brl(v.base_iss))
        self.lbl_val_iss.setText(brl(v.valor_iss))
        self.lbl_total_ret.setText(brl(v.total_retencoes))
        self.lbl_liquido.setText(brl(v.valor_liquido))
        self.footer_base.setText(brl(v.base_iss))
        self.footer_iss.setText(brl(v.valor_iss))
        self.footer_ret.setText(brl(v.total_retencoes))
        self.footer_liq.setText(brl(v.valor_liquido))

    def _payload_dps(self) -> dict:
        self._coletar_campos()
        self._recalcular()
        data_emissao = self.rps.data_emissao.strftime("%Y-%m-%d")
        return {
            "versao": "1.00",
            "identificacaoRps": {
                "tipo": self.rps.tipo, "serie": self.rps.serie,
                "numero": self.rps.numero, "dataEmissao": data_emissao
            },
            "prestador": {
                "cpfCnpj": self.prestador.cpf_cnpj,
                "inscricaoMunicipal": self.prestador.inscricao_municipal,
                "razaoSocial": self.prestador.razao_social,
                "endereco": {
                    "cep": self.prestador.endereco_cep,
                    "logradouro": self.prestador.endereco_logradouro,
                    "numero": self.prestador.endereco_numero,
                    "complemento": self.prestador.endereco_complemento,
                    "bairro": self.prestador.endereco_bairro,
                    "municipio": self.prestador.endereco_municipio,
                    "uf": self.prestador.endereco_uf,
                    "codigoMunicipio": self.prestador.endereco_cod_ibge
                }
            },
            "tomador": {
                "cpfCnpj": self.tomador.cpf_cnpj,
                "inscricaoMunicipal": self.tomador.inscricao_municipal,
                "inscricaoEstadual": self.tomador.inscricao_estadual,
                "razaoSocial": self.tomador.razao_social,
                "contato": {"email": self.tomador.email, "telefone": self.tomador.telefone},
                "endereco": {
                    "cep": self.tomador.endereco_cep,
                    "logradouro": self.tomador.endereco_logradouro,
                    "numero": self.tomador.endereco_numero,
                    "complemento": self.tomador.endereco_complemento,
                    "bairro": self.tomador.endereco_bairro,
                    "municipio": self.tomador.endereco_municipio,
                    "uf": self.tomador.endereco_uf,
                    "codigoMunicipio": self.tomador.endereco_cod_ibge
                }
            },
            "servico": {
                "codigoListaServicos": self.servico.codigo_lista_servicos,
                "cnae": self.servico.cnae,
                "itemLC116": self.servico.item_lc116,
                "discriminacao": self.servico.discriminacao,
                "aliquotaISS": round(self.servico.aliquota_iss, 2),
                "issRetido": self.servico.iss_retido,
                "naturezaOperacao": self.rps.natureza_operacao,
                "exigibilidadeISS": self.rps.exigibilidade_iss,
                "municipioIncidencia": self.rps.municipio_incidencia_cod_ibge
            },
            "valores": {
                "valorServicos": round(self.valores.valor_servicos, 2),
                "valorDeducoes": round(self.valores.valor_deducoes, 2),
                "descontosIncondicionais": round(self.valores.descontos_incondicionais, 2),
                "descontosCondicionais": round(self.valores.descontos_condicionais, 2),
                "outrasDespesas": round(self.valores.outras_despesas, 2),
                "outrosAcrescimos": round(self.valores.outros_acrescimos, 2),
                "valorISS": round(self.valores.valor_iss, 2),
                "baseCalculo": round(self.valores.base_iss, 2),
                "retencoes": {
                    "iss": round(self.valores.ret_iss, 2),
                    "ir": round(self.valores.ret_ir, 2),
                    "csll": round(self.valores.ret_csll, 2),
                    "inss": round(self.valores.ret_inss, 2),
                    "pis": round(self.valores.ret_pis, 2),
                    "cofins": round(self.valores.ret_cofins, 2)
                },
                "totalRetencoes": round(self.valores.total_retencoes, 2),
                "valorLiquido": round(self.valores.valor_liquido, 2)
            }
        }

    def _gerar_json_dps(self):
        self._coletar_campos()
        erros = []
        if not self.prestador.cpf_cnpj: erros.append("Preencha o CPF/CNPJ do Prestador (ou selecione a empresa).")
        if not self.tomador.cpf_cnpj: erros.append("Preencha o CPF/CNPJ do Tomador (ou selecione o cliente).")
        if not self.servico.codigo_lista_servicos: erros.append("Informe o Código da Lista de Serviços / Item LC 116.")
        if self.valores.valor_servicos <= 0: erros.append("O Valor dos Serviços deve ser maior que zero.")
        if erros:
            QMessageBox.warning(self, "Validação", "Corrija:\n- " + "\n- ".join(erros)); return

        payload = self._payload_dps()
        out_dir = Path("emissoes"); ensure_dir(out_dir / "x")
        cnpj = self.prestador.cpf_cnpj or "prestador"
        rps_key = f"{self.rps.serie}{self.rps.numero}"
        out_path = out_dir / f"{cnpj}_{rps_key}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        QMessageBox.information(self, "OK", f"JSON gerado em:\n{out_path.resolve()}")

    # ======================================================================
    # Certificado (.PFX)
    # ======================================================================
    def _selecionar_pfx(self):
        path, _ = QFileDialog.getOpenFileName(self, "Selecione o Certificado (.PFX)", "", "Certificado PFX (*.pfx *.p12)")
        if not path: return
        self.ed_pfx_path.setText(path)

    def _validar_pfx(self):
        path = self.ed_pfx_path.text().strip()
        senha = self.ed_pfx_senha.text()
        if not path:
            QMessageBox.warning(self, "Certificado", "Selecione o arquivo .PFX."); return
        try:
            with open(path, "rb") as f: data = f.read()
            key, cert, extra = load_key_and_certificates(data, senha.encode("utf-8") if senha else None)
            if not cert: raise ValueError("Certificado inválido.")
            subject = cert.subject.rfc4514_string()
            not_before = cert.not_valid_before.strftime("%d/%m/%Y %H:%M")
            not_after = cert.not_valid_after.strftime("%d/%m/%Y %H:%M")
            self.lbl_pfx_sujeito.setText(subject)
            self.lbl_pfx_valid.setText(f"{not_before}  →  {not_after}")
            QMessageBox.information(self, "Certificado", "Certificado válido e carregado com sucesso!")
        except Exception as e:
            QMessageBox.critical(self, "Certificado", f"Falha ao carregar/validar o .PFX:\n{e}")

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    import sys
    app = QApplication(sys.argv)
    w = EmissorNFSWindow()
    w.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
