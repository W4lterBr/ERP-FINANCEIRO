import os
from pathlib import Path
from lxml import etree
import sqlite3
from datetime import datetime

BASE = Path(__file__).parent
DB_PATH = BASE / "notas.db"
XMLS_DIR = BASE / "xmls"

# --- MAPEAMENTO UF ---
CODIGOS_UF = {
    '11':'RO','12':'AC','13':'AM','14':'RR','15':'PA','16':'AP','17':'TO',
    '21':'MA','22':'PI','23':'CE','24':'RN','25':'PB','26':'PE','27':'AL','28':'SE','29':'BA',
    '31':'MG','32':'ES','33':'RJ','35':'SP','41':'PR','42':'SC','43':'RS',
    '50':'MS','51':'MT','52':'GO','53':'DF'
}

def extrair_info_nfe(xml_path):
    try:
        with open(xml_path, "r", encoding="utf-8") as f:
            xml_txt = f.read()
        tree = etree.fromstring(xml_txt.encode("utf-8"))
        inf = tree.find('.//{http://www.portalfiscal.inf.br/nfe}infNFe')
        ide  = inf.find('{http://www.portalfiscal.inf.br/nfe}ide') if inf is not None else None
        emit = inf.find('{http://www.portalfiscal.inf.br/nfe}emit') if inf is not None else None
        dest = inf.find('{http://www.portalfiscal.inf.br/nfe}dest') if inf is not None else None
        tot  = tree.find('.//{http://www.portalfiscal.inf.br/nfe}ICMSTot')

        # Vencimento (<dup><dVenc>)
        vencimento = ""
        cobr = inf.find('{http://www.portalfiscal.inf.br/nfe}cobr') if inf is not None else None
        if cobr is not None:
            dup = cobr.find('.//{http://www.portalfiscal.inf.br/nfe}dup')
            if dup is not None:
                vencimento = dup.findtext('{http://www.portalfiscal.inf.br/nfe}dVenc', "")

        # CFOP do 1º produto
        cfop = ""
        if inf is not None:
            for det in inf.findall('{http://www.portalfiscal.inf.br/nfe}det'):
                prod = det.find('{http://www.portalfiscal.inf.br/nfe}prod')
                if prod is not None:
                    cfop = prod.findtext('{http://www.portalfiscal.inf.br/nfe}CFOP')
                    if cfop:
                        break

        valor = tot.findtext('{http://www.portalfiscal.inf.br/nfe}vNF') if tot is not None else ""
        chave = inf.attrib.get('Id', '')[-44:] if inf is not None else ""
        ie_tomador = dest.findtext('{http://www.portalfiscal.inf.br/nfe}IE') if dest is not None else ""
        nome_emitente = emit.findtext('{http://www.portalfiscal.inf.br/nfe}xNome') if emit is not None else ""
        cnpj_emitente = emit.findtext('{http://www.portalfiscal.inf.br/nfe}CNPJ') if emit is not None else ""
        numero = ide.findtext('{http://www.portalfiscal.inf.br/nfe}nNF') if ide is not None else ""
        data_emissao = (
            ide.findtext('{http://www.portalfiscal.inf.br/nfe}dhEmi') or 
            ide.findtext('{http://www.portalfiscal.inf.br/nfe}dEmi')
        ) if ide is not None else ""
        tipo = 'NFe'
        uf_num = ide.findtext('{http://www.portalfiscal.inf.br/nfe}cUF') if ide is not None else ""
        uf = CODIGOS_UF.get(uf_num, uf_num)
        natureza = ide.findtext('{http://www.portalfiscal.inf.br/nfe}natOp') if ide is not None else ""

        # Limpeza dos campos
        def limpa(v):
            return v if (v and v.strip() and v.strip().lower() not in ["none", "null"]) else ""

        return {
            "chave": limpa(chave),
            "ie_tomador": limpa(ie_tomador),
            "nome_emitente": limpa(nome_emitente),
            "cnpj_emitente": limpa(cnpj_emitente),
            "numero": limpa(numero),
            "data_emissao": limpa(data_emissao),
            "tipo": tipo,
            "valor": limpa(valor),
            "uf": limpa(uf),
            "cfop": limpa(cfop),
            "natureza": limpa(natureza),
            "vencimento": limpa(vencimento),
            "status": "",  # Vai ser preenchido depois se houver evento
            "atualizado_em": datetime.now().isoformat()
        }
    except Exception as e:
        print(f"[ERRO ao extrair dados de {xml_path}]: {e}")
        return None

def detectar_evento_cancelamento(xml_path):
    # Detecta eventos de cancelamento e retorna a chave afetada se houver
    try:
        tree = etree.parse(str(xml_path))
        root = tree.getroot()
        infEvento = root.find('.//{*}infEvento')
        if infEvento is not None:
            chave = infEvento.findtext('{*}chNFe') or infEvento.findtext('{*}chCTe')
            tpEvento = infEvento.findtext('{*}tpEvento')
            if tpEvento == "110111":  # Cancelamento
                return chave, "Cancelada"
        return None, None
    except Exception as e:
        print(f"[ERRO lendo evento {xml_path}]: {e}")
        return None, None

def atualizar_notas_detalhadas():
    # Cria a tabela completa se não existir
    with sqlite3.connect(DB_PATH) as conn:
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
            uf TEXT,
            cfop TEXT,
            natureza TEXT,
            vencimento TEXT,
            status TEXT,
            atualizado_em DATETIME
        )
        ''')

    # --- Atualiza notas detalhadas ---
    count = 0
    for xml_file in XMLS_DIR.rglob("*.xml"):
        nota = extrair_info_nfe(xml_file)
        if nota and nota["chave"]:
            try:
                with sqlite3.connect(DB_PATH) as conn:
                    conn.execute('''
                        INSERT OR REPLACE INTO notas_detalhadas (
                            chave, ie_tomador, nome_emitente, cnpj_emitente, numero,
                            data_emissao, tipo, valor, uf, cfop, natureza, vencimento, status, atualizado_em
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        nota['chave'], nota['ie_tomador'], nota['nome_emitente'], nota['cnpj_emitente'],
                        nota['numero'], nota['data_emissao'], nota['tipo'], nota['valor'],
                        nota['uf'], nota['cfop'], nota['natureza'], nota['vencimento'],
                        nota['status'], nota['atualizado_em']
                    ))
                count += 1
                print(f"[OK] Nota {nota['chave']} atualizada.")
            except Exception as e:
                print(f"[ERRO ao salvar nota {nota['chave']}]: {e}")

    # --- Atualiza status de notas com eventos de cancelamento ---
    atualizadas = 0
    for xml_file in XMLS_DIR.rglob("*.xml"):
        chave, evento = detectar_evento_cancelamento(xml_file)
        if chave and evento:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute(
                    "UPDATE notas_detalhadas SET status=? WHERE chave=?",
                    (evento, chave)
                )
                atualizadas += 1
                print(f"Nota {chave} atualizada para status: {evento}")

    print(f"[RESUMO] {count} notas detalhadas atualizadas no banco. {atualizadas} notas marcadas como canceladas.")

if __name__ == "__main__":
    atualizar_notas_detalhadas()
