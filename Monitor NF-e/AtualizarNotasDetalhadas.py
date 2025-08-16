import os
from pathlib import Path
from datetime import datetime
from lxml import etree
import sqlite3
import logging

# Configuração básica de log
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)

# Ajuste o caminho do banco e da pasta dos XMLs conforme seu projeto:
BASE = Path(__file__).parent
DB_PATH = BASE / "notas.db"
XML_DIR = BASE / "xmls"   # Ajuste se seus XMLs estiverem em outro diretório

def extrair_chave_nfe(xml_txt):
    try:
        tree = etree.fromstring(xml_txt.encode("utf-8"))
        infnfe = tree.find('.//{http://www.portalfiscal.inf.br/nfe}infNFe')
        if infnfe is not None:
            return infnfe.attrib.get('Id', '')[-44:]
        return None
    except Exception as e:
        logger.warning(f"Erro ao extrair chave: {e}")
        return None

def extrair_nota_detalhada(xml_txt, db=None):
    try:
        tree = etree.fromstring(xml_txt.encode('utf-8'))
        inf = tree.find('.//{http://www.portalfiscal.inf.br/nfe}infNFe')
        ide = inf.find('{http://www.portalfiscal.inf.br/nfe}ide') if inf is not None else None
        emit = inf.find('{http://www.portalfiscal.inf.br/nfe}emit') if inf is not None else None
        dest = inf.find('{http://www.portalfiscal.inf.br/nfe}dest') if inf is not None else None
        tot = tree.find('.//{http://www.portalfiscal.inf.br/nfe}ICMSTot')

        cfop = ""
        if inf is not None:
            for det in inf.findall('{http://www.portalfiscal.inf.br/nfe}det'):
                prod = det.find('{http://www.portalfiscal.inf.br/nfe}prod')
                if prod is not None:
                    cfop = prod.findtext('{http://www.portalfiscal.inf.br/nfe}CFOP') or ""
                    if cfop:
                        break

        vencimento = ""
        if inf is not None:
            cobr = inf.find('{http://www.portalfiscal.inf.br/nfe}cobr')
            if cobr is not None:
                dup = cobr.find('.//{http://www.portalfiscal.inf.br/nfe}dup')
                if dup is not None:
                    vencimento = dup.findtext('{http://www.portalfiscal.inf.br/nfe}dVenc', "")

        valor = ""
        if tot is not None:
            vnf = tot.findtext('{http://www.portalfiscal.inf.br/nfe}vNF')
            valor = f"R$ {float(vnf):,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.') if vnf else ""

        chave = inf.attrib.get('Id','')[-44:] if inf is not None else ""
        status_str = "Autorizado o uso da NF-e"

        return {
            "chave":       chave or "",
            "ie_tomador":  dest.findtext('{http://www.portalfiscal.inf.br/nfe}IE') if dest is not None else "",
            "nome_emitente": emit.findtext('{http://www.portalfiscal.inf.br/nfe}xNome') if emit is not None else "",
            "cnpj_emitente": emit.findtext('{http://www.portalfiscal.inf.br/nfe}CNPJ') if emit is not None else "",
            "numero":      ide.findtext('{http://www.portalfiscal.inf.br/nfe}nNF') if ide is not None else "",
            "data_emissao": (ide.findtext('{http://www.portalfiscal.inf.br/nfe}dhEmi')[:10]
                             if ide is not None and ide.findtext('{http://www.portalfiscal.inf.br/nfe}dhEmi')
                             else ""),
            "tipo":        "NFe",
            "valor":       valor,
            "cfop":        cfop,
            "vencimento":  vencimento,
            "uf":          ide.findtext('{http://www.portalfiscal.inf.br/nfe}cUF') if ide is not None else "",
            "natureza":    ide.findtext('{http://www.portalfiscal.inf.br/nfe}natOp') if ide is not None else "",
            "status":      status_str,
            "atualizado_em": datetime.now().isoformat()
        }
    except Exception as e:
        logger.warning(f"Erro ao extrair nota detalhada: {e}")
        return None

def criar_tabela_detalhada(conn):
    conn.execute('''
        CREATE TABLE IF NOT EXISTS notas_detalhadas (
            chave TEXT PRIMARY KEY,
            ie_tomador TEXT,
            nome_emitente TEXT,
            cnpj_emitente TEXT,
            numero TEXT,
            data_emissao TEXT,
            tipo TEXT,
            valor TEXT,
            cfop TEXT,
            vencimento TEXT,
            uf TEXT,
            natureza TEXT,
            status TEXT DEFAULT 'Autorizado o uso da NF-e',
            atualizado_em DATETIME
        )
    ''')

def salvar_nota_detalhada(conn, nota):
    conn.execute('''
        INSERT OR REPLACE INTO notas_detalhadas (
            chave, ie_tomador, nome_emitente, cnpj_emitente, numero,
            data_emissao, tipo, valor, cfop, vencimento,
            uf, natureza, status, atualizado_em
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        nota['chave'], nota['ie_tomador'], nota['nome_emitente'], nota['cnpj_emitente'],
        nota['numero'], nota['data_emissao'], nota['tipo'], nota['valor'],
        nota['cfop'], nota['vencimento'], nota['uf'], nota['natureza'],
        nota['status'], nota['atualizado_em']
    ))

def main():
    logger.info("Iniciando atualização de notas detalhadas a partir dos XMLs...")
    conn = sqlite3.connect(DB_PATH)
    criar_tabela_detalhada(conn)
    count = 0
    for xml_file in XML_DIR.rglob("*.xml"):
        try:
            xml_txt = xml_file.read_text(encoding="utf-8")
            chave = extrair_chave_nfe(xml_txt)
            if chave:
                nota = extrair_nota_detalhada(xml_txt)
                if nota and nota['chave']:
                    salvar_nota_detalhada(conn, nota)
                    count += 1
        except Exception as e:
            logger.warning(f"Erro ao processar {xml_file}: {e}")
    conn.commit()
    conn.close()
    logger.info(f"Atualização finalizada. Total de notas processadas: {count}")

if __name__ == "__main__":
    main()
