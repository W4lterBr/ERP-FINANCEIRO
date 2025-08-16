import os
import sqlite3
from pathlib import Path
from lxml import etree

from datetime import datetime

BASE = Path(__file__).parent
DB_PATH = BASE / "notas.db"
XMLS_DIR = BASE / "xmls"

def debug(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def get_prot_status(tree):
    # Busca o status de autorização da NF-e (protNFe/xMotivo)
    prot = tree.find('.//{http://www.portalfiscal.inf.br/nfe}protNFe')
    if prot is not None:
        xMotivo = prot.findtext('{http://www.portalfiscal.inf.br/nfe}xMotivo')
        if xMotivo:
            return xMotivo
    return ""

def get_event_status(tree):
    # Busca o status de eventos relacionados (ex: cancelamento)
    # Retorna lista dos status encontrados
    eventos = []
    for procEvento in tree.findall('.//{http://www.portalfiscal.inf.br/nfe}procEventoNFe'):
        ev = procEvento.find('.//{http://www.portalfiscal.inf.br/nfe}detEvento')
        if ev is not None:
            xEvento = ev.findtext('{http://www.portalfiscal.inf.br/nfe}descEvento')
            if xEvento:
                eventos.append(xEvento)
    # Também tenta pelo root caso o evento não seja um procEventoNFe
    for ev in tree.findall('.//{http://www.portalfiscal.inf.br/nfe}detEvento'):
        xEvento = ev.findtext('{http://www.portalfiscal.inf.br/nfe}descEvento')
        if xEvento and xEvento not in eventos:
            eventos.append(xEvento)
    return eventos

def extrair_info_nfe(xml_path):
    try:
        with open(xml_path, "r", encoding="utf-8") as f:
            xml_txt = f.read()
        tree = etree.fromstring(xml_txt.encode("utf-8"))
        inf = tree.find('.//{http://www.portalfiscal.inf.br/nfe}infNFe')
        if inf is None:
            debug(f"[IGNORADO] Não é NF-e: {xml_path.name}")
            return None
        ide  = inf.find('{http://www.portalfiscal.inf.br/nfe}ide')
        emit = inf.find('{http://www.portalfiscal.inf.br/nfe}emit')
        dest = inf.find('{http://www.portalfiscal.inf.br/nfe}dest')
        tot  = tree.find('.//{http://www.portalfiscal.inf.br/nfe}ICMSTot')
        valor = tot.findtext('{http://www.portalfiscal.inf.br/nfe}vNF') if tot is not None else ''

        chave = inf.attrib.get('Id', '')[-44:]
        ie_tomador = dest.findtext('{http://www.portalfiscal.inf.br/nfe}IE') if dest is not None else ""
        nome_emitente = emit.findtext('{http://www.portalfiscal.inf.br/nfe}xNome') if emit is not None else ""
        cnpj_emitente = emit.findtext('{http://www.portalfiscal.inf.br/nfe}CNPJ') if emit is not None else ""
        numero = ide.findtext('{http://www.portalfiscal.inf.br/nfe}nNF') if ide is not None else ""
        data_emissao = (
            ide.findtext('{http://www.portalfiscal.inf.br/nfe}dhEmi') or 
            ide.findtext('{http://www.portalfiscal.inf.br/nfe}dEmi')
        ) if ide is not None else ""
        tipo = 'NFe'
        uf = ide.findtext('{http://www.portalfiscal.inf.br/nfe}cUF') if ide is not None else ""
        natureza = ide.findtext('{http://www.portalfiscal.inf.br/nfe}natOp') if ide is not None else ""

        # CFOP
        cfop_ = ""
        for det in inf.findall('{http://www.portalfiscal.inf.br/nfe}det'):
            prod = det.find('{http://www.portalfiscal.inf.br/nfe}prod')
            if prod is not None:
                cfop_ = prod.findtext('{http://www.portalfiscal.inf.br/nfe}CFOP') or ""
                if cfop_:
                    break

        # Vencimento
        vencimento = ""
        cobr = inf.find('{http://www.portalfiscal.inf.br/nfe}cobr')
        if cobr is not None:
            dup = cobr.find('.//{http://www.portalfiscal.inf.br/nfe}dup')
            if dup is not None:
                vencimento = dup.findtext('{http://www.portalfiscal.inf.br/nfe}dVenc', "")

        # Status: "Autorizado o uso da NF-e" por padrão
        status = get_prot_status(tree) or "Autorizado o uso da NF-e"

        # Procura por eventos de cancelamento ou manifestação
        eventos = get_event_status(tree)
        if eventos:
            # Se houver mais de um evento relevante, pega o último da lista
            status = eventos[-1]

        return {
            "chave": chave,
            "ie_tomador": ie_tomador,
            "nome_emitente": nome_emitente,
            "cnpj_emitente": cnpj_emitente,
            "numero": numero,
            "data_emissao": data_emissao,
            "tipo": tipo,
            "valor": valor,
            "uf": uf,
            "natureza": natureza,
            "cfop": cfop_,
            "vencimento": vencimento,
            "status": status
        }
    except Exception as e:
        debug(f"[ERRO ao extrair dados de {xml_path}]: {e}")
        return None

def auto_ajuste():
    # Atualiza os campos cfop, vencimento e status das notas presentes no banco, a partir dos XMLs
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
                natureza TEXT,
                cfop TEXT,
                vencimento TEXT,
                status TEXT,
                atualizado_em DATETIME
            )
        ''')
        count = 0
        for xml_file in XMLS_DIR.rglob("*.xml"):
            nota = extrair_info_nfe(xml_file)
            if nota and nota["chave"]:
                try:
                    conn.execute('''
                        UPDATE notas_detalhadas
                        SET cfop=?, vencimento=?, status=?, atualizado_em=?
                        WHERE chave=?
                    ''', (
                        nota['cfop'], nota['vencimento'], nota['status'], datetime.now().isoformat(), nota['chave']
                    ))
                    debug(f"[OK] Ajustada nota {nota['chave']} | CFOP={nota['cfop']} | Vencimento={nota['vencimento']} | Status={nota['status']}")
                    count += 1
                except Exception as e:
                    debug(f"[ERRO ao atualizar nota {nota['chave']}]: {e}")
        debug(f"[RESUMO] {count} notas ajustadas no banco.")

if __name__ == "__main__":
    auto_ajuste()
