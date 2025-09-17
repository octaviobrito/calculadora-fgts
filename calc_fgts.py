# calc_fgts.py — Calculadora Antecipação FGTS (Tkinter + máscara de data + Google Sheets opcional)
# Requisitos extras (só para o Sheets): pip install gspread oauth2client

import datetime as _dt
from pathlib import Path
import tkinter as tk
from tkinter import messagebox

# ========= CONFIG =========
MONTHLY_RATE = 0.0179     # 1,79% a.m.
IOF_RATE     = 0.0075     # ~0,75% simplificado
SHEET_NAME   = "Simulações FGTS"          # nome da planilha (aba 1)
BASE_DIR     = Path(__file__).resolve().parent
CREDS_FILE   = BASE_DIR / "credenciais.json"
# ==========================


# ---- Helpers de data: máscara + validação inteligente ----
def _format_date_mask(s: str) -> str:
    digits = "".join(ch for ch in s if ch.isdigit())[:8]  # ddmmaaaa
    out = ""
    for i, ch in enumerate(digits):
        if i in (2, 4):
            out += "/"
        out += ch
    return out

def _validate_date_parts(text: str):
    """
    Retorna (ok, msg). ok=True se:
      - tem 10 chars no formato dd/mm/aaaa
      - 01<=dia<=31, 01<=mes<=12, 1900<=ano<=2099
      - e a data existir no calendário (strptime valida 29/02, etc.)
    """
    if len(text) != 10 or text[2] != "/" or text[5] != "/":
        return False, "Use o formato dd/mm/aaaa."
    dd, mm, yyyy = text[:2], text[3:5], text[6:]
    if not (dd.isdigit() and mm.isdigit() and yyyy.isdigit()):
        return False, "Use apenas números."
    d, m, y = int(dd), int(mm), int(yyyy)
    if not (1 <= d <= 31):
        return False, "Dia deve ser entre 01 e 31."
    if not (1 <= m <= 12):
        return False, "Mês deve ser entre 01 e 12."
    if not (1900 <= y <= 2099):
        return False, "Ano deve ser entre 1900 e 2099."
    # valida calendário real (ex.: 31/02 inválido)
    import datetime as _dt
    try:
        _dt.date(y, m, d)
    except ValueError:
        return False, "Data inválida para esse mês/ano."
    return True, ""

def _bind_date_mask(entry: tk.Entry):
    # cores para feedback
    COLOR_OK = "white"
    COLOR_BAD = "#ffecec"

    def normalize_partial(text: str) -> str:
        """Aplica máscara e corrige limites parciais (01–31 / 01–12) enquanto digita."""
        masked = _format_date_mask(text)
        # análise por partes mesmo que incompleto
        parts = masked.split("/")
        # corrige DD
        if len(parts) >= 1 and len(parts[0]) >= 1:
            d1 = parts[0][0]
            if d1 > "3":  # primeira dezena do dia não pode ser 4–9
                parts[0] = "3" + parts[0][1:] if len(parts[0]) > 1 else "3"
        if len(parts) >= 1 and len(parts[0]) == 2:
            d = int(parts[0])
            if d == 0:
                parts[0] = "01"
            elif d > 31:
                parts[0] = "31"
        # corrige MM
        if len(parts) >= 2 and len(parts[1]) >= 1:
            m1 = parts[1][0]
            if m1 > "1":  # primeira dezena do mês não pode ser 2–9
                parts[1] = "1" + parts[1][1:] if len(parts[1]) > 1 else "1"
        if len(parts) >= 2 and len(parts[1]) == 2:
            m = int(parts[1])
            if m == 0:
                parts[1] = "01"
            elif m > 12:
                parts[1] = "12"
        # reconstrói com barras
        masked = ""
        if len(parts) >= 1:
            masked += parts[0][:2]
        if len(parts) >= 2:
            masked += "/" + parts[1][:2]
        if len(parts) >= 3:
            masked += "/" + parts[2][:4]
        return masked[:10]

    def refresh(event=None):
        cur = entry.get()
        fmt = normalize_partial(cur)
        if cur != fmt:
            entry.delete(0, tk.END)
            entry.insert(0, fmt)
        # feedback de validade parcial
        ok, _ = _validate_date_parts(fmt) if len(fmt) == 10 else (False, "")
        entry.config(bg=COLOR_OK if ok else COLOR_BAD)
        # cursor sempre no final
        entry.icursor(tk.END)

    def on_paste(event=None):
        entry.after(1, refresh)

    def on_focus_out(event=None):
        text = entry.get()
        ok, msg = _validate_date_parts(text)
        if not ok and text:
            # mantém vermelho e alerta
            entry.config(bg=COLOR_BAD)
            messagebox.showerror("Data inválida", msg)

    # só permite dígitos e '/'
    def on_validate(proposed):
        return all(ch.isdigit() or ch == "/" for ch in proposed) and len(proposed) <= 10

    vcmd = (entry.register(on_validate), "%P")
    entry.config(validate="key", validatecommand=vcmd)
    entry.bind("<KeyRelease>", refresh)
    entry.bind("<<Paste>>", on_paste)
    entry.bind("<FocusOut>", on_focus_out)


# ------- Regras do saque-aniversário (alíquota + parcela adicional) -------
def saque_aniversario(saldo: float) -> float:
    if saldo <= 0:
        return 0.0
    if saldo <= 500:
        return 0.50 * saldo
    elif saldo <= 1000:
        return 0.40 * saldo + 50
    elif saldo <= 5000:
        return 0.30 * saldo + 150
    elif saldo <= 10000:
        return 0.20 * saldo + 650
    elif saldo <= 15000:
        return 0.15 * saldo + 1150
    elif saldo <= 20000:
        return 0.10 * saldo + 1900
    else:
        return 0.05 * saldo + 2900


def meses_ate_proximo_aniversario(nasc: _dt.date, ref: _dt.date) -> int:
    """Retorna quantos meses (aprox.) faltam até o próximo aniversário a partir de ref."""
    ano = ref.year
    # usa dia 28 para evitar problema em 29/30/31 (fevereiro etc.)
    prox = _dt.date(ano, nasc.month, min(nasc.day, 28))
    if prox < ref:
        prox = _dt.date(ano + 1, nasc.month, min(nasc.day, 28))
    anos_diff = prox.year - ref.year
    meses = anos_diff * 12 + (prox.month - ref.month)
    if prox.day < ref.day:
        meses -= 1
    return max(meses, 0)


def format_br(v: float) -> str:
    """Formata número no estilo BR (milhar . e decimal ,) sem locale."""
    s = f"{v:,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


# ------------------ Lógica principal de cálculo ------------------
def simular(data_nasc: str, data_simul: str, n_parcelas: int, saldo_inicial: float, tac_percent: float):
    nasc = _dt.datetime.strptime(data_nasc, "%d/%m/%Y").date()
    simul = _dt.datetime.strptime(data_simul, "%d/%m/%Y").date()

    if not (2 <= n_parcelas <= 10):
        raise ValueError("Número de parcelas deve estar entre 2 e 10.")
    if saldo_inicial <= 0:
        raise ValueError("Saldo FGTS deve ser maior que zero.")
    if tac_percent < 0:
        raise ValueError("TAC não pode ser negativa.")

    # 1) calcula saques anuais projetados
    saldo = float(saldo_inicial)
    saques = []
    for _ in range(n_parcelas):
        s = saque_aniversario(saldo)
        s = max(0.0, min(s, saldo))  # nunca saque mais que o saldo
        saques.append(s)
        saldo -= s
        if saldo <= 0:
            saques += [0.0] * (n_parcelas - len(saques))
            break

    # 2) meses até cada parcela
    m0 = meses_ate_proximo_aniversario(nasc, simul)
    meses_list = [m0 + 12 * i for i in range(n_parcelas)]

    # 3) valor presente de cada parcela
    vps = []
    for saque, meses in zip(saques, meses_list):
        vp = saque if meses <= 0 else saque / ((1 + MONTHLY_RATE) ** meses)
        vps.append(vp)

    vp_total = sum(vps)

    # 4) IOF simplificado e 5) TAC
    iof_val = IOF_RATE * vp_total
    apos_iof = vp_total - iof_val
    tac_val = (tac_percent / 100.0) * apos_iof
    liquido = apos_iof - tac_val

    rel = []
    rel.append("=== Simulação de Antecipação FGTS ===")
    rel.append(f"Data Nasc.: {data_nasc}    Data Simulação: {data_simul}")
    rel.append(f"Parcelas antecipadas: {n_parcelas}")
    rel.append(f"Saldo FGTS considerado: R$ {format_br(saldo_inicial)}\n")
    rel.append("Detalhamento dos saques por ano:")
    for i, s in enumerate(saques, start=1):
        rel.append(f"  Parcela {i}: R$ {format_br(s)}  (em ~{meses_list[i-1]} meses)")
    rel.append("")
    rel.append(f"Valor Presente Total: R$ {format_br(vp_total)}")
    rel.append(f"IOF (~0,75%):        R$ {format_br(iof_val)}")
    rel.append(f"TAC ({tac_percent:.2f}%):       R$ {format_br(tac_val)}\n")
    rel.append(f">> VALOR LÍQUIDO AO CLIENTE: R$ {format_br(liquido)} <<")

    return {
        "saques": saques,
        "meses": meses_list,
        "vp_total": vp_total,
        "iof": iof_val,
        "tac": tac_val,
        "liquido": liquido,
        "relatorio": "\n".join(rel)
    }


# -------- Integração com Google Sheets (opcional) --------
def _salvar_planilha(vendedor, data_simul, data_nasc, parcelas, saldo, tac_perc, valor_liquido):
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials
    import getpass
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name(str(CREDS_FILE), scope)
    client = gspread.authorize(creds)
    sh = client.open(SHEET_NAME)
    ws = sh.sheet1

    # Garante cabeçalho padrão (A–I) na primeira linha
    header = ws.row_values(1)
    header_expected = [
        "Data Simulação", "Vendedor", "Data Nasc.", "Parcelas antecipadas",
        "Saldo FGTS considerado", "TAC", "Valor Líquido ao Cliente",
        "Data e hora da consulta", "WindowsUser"
    ]
    if header != header_expected:
        # sobrescreve cabeçalho (não mexe nas linhas antigas)
        if header:
            ws.update("A1:I1", [header_expected])
        else:
            ws.insert_row(header_expected, 1)

    windows_user = ""
    try:
        import os
        windows_user = os.getlogin()
    except Exception:
        try:
            windows_user = getpass.getuser()
        except Exception:
            windows_user = ""

    linha = [
        data_simul,
        vendedor or "",
        data_nasc,
        str(parcelas),
        f"{saldo:.2f}",
        f"{tac_perc:.2f}%",
        f"{valor_liquido:.2f}",
        _dt.datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        windows_user,
    ]
    ws.append_row(linha)


# ------------------ UI (Tkinter) ------------------
def main():
    root = tk.Tk()
    root.title("Calculadora Antecipação FGTS")
    root.geometry("700x600+120+120")

    # garantir visibilidade (se vier minimizada/atrás)
    root.update_idletasks()
    root.deiconify()
    root.state('normal')
    root.attributes('-topmost', True)
    root.after(1200, lambda: root.attributes('-topmost', False))
    root.lift()
    try:
        root.focus_force()
    except:
        pass

    frm = tk.Frame(root)
    frm.pack(padx=16, pady=12, fill="x")

    tk.Label(frm, text="Data de Nascimento (dd/mm/aaaa)").grid(row=0, column=0, sticky="w")
    ent_nasc = tk.Entry(frm)
    ent_nasc.grid(row=1, column=0, sticky="we", padx=(0,10))
    _bind_date_mask(ent_nasc)  # << máscara aplicada

    tk.Label(frm, text="Data da Simulação (dd/mm/aaaa)").grid(row=0, column=1, sticky="w")
    ent_simul = tk.Entry(frm)
    ent_simul.grid(row=1, column=1, sticky="we")
    ent_simul.insert(0, _dt.date.today().strftime("%d/%m/%Y"))
    _bind_date_mask(ent_simul)  # << máscara aplicada

    tk.Label(frm, text="Nº parcelas (2 a 10)").grid(row=2, column=0, sticky="w", pady=(10,0))
    spn_parc = tk.Spinbox(frm, from_=2, to=10, width=6)
    spn_parc.grid(row=3, column=0, sticky="w", padx=(0,10))

    tk.Label(frm, text="Saldo FGTS (R$)").grid(row=2, column=1, sticky="w", pady=(10,0))
    ent_saldo = tk.Entry(frm)
    ent_saldo.grid(row=3, column=1, sticky="we")

    tk.Label(frm, text="TAC (%)").grid(row=4, column=0, sticky="w", pady=(10,0))
    ent_tac = tk.Entry(frm)
    ent_tac.grid(row=5, column=0, sticky="we", padx=(0,10))

    frm.columnconfigure(0, weight=1)
    frm.columnconfigure(1, weight=1)

    txt = tk.Text(root, height=18, wrap="word")
    txt.pack(padx=16, pady=12, fill="both", expand=True)

    save_var = tk.IntVar(value=1)

    def limpar():
        txt.delete("1.0", "end")

    def calcular_click():
        try:
            nasc = ent_nasc.get().strip()
            simul = ent_simul.get().strip()
            parcelas = int(spn_parc.get())
            saldo = float(ent_saldo.get().strip().replace(".", "").replace(",", "."))  # aceita 1.234,56
            tac = float(ent_tac.get().strip().replace(",", "."))
            r = simular(nasc, simul, parcelas, saldo, tac)
            limpar()
            txt.insert("end", r["relatorio"])
            if save_var.get() == 1:
                try:
                    _salvar_planilha(vendedor="",                    # versão principal não pede vendedor
				     data_simul=simul,
       				     data_nasc=nasc,
        			     parcelas=parcelas,
        			     saldo=saldo,
        			     tac_perc=tac,                   # TAC da UI
        			     valor_liquido=r["liquido"])
                except Exception as ee:
                    messagebox.showwarning(
                        "Aviso",
                        "Não foi possível registrar no Google Sheets agora.\n"
                        f"Detalhes: {ee}\n\n"
                        "A simulação foi calculada normalmente."
                    )
        except Exception as e:
            messagebox.showerror("Erro de entrada", str(e))

    btns = tk.Frame(root)
    btns.pack(padx=16, pady=(4,16), fill="x")
    tk.Button(btns, text="Calcular", command=calcular_click, width=14).pack(side="left")
    tk.Button(btns, text="Limpar", command=limpar, width=10).pack(side="left", padx=6)
    tk.Button(btns, text="Fechar", command=root.destroy, width=10).pack(side="right")

    root.mainloop()


if __name__ == "__main__":
    main()
