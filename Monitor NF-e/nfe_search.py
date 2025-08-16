# Bibliotecas padrão
import os
import gzip
import re
import base64
import logging
import sqlite3
import time
from pathlib import Path
from datetime import datetime

# Bibliotecas de terceiros
import requests
import requests_pkcs12
from requests.exceptions import RequestException
from zeep import Client
from zeep.transports import Transport
from zeep.exceptions import Fault
from lxml import etree
# -------------------------------------------------------------------
# Configuração de logs
# -------------------------------------------------------------------
def setup_logger():
    logger = logging.getLogger(__name__)
    if not logger.hasHandlers():
        handler = logging.StreamHandler()
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    return logger

logger = setup_logger()
logger.debug("Iniciando nfe_search.py")

BASE = Path(__file__).parent
# -------------------------------------------------------------------
# Fluxo NSU
# -------------------------------------------------------------------
def ciclo_nsu(db, parser, intervalo=3600):
    """
    Executa o ciclo de busca de NSU para todos os certificados cadastrados.
    Faz busca periódica e salva notas detalhadas.
    Se ocorrer erro de conexão ou indisponibilidade da SEFAZ/internet,
    registra no log, aguarda alguns minutos e tenta novamente sem encerrar o processo.
    """
    XML_DIR = Path("xmls")
    while True:
        try:
            logger.info(f"Iniciando busca periódica de NSU em {datetime.now().isoformat()}")
            for cnpj, path, senha, inf, cuf in db.get_certificados():
                try:
                    svc = NFeService(path, senha, cnpj, cuf)
                    ult_nsu = db.get_last_nsu(inf)
                    logger.debug(f"Buscando notas a partir do NSU {ult_nsu} para {inf}")
                    while True:
                        try:
                            resp = svc.fetch_by_cnpj("CNPJ" if len(cnpj)==14 else "CPF", ult_nsu)
                            if not resp:
                                logger.warning(f"Falha ao buscar NSU para {inf}")
                                break
                            cStat = parser.extract_cStat(resp)
                            if cStat == '656':  # Consumo indevido, bloqueio temporário
                                ult = parser.extract_last_nsu(resp)
                                if ult and ult != ult_nsu:
                                    db.set_last_nsu(inf, ult)
                                    logger.info(f"NSU atualizado após consumo indevido para {inf}: {ult}")
                                logger.warning(f"Consumo indevido, aguardando desbloqueio para {inf}")
                                break

                            docs = parser.extract_docs(resp)
                            if not docs:
                                logger.info(f"Nenhum novo docZip para {inf}")
                                break
                            for nsu, xml in docs:
                                try:
                                    validar_xml_auto(xml, 'leiauteNFe_v4.00.xsd')
                                    tree = etree.fromstring(xml.encode('utf-8'))
                                    infnfe = tree.find('.//{http://www.portalfiscal.inf.br/nfe}infNFe')
                                    if infnfe is None:
                                        continue
                                    chave = infnfe.attrib.get('Id','')[-44:]
                                    db.registrar_xml(chave, cnpj)
                                    # Salva o XML em disco
                                    salvar_xml_por_certificado(xml, cnpj)
                                    # Salva nota detalhada
                                    db.criar_tabela_detalhada()
                                    nota = extrair_nota_detalhada(xml, parser, db, chave)
                                    db.salvar_nota_detalhada(nota)
                                except Exception:
                                    logger.exception("Erro ao processar docZip")
                            ult = parser.extract_last_nsu(resp)
                            if ult and ult != ult_nsu:
                                db.set_last_nsu(inf, ult)
                                ult_nsu = ult
                            else:
                                break
                        except (requests.exceptions.RequestException, Fault, OSError) as e:
                            logger.warning(f"Erro de rede/SEFAZ para {inf}: {e}")
                            logger.info("Aguardando 3 minutos antes de tentar novamente este certificado...")
                            time.sleep(180)  # aguarda 3 minutos e tenta de novo o mesmo certificado
                            continue  # volta para o while interno
                except Exception as e:
                    logger.exception(f"Erro inesperado ao processar certificado {inf}: {e}")
                    continue  # vai para o próximo certificado

            # Após o ciclo, garante atualização das notas detalhadas a partir dos XMLs já salvos
            db.criar_tabela_detalhada()
            for xml_file in XML_DIR.rglob("*.xml"):
                try:
                    xml_txt = xml_file.read_text(encoding="utf-8")
                    chave = extrair_chave_nfe(xml_txt)
                    if chave:
                        nota = extrair_nota_detalhada(xml_txt, parser, db, chave)
                        db.salvar_nota_detalhada(nota)
                except Exception as e:
                    logger.warning(f"Falha ao extrair/atualizar nota detalhada de {xml_file}: {e}")

            logger.info(f"Busca de NSU finalizada. Dormindo por {intervalo/60:.0f} minutos...")

            time.sleep(intervalo)

        except Exception as e:
            logger.error(f"Erro geral no ciclo NSU: {e}")
            logger.info("Aguardando 5 minutos para reiniciar o ciclo...")
            time.sleep(300)  # espera 5 minutos antes de recomeçar o ciclo externo

# Função utilitária para extrair chave (44 dígitos) do XML
def extrair_chave_nfe(xml_txt):
    try:
        tree = etree.fromstring(xml_txt.encode("utf-8"))
        infnfe = tree.find('.//{http://www.portalfiscal.inf.br/nfe}infNFe')
        if infnfe is not None:
            return infnfe.attrib.get('Id', '')[-44:]
        return None
    except Exception:
        return None

# Função para montar o dict da nota detalhada a partir do XML
def extrair_nota_detalhada(xml_txt, parser, db, chave):
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

        # Busca status no banco (pode ser None)
        status_db = db.get_nf_status(chave)
        if status_db and status_db[0] and status_db[1]:
            status_str = f"{status_db[0]} – {status_db[1]}"
        else:
            status_str = "Autorizado o uso da NF-e"

        # CNPJ do destinatário
        cnpj_destinatario = dest.findtext('{http://www.portalfiscal.inf.br/nfe}CNPJ', "") if dest is not None else ""

        return {
            "chave": chave or "",
            "ie_tomador": dest.findtext('{http://www.portalfiscal.inf.br/nfe}IE') if dest is not None else "",
            "nome_emitente": emit.findtext('{http://www.portalfiscal.inf.br/nfe}xNome') if emit is not None else "",
            "cnpj_emitente": emit.findtext('{http://www.portalfiscal.inf.br/nfe}CNPJ') if emit is not None else "",
            "numero": ide.findtext('{http://www.portalfiscal.inf.br/nfe}nNF') if ide is not None else "",
            "data_emissao": (ide.findtext('{http://www.portalfiscal.inf.br/nfe}dhEmi')[:10]
                            if ide is not None and ide.findtext('{http://www.portalfiscal.inf.br/nfe}dhEmi')
                            else ""),
            "tipo": "NFe",
            "valor": valor,
            "cfop": cfop,
            "vencimento": vencimento,
            "uf": ide.findtext('{http://www.portalfiscal.inf.br/nfe}cUF') if ide is not None else "",
            "natureza": ide.findtext('{http://www.portalfiscal.inf.br/nfe}natOp') if ide is not None else "",
            "status": status_str,
            "atualizado_em": datetime.now().isoformat(),
            "cnpj_destinatario": cnpj_destinatario
        }
    except Exception as e:
        logger.warning(f"Erro ao extrair nota detalhada: {e}")
        return {
            "chave": chave or "",
            "ie_tomador": "",
            "nome_emitente": "",
            "cnpj_emitente": "",
            "numero": "",
            "data_emissao": "",
            "tipo": "NFe",
            "valor": "",
            "cfop": "",
            "vencimento": "",
            "uf": "",
            "natureza": "",
            "status": "Autorizado o uso da NF-e",
            "atualizado_em": datetime.now().isoformat(),
            "cnpj_destinatario": ""
        }
# -------------------------------------------------------------------
# Salvar XML na pasta
# -------------------------------------------------------------------
def sanitize_filename(s: str) -> str:
    """Remove caracteres inválidos para nomes de arquivos/pastas."""
    return re.sub(r'[\\/*?:"<>|]', "_", s).strip()

def format_cnpj_cpf_dir(doc: str) -> str:
    """
    Retorna apenas os dígitos do CNPJ ou CPF para uso seguro em nomes de pastas.
    Exemplo:
        '47.539.664/0001-97'  --> '47539664000197'
        '123.456.789-01'      --> '12345678901'
        '47539664000197'      --> '47539664000197'
    """
    return ''.join(filter(str.isdigit, doc or ""))

def salvar_xml_por_certificado(xml, cnpj_cpf, pasta_base="xmls"):
    """
    Salva o XML em uma pasta separada por certificado (apenas dígitos) e ano-mês de emissão.
    Exemplo: xmls/47539664000197/2025-08/00123-EMPRESA.xml
    """
    import os
    from lxml import etree
    import re

    def sanitize_filename(s: str) -> str:
        """Remove caracteres inválidos para nomes de arquivos/pastas."""
        return re.sub(r'[\\/*?:"<>|]', "_", s or "").strip()

    try:
        cnpj_cpf_fmt = format_cnpj_cpf_dir(cnpj_cpf)

        # Parse o XML para extrair dados de organização
        root = etree.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml)
        ide = root.find('.//{http://www.portalfiscal.inf.br/nfe}ide')
        if ide is not None:
            dEmi = ide.findtext('{http://www.portalfiscal.inf.br/nfe}dEmi')
            dhEmi = ide.findtext('{http://www.portalfiscal.inf.br/nfe}dhEmi')
            data_raw = dEmi or dhEmi
            if data_raw:
                data_part = data_raw.split("T")[0]
                ano_mes = data_part[:7] if len(data_part) >= 7 else "SEM_DATA"
            else:
                ano_mes = "SEM_DATA"
        else:
            ano_mes = "SEM_DATA"

        nNF = ide.findtext('{http://www.portalfiscal.inf.br/nfe}nNF') if ide is not None else "SEM_NUMERO"
        emit = root.find('.//{http://www.portalfiscal.inf.br/nfe}emit')
        xNome = emit.findtext('{http://www.portalfiscal.inf.br/nfe}xNome') if emit is not None else "SEM_NOME"

        pasta_dest = os.path.join(pasta_base, cnpj_cpf_fmt, ano_mes)
        os.makedirs(pasta_dest, exist_ok=True)

        nome_arquivo = f"{sanitize_filename(nNF)}-{sanitize_filename(xNome)[:40]}.xml"
        caminho_xml = os.path.join(pasta_dest, nome_arquivo)

        with open(caminho_xml, "w", encoding="utf-8") as f:
            f.write(xml)
        print(f"[SALVO] {caminho_xml}")
    except Exception as e:
        print(f"[ERRO ao salvar XML de {cnpj_cpf}]: {e}")
# -------------------------------------------------------------------
# Validação de XML com XSD
# -------------------------------------------------------------------
def validar_xml_auto(xml, default_xsd):
    # Mostra XML para debug
    print("\n--- XML sendo validado ---\n", xml, "\n-------------------------\n")

    # Mapeamento padrão
    ROOT_XSD_MAP = {
        "nfeProc":      "procNFe_v4.00.xsd",
        "NFe":          "leiauteNFe_v4.00.xsd",
        "procEventoNFe":"procEventoNFe_v1.00.xsd",
        "resNFe":       "resNFe_v1.01.xsd",
        "resEvento":    "resEvento_v1.01.xsd",
        "retConsReciNFe":"retConsReciNFe_v4.00.xsd",
        "enviNFe":      "enviNFe_v4.00.xsd",
        "distDFeInt":   "distDFeInt_v1.01.xsd",
        "inutNFe":      "inutNFe_v4.00.xsd",
        "procInutNFe":  "procInutNFe_v4.00.xsd",
        # Outros se necessário
    }
    # Descobre tag raiz
    try:
        tree = etree.fromstring(xml.encode('utf-8') if isinstance(xml, str) else xml)
        root_tag = tree.tag
        if '}' in root_tag:
            root_tag = root_tag.split('}', 1)[1]
    except Exception as e:
        raise Exception(f"Erro ao fazer parse do XML: {e}")

    # ATENÇÃO: Pule validação de eventos (resEvento, procEventoNFe etc)
    if root_tag.lower() in {"proceventonfe", "resevento", "receventonfe"}:
        print(f"[DEBUG] PULANDO validação XSD para {root_tag} (problema conhecido com XSD de eventos SEFAZ)")
        return True

    # Descobre nome do XSD correto
    xsd_file = ROOT_XSD_MAP.get(root_tag, default_xsd)

    # Busca o XSD no projeto (recursivo)
    def find_xsd(xsd_name, base_dir=None):
        from pathlib import Path
        if base_dir is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
        base_dir = Path(base_dir)
        for p in base_dir.rglob(xsd_name):
            if p.exists():
                print(f"[XSD] Encontrado: {p}")
                return str(p)
        print(f"[XSD] NÃO encontrado: {xsd_name} em {base_dir}")
        return None

    xsd_path = find_xsd(xsd_file)
    if not xsd_path:
        raise FileNotFoundError(f"Arquivo XSD não encontrado: {xsd_file} (procure inclusive em subpastas)")

    # PREVENÇÃO: Muda para pasta do XSD antes de validar (corrige problemas de includes)
    xsd_dir = os.path.dirname(xsd_path)
    cwd = os.getcwd()
    try:
        os.chdir(xsd_dir)
        # Usa só o nome do arquivo pois está na pasta
        with open(os.path.basename(xsd_path), 'rb') as f:
            schema_root = etree.XML(f.read())
        schema = etree.XMLSchema(schema_root)
        if not schema.validate(tree):
            errors = "\n".join([str(e) for e in schema.error_log])
            raise Exception(f"Erro ao validar XML com XSD {xsd_file}:\n{errors}")
    except etree.XMLSchemaParseError as e:
        raise Exception(f"[DEBUG] Falha ao validar XML (parse XSD): {e}")
    except etree.XMLSyntaxError as e:
        raise Exception(f"[DEBUG] Falha ao validar XML (syntax XSD): {e}")
    except Exception as e:
        raise Exception(f"[DEBUG] Falha ao validar XML: {e}")
    finally:
        os.chdir(cwd)
    return True
# -------------------------------------------------------------------
# URLs dos serviços
# -------------------------------------------------------------------
URL_DISTRIBUICAO = (
    "https://www1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/"
    "NFeDistribuicaoDFe.asmx?wsdl"
)
CONSULTA_WSDL = {
    '50': "https://nfe.sefaz.ms.gov.br/ws/NFeConsultaProtocolo4?wsdl",  # MS
    # ... os demais já estavam no seu dicionário, mas só MS interessa aqui.
}
URL_CONSULTA_FALLBACK = (
    "https://www1.nfe.fazenda.gov.br/NFeConsultaProtocolo/"
    "NFeConsultaProtocolo.asmx?wsdl"
)
# -------------------------------------------------------------------
# Banco de Dados
# -------------------------------------------------------------------
class DatabaseManager:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._initialize()
        logger.debug(f"Banco inicializado em {db_path}")

    def get_nf_status(self, chave):
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT cStat, xMotivo FROM nf_status WHERE chNFe = ?", (chave,)
            )
            return cur.fetchone()

    def extrair_dados_nfe(xml_str, db):
        """
        Extrai dados relevantes do XML da NF-e para a tabela detalhada.
        """
        try:
            tree = etree.fromstring(xml_str.encode("utf-8") if isinstance(xml_str, str) else xml_str)
            inf = tree.find('.//{http://www.portalfiscal.inf.br/nfe}infNFe')
            if inf is None:
                return None
            ide  = inf.find('{http://www.portalfiscal.inf.br/nfe}ide')
            emit = inf.find('{http://www.portalfiscal.inf.br/nfe}emit')
            dest = inf.find('{http://www.portalfiscal.inf.br/nfe}dest')
            tot  = inf.find('.//{http://www.portalfiscal.inf.br/nfe}ICMSTot')
            valor = tot.findtext('{http://www.portalfiscal.inf.br/nfe}vNF') if tot is not None else ''

            chave = inf.attrib.get('Id','')[-44:]
            ie_tomador = dest.findtext('{http://www.portalfiscal.inf.br/nfe}IE') if dest is not None else ''
            nome_emitente = emit.findtext('{http://www.portalfiscal.inf.br/nfe}xNome') if emit is not None else ''
            cnpj_emitente = emit.findtext('{http://www.portalfiscal.inf.br/nfe}CNPJ') if emit is not None else ''
            numero = ide.findtext('{http://www.portalfiscal.inf.br/nfe}nNF') if ide is not None else ''
            data_emissao = ide.findtext('{http://www.portalfiscal.inf.br/nfe}dhEmi') or \
                ide.findtext('{http://www.portalfiscal.inf.br/nfe}dEmi') if ide is not None else ''
            tipo = 'NFe'
            uf = ide.findtext('{http://www.portalfiscal.inf.br/nfe}cUF') if ide is not None else ''
            natureza = ide.findtext('{http://www.portalfiscal.inf.br/nfe}natOp') if ide is not None else ''
            # Busca status se existir no banco
            stat = db.get_nf_status(chave)
            status = f"{stat[0]} – {stat[1]}" if stat else "—"

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
                "status": status,
                "atualizado_em": datetime.now().isoformat()
            }
        except Exception as e:
            print(f"[ERRO extrair_dados_nfe] {e}")
            return None

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _initialize(self):
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute('''CREATE TABLE IF NOT EXISTS certificados (
                id INTEGER PRIMARY KEY,
                cnpj_cpf TEXT,
                caminho TEXT,
                senha TEXT,
                informante TEXT,
                cUF_autor TEXT
            )''')
            cur.execute('''CREATE TABLE IF NOT EXISTS xmls_baixados (
                chave TEXT PRIMARY KEY,
                cnpj_cpf TEXT
            )''')
            cur.execute('''CREATE TABLE IF NOT EXISTS nf_status (
                chNFe TEXT PRIMARY KEY,
                cStat TEXT,
                xMotivo TEXT
            )''')
            cur.execute('''CREATE TABLE IF NOT EXISTS nsu (
                informante TEXT PRIMARY KEY,
                ult_nsu TEXT
            )''')
            conn.commit()
            logger.debug("Tabelas verificadas/criadas no banco")
    
    def criar_tabela_detalhada(self):
        with self._connect() as conn:
            # Cria a tabela com o campo cnpj_destinatario, se ainda não existir
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
                atualizado_em DATETIME,
                cnpj_destinatario TEXT
            )
            ''')
            # Garante que a coluna cnpj_destinatario existe (caso o banco seja antigo)
            try:
                conn.execute("ALTER TABLE notas_detalhadas ADD COLUMN cnpj_destinatario TEXT;")
            except sqlite3.OperationalError:
                # Já existe, ignora o erro
                pass
            conn.commit()

    def salvar_nota_detalhada(self, nota):
        with self._connect() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO notas_detalhadas (
                    chave, ie_tomador, nome_emitente, cnpj_emitente, numero,
                    data_emissao, tipo, valor, cfop, vencimento, uf, natureza,
                    status, atualizado_em, cnpj_destinatario
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                nota['chave'], nota['ie_tomador'], nota['nome_emitente'], nota['cnpj_emitente'],
                nota['numero'], nota['data_emissao'], nota['tipo'], nota['valor'],
                nota.get('cfop', ''), nota.get('vencimento', ''), nota.get('uf', ''),
                nota.get('natureza', ''), nota['status'], nota['atualizado_em'],
                nota.get('cnpj_destinatario', '')
            ))
            conn.commit()

    def get_certificados(self):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT cnpj_cpf,caminho,senha,informante,cUF_autor FROM certificados"
            ).fetchall()
            logger.debug(f"Certificados carregados: {rows}")
            return rows

    def get_last_nsu(self, informante):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT ult_nsu FROM nsu WHERE informante=?", (informante,)
            ).fetchone()
            last = row[0] if row else "000000000000000"
            logger.debug(f"Último NSU para {informante}: {last}")
            return last

    def set_last_nsu(self, informante, nsu):
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO nsu (informante,ult_nsu) VALUES (?,?)",
                (informante, nsu)
            )
            conn.commit()
            logger.debug(f"NSU atualizado para {informante}: {nsu}")

    def registrar_xml(self, chave, cnpj):
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO xmls_baixados (chave,cnpj_cpf) VALUES (?,?)",
                (chave, cnpj)
            )
            conn.commit()
            logger.debug(f"XML registrado: {chave} (CNPJ {cnpj})")

    def get_chaves_missing_status(self):
        with self._connect() as conn:
            rows = conn.execute('''
                SELECT x.chave, x.cnpj_cpf
                FROM xmls_baixados x
                LEFT JOIN nf_status n
                ON x.chave = n.chNFe
                WHERE n.chNFe IS NULL
            ''').fetchall()
            logger.debug(f"Chaves sem status: {rows}")
            return rows

    def set_nf_status(self, chave, cStat, xMotivo):
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO nf_status (chNFe,cStat,xMotivo) VALUES (?,?,?)",
                (chave, cStat, xMotivo)
            )
            conn.commit()
            logger.debug(f"Status gravado: {chave} → {cStat} / {xMotivo}")

    def find_cert_by_cnpj(self, cnpj):
        for row in self.get_certificados():
            if row[0] == cnpj:
                return row
        return None

# -------------------------------------------------------------------
# Processador de XML
# -------------------------------------------------------------------
class XMLProcessor:
    NS = {'nfe':'http://www.portalfiscal.inf.br/nfe'}

    def extract_docs(self, resp_xml):
        logger.debug("Extraindo docs de distribuição")
        docs = []
        tree = etree.fromstring(resp_xml.encode('utf-8'))
        for dz in tree.findall('.//nfe:docZip', namespaces=self.NS):
            data = base64.b64decode(dz.text or '')
            xml  = gzip.decompress(data).decode('utf-8')
            nsu  = dz.get('NSU','')
            docs.append((nsu, xml))
        logger.debug(f"{len(docs)} documentos extraídos")
        return docs

    def extract_last_nsu(self, resp_xml):
        tree = etree.fromstring(resp_xml.encode('utf-8'))
        ult = tree.find('.//nfe:ultNSU', namespaces=self.NS)
        last = ult.text.zfill(15) if ult is not None and ult.text else None
        logger.debug(f"último NSU extraído: {last}")
        return last

    def extract_cStat(self, resp_xml):
        tree = etree.fromstring(resp_xml.encode('utf-8'))
        cs = tree.find('.//nfe:cStat', namespaces=self.NS)
        stat = cs.text if cs is not None else None
        logger.debug(f"cStat extraído: {stat}")
        return stat

    def parse_protNFe(self, xml_obj):
        logger.debug("Parseando protocolo NF-e")
        # Se já for Element, use direto
        if isinstance(xml_obj, etree._Element):
            tree = xml_obj
        else:
            tree = etree.fromstring(xml_obj.encode('utf-8'))
        prot = tree.find('.//{http://www.portalfiscal.inf.br/nfe}protNFe')
        if prot is None:
            logger.debug("nenhum protNFe encontrado")
            return None, None, None
        chNFe   = prot.findtext('{http://www.portalfiscal.inf.br/nfe}chNFe') or ''
        cStat   = prot.findtext('{http://www.portalfiscal.inf.br/nfe}cStat') or ''
        xMotivo = prot.findtext('{http://www.portalfiscal.inf.br/nfe}xMotivo') or ''
        logger.debug(f"Parse protocolo → chNFe={chNFe}, cStat={cStat}, xMotivo={xMotivo}")
        return chNFe, cStat, xMotivo

# -------------------------------------------------------------------
# Serviço SOAP
# -------------------------------------------------------------------
class NFeService:
    def __init__(self, cert_path, senha, informante, cuf):
        logger.debug(f"Inicializando serviço para informante={informante}, cUF={cuf}")
        sess = requests.Session()
        sess.mount('https://', requests_pkcs12.Pkcs12Adapter(
            pkcs12_filename=cert_path, pkcs12_password=senha
        ))
        trans = Transport(session=sess)
        self.dist_client = Client(wsdl=URL_DISTRIBUICAO, transport=trans)
        wsdl = CONSULTA_WSDL.get(str(cuf), URL_CONSULTA_FALLBACK)
        try:
            self.cons_client = Client(wsdl=wsdl, transport=trans)
            logger.debug(f"Cliente de protocolo inicializado: {wsdl}")
        except Exception as e:
            self.cons_client = None
            logger.warning(f"Falha ao inicializar WSDL de protocolo ({wsdl}): {e}")
        self.informante = informante
        self.cuf        = cuf

    def fetch_by_cnpj(self, tipo, ult_nsu):
        logger.debug(f"Chamando distribuição: tipo={tipo}, informante={self.informante}, ultNSU={ult_nsu}")
        distInt = etree.Element("distDFeInt",
            xmlns=XMLProcessor.NS['nfe'], versao="1.01"
        )
        etree.SubElement(distInt, "tpAmb").text    = "1"
        etree.SubElement(distInt, "cUFAutor").text = str(self.cuf)
        etree.SubElement(distInt, tipo).text       = self.informante
        sub = etree.SubElement(distInt, "distNSU")
        etree.SubElement(sub, "ultNSU").text       = ult_nsu

        xml_envio = etree.tostring(distInt, encoding='utf-8').decode()
        # Valide antes de enviar
        try:
            validar_xml_auto(xml_envio, 'distDFeInt_v1.01.xsd')
        except Exception as e:
            logger.error("XML de distribuição não passou na validação XSD. Corrija antes de enviar.")
            return None

        try:
            resp = self.dist_client.service.nfeDistDFeInteresse(nfeDadosMsg=distInt)
        except Fault as fault:
            logger.error(f"SOAP Fault Distribuição: {fault}")
            return None
        xml_str = etree.tostring(resp, encoding='utf-8').decode()
        logger.debug(f"Resposta Distribuição:\n{xml_str}")
        return xml_str

    def fetch_prot_nfe(self, chave):
        """
        Consulta o protocolo da NF-e pela chave, validando o XML de envio e resposta.
        """
        if not self.cons_client:
            logger.debug("Cliente de protocolo não disponível")
            return None

        logger.debug(f"Chamando protocolo para chave={chave}")
        NAMESPACE = "http://www.portalfiscal.inf.br/nfe"
        # Cria o XML da consulta (sem prefixo de namespace)
        cons = etree.Element("consSitNFe", versao="4.00", xmlns=NAMESPACE)
        etree.SubElement(cons, "tpAmb").text = "1"
        etree.SubElement(cons, "xServ").text = "CONSULTAR"
        etree.SubElement(cons, "chNFe").text = chave
        xml_envio = etree.tostring(cons, encoding='utf-8').decode()

        # Valida o XML de consulta (buscando consSitNFe_v4.00.xsd em subpastas)
        try:
            validar_xml_auto(xml_envio, 'consSitNFe_v4.00.xsd')
        except Exception as e:
            logger.error("XML de consulta protocolo não passou na validação XSD.")
            return None

        # Chama o serviço SOAP
        try:
            resp = self.cons_client.service.nfeConsultaNF(cons)
        except Fault as fault:
            logger.error(f"SOAP Fault Protocolo: {fault}")
            return None

        # Zeep pode retornar lxml.Element, string, ou objeto
        if hasattr(resp, 'decode'):
            resp_xml = resp.decode()
        elif hasattr(resp, '__str__'):
            resp_xml = str(resp)
        else:
            resp_xml = etree.tostring(resp, encoding="utf-8").decode()

        # Protege contra respostas inválidas (vazia, HTML, etc)
        if not resp_xml or resp_xml.strip().startswith('<html') or resp_xml.strip() == '':
            logger.warning("Resposta inválida da SEFAZ (não é XML): %s", resp_xml)
            return None

        # (Opcional) Salva para depuração
        # with open('ult_resposta_protocolo.xml', 'w', encoding='utf-8') as f:
        #     f.write(resp_xml)

        # Valida o XML da resposta (padrão é leiauteNFe_v4.00.xsd, mas pode mudar conforme SEFAZ)
        try:
            validar_xml_auto(resp_xml, 'leiauteNFe_v4.00.xsd')
        except Exception:
            logger.warning("Resposta da SEFAZ não passou na validação XSD.")
            return None

        logger.debug(f"Resposta Protocolo (raw):\n{resp_xml}")
        return resp_xml

# -------------------------------------------------------------------
# Fluxo Principal
# -------------------------------------------------------------------
def main():
    BASE = Path(__file__).parent
    db = DatabaseManager(BASE / "notas.db")
    parser = XMLProcessor()
    logger.info(f"=== Início da busca: {datetime.now().isoformat()} ===")
    # 1) Distribuição
    for cnpj, path, senha, inf, cuf in db.get_certificados():
        logger.debug(f"Processando certificado: CNPJ={cnpj}, arquivo={path}, informante={inf}, cUF={cuf}")
        svc      = NFeService(path, senha, cnpj, cuf)
        last_nsu = db.get_last_nsu(inf)
        resp     = svc.fetch_by_cnpj("CNPJ" if len(cnpj)==14 else "CPF", last_nsu)
        if not resp:
            continue
        cStat = parser.extract_cStat(resp)
        ult   = parser.extract_last_nsu(resp)
        if cStat == '656':
            logger.info(f"{inf}: Consumo indevido (656), manter NSU em {last_nsu}")
        else:
            if ult:
                db.set_last_nsu(inf, ult)
            for nsu, xml in parser.extract_docs(resp):
                try:
                    validar_xml_auto(xml, 'leiauteNFe_v4.00.xsd')
                    tree   = etree.fromstring(xml.encode('utf-8'))
                    infnfe = tree.find('.//{http://www.portalfiscal.inf.br/nfe}infNFe')
                    if infnfe is None:
                        logger.debug("infNFe não encontrado no XML, pulando")
                        continue
                    chave  = infnfe.attrib.get('Id','')[-44:]
                    db.registrar_xml(chave, cnpj)
                except Exception:
                    logger.exception("Erro ao processar docZip")
    # 2) Consulta de Protocolo
    faltam = db.get_chaves_missing_status()
    if not faltam:
        logger.info("Nenhuma chave faltando status")
    else:
        for chave, cnpj in faltam:
            cert = db.find_cert_by_cnpj(cnpj)
            if not cert:
                logger.warning(f"Certificado não encontrado para {cnpj}, ignorando {chave}")
                continue
            _, path, senha, inf, cuf = cert
            svc = NFeService(path, senha, cnpj, cuf)
            logger.debug(f"Consultando protocolo para NF-e {chave} (informante {inf})")
            prot_xml = svc.fetch_prot_nfe(chave)
            if not prot_xml:
                continue
            ch, cStat, xMotivo = parser.parse_protNFe(prot_xml)
            if ch:
                db.set_nf_status(ch, cStat, xMotivo)
    logger.info(f"=== Busca concluída: {datetime.now().isoformat()} ===")

if __name__ == "__main__":
    BASE = Path(__file__).parent
    db = DatabaseManager(BASE / "notas.db")
    parser = XMLProcessor()
    ciclo_nsu(db, parser, intervalo=3600)  # 3600 segundos = 1h