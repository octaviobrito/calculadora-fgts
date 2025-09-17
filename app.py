# app.py — Calculadora FGTS Web (Streamlit) — versão Consultores
# Requisitos: pip install streamlit gspread oauth2client

import streamlit as st
import datetime as dt

# ======= CONFIG =======
MONTHLY_RATE = 0.0179              # 1,79% a.m.
IOF_RATE     = 0.0075              # ~0,75% (simplificado)
TAC_FIXED    = 7.0                 # TAC fixa (oculta) — registrada no Sheets
SHOW_CONSULTANT_COMMISSION = True
CONSULTANT_COMMISSION_RATE = 0.03  # 3% do líquido
DEFAULT_SHEET_NAME = "Simulações FGTS"
# ======================

# --------- Helpers ---------
def format_br(v: float) -> str:
    s = f"{v:,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")

def saque_aniversario(saldo: float) -> float:
    if saldo <= 0: return 0.0
    if saldo <= 500:    return 0.50 * saldo
    elif saldo <= 1000: return 0.40 * saldo + 50
    elif saldo <= 5000: return 0.30 * saldo + 150
    elif saldo <= 10000:return 0.20 * saldo + 650
    elif saldo <= 15000:return 0.15 * saldo + 1150
    elif saldo <= 20000:return 0.10 * saldo + 1900
    else:               return 0.05 * saldo + 2900

def meses_ate_proximo_aniversario(nasc: dt.date, ref: dt.date) -> int:
    ano = ref.year
    prox = dt.date(ano, nasc.month, min(nasc.day, 28))
    if prox < ref:
        prox = dt.date(ano + 1, nasc.month, min(nasc.day, 28))
    anos_diff = prox.year - ref.year
    meses = anos_diff * 12 + (prox.month - ref.month)
    if prox.day < ref.day:
        meses -= 1
    return max(meses, 0)

def parse_brl(texto: str) -> float:
    t = str(texto).strip()
    if not t:
        return 0.0
    return float(t.replace(".", "").replace(",", "."))

# --------- Google Sheets ----------
def get_sheet_client():
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials
    import streamlit as st
    from collections.abc import Mapping

    scopes = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/drive",
    ]

    sa = st.secrets.get("gcp_service_account")
    if not sa:
        raise FileNotFoundError(
            "Secret 'gcp_service_account' não encontrado. Configure em Settings → Secrets como TABELA TOML."
        )

    # Aceita AttrDict/dict/JSON string
    if isinstance(sa, Mapping):
        info = dict(sa)
    else:
        import json
        info = json.loads(sa)

    info.setdefault("token_uri", "https://oauth2.googleapis.com/token")

    # Conserta caso ainda existam '\n' literais
    pk = info.get("private_key", "")
    if "\\n" in pk and "\n" not in pk:
        info["private_key"] = pk.replace("\\n", "\n")

    creds = ServiceAccountCredentials.from_json_keyfile_dict(info, scopes=scopes)
    return gspread.authorize(creds)


def append_row_consulta(consultor: str, data_simul: str, data_nasc: str,
                        parcelas: int, saldo: float, liquido: float, tac_perc: float):
    client = get_sheet_client()
    sheet_name = st.secrets.get("sheet_name", DEFAULT_SHEET_NAME)
    sh = client.open(sheet_name)
    ws = sh.sheet1

    # Cabeçalho padrão A–I
    header_expected = [
        "Data Simulação", "Vendedor", "Data Nasc.", "Parcelas antecipadas",
        "Saldo FGTS considerado", "TAC", "Valor Líquido ao Cliente",
        "Data e hora da consulta", "WindowsUser"
    ]
    header = ws.row_values(1)
    if header != header_expected:
        if header:
            ws.update("A1:I1", [header_expected])
        else:
            ws.insert_row(header_expected, 1)

    # "WindowsUser" (no cloud pode ficar vazio)
    import getpass
    try:
        winuser = getpass.getuser()
    except Exception:
        winuser = ""

    linha = [
        data_simul,
        consultor or "",  # a coluna no sheet permanece "Vendedor" por compatibilidade
        data_nasc,
        str(parcelas),
        f"{saldo:.2f}",
        f"{tac_perc:.2f}%",
        f"{liquido:.2f}",
        dt.datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        winuser,
    ]
    ws.append_row(linha)

# --------- Cálculo principal ---------
def simular(data_nasc: dt.date, n_parcelas: int, saldo_inicial: float):
    data_simul = dt.date.today()
    if not (2 <= n_parcelas <= 10):
        raise ValueError("Parcelas devem estar entre 2 e 10.")
    if saldo_inicial <= 0:
        raise ValueError("Saldo FGTS deve ser maior que zero.")

    saldo = float(saldo_inicial)
    saques = []
    for _ in range(n_parcelas):
        s = saque_aniversario(saldo)
        s = max(0.0, min(s, saldo))
        saques.append(s)
        saldo -= s
        if saldo <= 0:
            saques += [0.0] * (n_parcelas - len(saques))
            break

    m0 = meses_ate_proximo_aniversario(data_nasc, data_simul)
    meses_list = [m0 + 12 * i for i in range(n_parcelas)]

    vps = []
    for saque, meses in zip(saques, meses_list):
        vp = saque if meses <= 0 else saque / ((1 + MONTHLY_RATE) ** meses)
        vps.append(vp)

    vp_total = sum(vps)
    iof_val  = IOF_RATE * vp_total
    apos_iof = vp_total - iof_val

    # Versão consultores: TAC NÃO reduz o líquido mostrado ao cliente (só registro)
    liquido = apos_iof

    return {
        "data_simul": data_simul.strftime("%d/%m/%Y"),
        "saques": saques,
        "meses": meses_list,
        "vp_total": vp_total,
        "iof": iof_val,
        "liquido": liquido,
    }

# =================== UI (Streamlit) ===================
st.set_page_config(page_title="Calculadora FGTS — Consultores", page_icon="💼", layout="centered")
st.title("Calculadora de Antecipação do FGTS — Consultores")

with st.form("form_fgts", clear_on_submit=False):
    colA, colB = st.columns(2)
    consultor = colA.text_input("Consultor (obrigatório)")
    data_nasc = colB.date_input("Data de nascimento", value=dt.date(1990, 1, 1), format="DD/MM/YYYY")

    col1, col2 = st.columns(2)
    parcelas = col1.number_input("Nº de parcelas (2 a 10)", min_value=2, max_value=10, step=1, value=2)
    saldo_txt = col2.text_input("Saldo FGTS (R$)", placeholder="Ex.: 12.345,67")

    submitted = st.form_submit_button("Calcular")

if submitted:
    try:
        if not consultor.strip():
            st.error("Informe o nome do consultor.")
            st.stop()

        saldo = parse_brl(saldo_txt)
        result = simular(data_nasc=data_nasc, n_parcelas=int(parcelas), saldo_inicial=saldo)

        # Resultado
        st.subheader("Resultado da simulação")
        st.write(f"**Data de Nascimento:** {data_nasc.strftime('%d/%m/%Y')}")
        st.write(f"**Parcelas antecipadas:** {parcelas}")
        st.write(f"**Saldo FGTS considerado:** R$ {format_br(saldo)}")

        with st.expander("Ver detalhamento dos saques (por ano)"):
            for i, (s, m) in enumerate(zip(result['saques'], result['meses']), start=1):
                st.write(f"Parcela {i}: **R$ {format_br(s)}** (em ~{m} meses)")

        st.write(f"**Valor Presente Total:** R$ {format_br(result['vp_total'])}")
        st.write(f"**IOF (~0,75%):** R$ {format_br(result['iof'])}")
        st.success(f"**VALOR LÍQUIDO AO CLIENTE: R$ {format_br(result['liquido'])}**")

        if SHOW_CONSULTANT_COMMISSION:
            comissao = CONSULTANT_COMMISSION_RATE * result['liquido']
            st.info(f"**Comissão estimada do consultor (~{int(CONSULTANT_COMMISSION_RATE*100)}%): R$ {format_br(comissao)}**")

        st.caption("⚠️ Os valores são aproximados e podem variar conforme a data da consulta e regras do FGTS.")

        # Registro no Sheets
        try:
            append_row_consulta(
                consultor=consultor.strip(),
                data_simul=result["data_simul"],
                data_nasc=data_nasc.strftime("%d/%m/%Y"),
                parcelas=int(parcelas),
                saldo=saldo,
                liquido=result["liquido"],
                tac_perc=TAC_FIXED,
            )
        except Exception as e:
            st.warning(f"Simulação OK, mas não foi possível registrar no Google Sheets agora.\n\nDetalhes: {e}")

    except Exception as e:
        st.error(f"Erro: {e}")
