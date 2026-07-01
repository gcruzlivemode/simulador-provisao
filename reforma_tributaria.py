#!/usr/bin/env python3
"""
Reforma Tributária 2026 — Portfólio Livemode
Extrai projetos fechados do Airtable e calcula impacto tributário
por contrato, marca e empresa ao longo de 2026–2033.
Detecta mudanças vs. snapshot anterior e notifica via Slack e email.
"""

import os, json, re, pathlib, urllib.request, urllib.parse, smtplib
from datetime import datetime, date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

AIRTABLE_TOKEN = os.environ["AIRTABLE_TOKEN"]
BASE_ID        = "appm3CiLOmaJYRPuv"
ANO_HOJE       = date.today().year
CACHE_FILE     = pathlib.Path("reforma_cache.json")

ANOS = list(range(2026, 2034))

RATES = {
    2026: {"pis": .0165, "cof": .076,  "iss": .030, "cbs": .009, "ibs": .001, "confirmed": True},
    2027: {"pis": .000,  "cof": .000,  "iss": .030, "cbs": .088, "ibs": .001, "confirmed": False},
    2028: {"pis": .000,  "cof": .000,  "iss": .030, "cbs": .088, "ibs": .001, "confirmed": False},
    2029: {"pis": .000,  "cof": .000,  "iss": .027, "cbs": .088, "ibs": .032, "confirmed": False},
    2030: {"pis": .000,  "cof": .000,  "iss": .024, "cbs": .088, "ibs": .064, "confirmed": False},
    2031: {"pis": .000,  "cof": .000,  "iss": .021, "cbs": .088, "ibs": .096, "confirmed": False},
    2032: {"pis": .000,  "cof": .000,  "iss": .018, "cbs": .088, "ibs": .128, "confirmed": False},
    2033: {"pis": .000,  "cof": .000,  "iss": .000, "cbs": .088, "ibs": .177, "confirmed": False},
}
RATES_USD_PIS_COF = {y: (.0165 if y == 2026 else 0, .076 if y == 2026 else 0) for y in ANOS}

# ── Helpers ───────────────────────────────────────────────────────────────────

def airtable_get(table, params=None):
    records, offset = [], None
    while True:
        p = dict(params or {})
        if offset:
            p["offset"] = offset
        qs  = urllib.parse.urlencode(p, doseq=True)
        url = f"https://api.airtable.com/v0/{BASE_ID}/{urllib.parse.quote(table)}?{qs}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {AIRTABLE_TOKEN}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        records.extend(data.get("records", []))
        offset = data.get("offset")
        if not offset:
            break
    return records

def calcular_impacto(valor_brl, ano_ini, ano_fim, is_brl=True, irrf_pct=0.15):
    num_anos      = max(1, ano_fim - ano_ini + 1)
    valor_por_ano = valor_brl / num_anos
    resultado     = {}
    for ano in ANOS:
        if ano < ano_ini or ano > ano_fim:
            resultado[str(ano)] = None
            continue
        r = RATES[ano]
        v = valor_por_ano
        if is_brl:
            pis_v  = v * r["pis"]
            cof_v  = v * r["cof"]
            iss_v  = v * r["iss"]
            irrf_v = 0.0
        else:
            pis_pct, cof_pct = RATES_USD_PIS_COF[ano]
            pis_v  = v * pis_pct
            cof_v  = v * cof_pct
            iss_v  = v * r["iss"]
            irrf_v = v * irrf_pct
        cbs_v        = v * r["cbs"]
        ibs_v        = v * r["ibs"]
        cbs_efetiva  = 0.0 if ano == 2026 else cbs_v
        ibs_efetivo  = 0.0 if ano <= 2028  else ibs_v
        total_atual  = irrf_v + pis_v + cof_v + iss_v
        total_novo   = irrf_v + iss_v + cbs_efetiva + ibs_efetivo
        delta        = total_novo - total_atual
        resultado[str(ano)] = {
            "valor":       round(v, 2),
            "pis":         round(pis_v, 2),
            "cof":         round(cof_v, 2),
            "iss":         round(iss_v, 2),
            "irrf":        round(irrf_v, 2),
            "cbs":         round(cbs_v, 2),
            "ibs":         round(ibs_v, 2),
            "total_atual": round(total_atual, 2),
            "total_novo":  round(total_novo, 2),
            "delta":       round(delta, 2),
            "confirmed":   r["confirmed"],
        }
    return resultado

def parse_anos(ini_str, fim_str, periodo_str, nome_projeto=""):
    ano_ini = ano_fim = ANO_HOJE
    if ini_str:
        try: ano_ini = int(str(ini_str)[:4])
        except: pass
    if fim_str:
        try: ano_fim = int(str(fim_str)[:4])
        except: pass
    elif periodo_str:
        years = re.findall(r"\d{4}", str(periodo_str))
        if len(years) >= 2:
            ano_ini, ano_fim = int(years[0]), int(years[-1])
        elif len(years) == 1:
            ano_ini = ano_fim = int(years[0])
    # Fallback: extrai ano do nome do projeto (ex: "Aurora | Paulistão 2028")
    if ano_ini == ANO_HOJE and ano_fim == ANO_HOJE and nome_projeto:
        years_nome = re.findall(r"20[2-3]\d", nome_projeto)
        if years_nome:
            yr = int(years_nome[-1])
            if 2026 <= yr <= 2033:
                ano_ini = ano_fim = yr
    ano_ini = max(2026, min(2033, ano_ini))
    ano_fim = max(ano_ini, min(2033, ano_fim))
    return ano_ini, ano_fim

def classifica_empresa(empresa_raw, nome_projeto):
    e = (empresa_raw or "").upper()
    n = (nome_projeto or "").upper()
    if "CAZETV" in e or "CAZÉ" in e or "CAZE" in e:
        return "CZTV"
    if "CAZETV" in n or "CAZÉ" in n or "CASA CAZ" in n:
        return "CZTV"
    return "LMS"

def formata_brl(valor):
    return "R$ " + f"{valor:,.0f}".replace(",", ".")

# ── Notificações ──────────────────────────────────────────────────────────────

def notificar_slack(novos, cancelados, atualizados, total):
    token   = os.environ.get("SLACK_BOT_TOKEN")
    channel = os.environ.get("SLACK_CHANNEL_ID")
    if not token or not channel:
        print("[Slack] SLACK_BOT_TOKEN ou SLACK_CHANNEL_ID não configurado — pulando.")
        return

    hoje   = date.today().strftime("%d/%m/%Y")
    partes = [f":bell: *Reforma Tributária — Portfólio Atualizado* ({hoje})"]

    if novos:
        partes.append(f"\n:white_check_mark: *{len(novos)} novo(s) contrato(s) em Fechamento:*")
        for p in novos:
            partes.append(f"  • [{p['empresa']}] {p['nome']} — {formata_brl(p['valor_total'])}")

    if atualizados:
        partes.append(f"\n:pencil2: *{len(atualizados)} valor(es) atualizado(s):*")
        for ant, novo in atualizados:
            partes.append(
                f"  • [{novo['empresa']}] {novo['nome']}: "
                f"{formata_brl(ant['valor_total'])} → {formata_brl(novo['valor_total'])}"
            )

    if cancelados:
        partes.append(f"\n:x: *{len(cancelados)} contrato(s) saiu de Fechamento:*")
        for p in cancelados:
            partes.append(f"  • [{p['empresa']}] {p['nome']} — {formata_brl(p['valor_total'])}")

    partes.append(f"\n_Total no portfólio: {total} contrato(s) com valor_")
    partes.append("_Dashboard: https://gcruzlivemode.github.io/simulador-provisao/reforma.html_")

    body = json.dumps({"channel": channel, "text": "\n".join(partes)}).encode()
    req  = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read())
        print(f"[Slack] {'OK' if resp.get('ok') else 'ERRO: ' + resp.get('error', '?')}")
    except Exception as ex:
        print(f"[Slack] Erro ao enviar: {ex}")

def notificar_email(novos, cancelados, atualizados, total):
    host     = os.environ.get("SMTP_HOST")
    port     = int(os.environ.get("SMTP_PORT", "587"))
    user     = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASS")
    destino  = "gcruz@livemode.com"

    if not all([host, user, password]):
        print("[Email] SMTP_HOST/SMTP_USER/SMTP_PASS não configurados — pulando.")
        return

    hoje = date.today().strftime("%d/%m/%Y")
    rows = []

    if novos:
        rows.append(f"<h3 style='color:#27ae60'>✅ {len(novos)} Novo(s) Contrato(s) em Fechamento</h3><ul>")
        for p in novos:
            rows.append(
                f"<li>[{p['empresa']}] <strong>{p['nome']}</strong> — {formata_brl(p['valor_total'])}</li>"
            )
        rows.append("</ul>")

    if atualizados:
        rows.append(f"<h3 style='color:#2980b9'>✏️ {len(atualizados)} Valor(es) Atualizado(s)</h3><ul>")
        for ant, novo in atualizados:
            rows.append(
                f"<li>[{novo['empresa']}] <strong>{novo['nome']}</strong>: "
                f"{formata_brl(ant['valor_total'])} → <strong>{formata_brl(novo['valor_total'])}</strong></li>"
            )
        rows.append("</ul>")

    if cancelados:
        rows.append(f"<h3 style='color:#e74c3c'>❌ {len(cancelados)} Saiu de Fechamento</h3><ul>")
        for p in cancelados:
            rows.append(
                f"<li>[{p['empresa']}] <strong>{p['nome']}</strong> — {formata_brl(p['valor_total'])}</li>"
            )
        rows.append("</ul>")

    html = f"""
    <div style='font-family:Arial,sans-serif;max-width:600px;margin:0 auto'>
      <h2 style='color:#1a1a2e;border-bottom:2px solid #e8e8e8;padding-bottom:8px'>
        🔔 Reforma Tributária — Portfólio Atualizado
      </h2>
      <p style='color:#555'>{hoje} — Alterações detectadas nos contratos do Airtable.</p>
      {''.join(rows)}
      <hr style='border:none;border-top:1px solid #eee;margin:20px 0'>
      <p style='color:#888;font-size:12px'>
        Total no portfólio: {total} contrato(s) com valor declarado.<br>
        <a href='https://gcruzlivemode.github.io/simulador-provisao/reforma.html'
           style='color:#2980b9'>Abrir dashboard da Reforma Tributária →</a>
      </p>
    </div>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[Reforma Tributária] Portfólio atualizado — {hoje}"
    msg["From"]    = user
    msg["To"]      = destino
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        with smtplib.SMTP(host, port) as s:
            s.ehlo()
            s.starttls()
            s.login(user, password)
            s.sendmail(user, [destino], msg.as_string())
        print(f"[Email] Enviado para {destino}")
    except Exception as ex:
        print(f"[Email] Erro ao enviar: {ex}")

# ── Main ──────────────────────────────────────────────────────────────────────
print(f"=== Reforma Tributária — Portfólio Livemode — {date.today()} ===")

# Carregar snapshot anterior para detecção de mudanças
snapshot_anterior = {}
is_first_run      = True
if CACHE_FILE.exists():
    try:
        _c = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        snapshot_anterior = {p["id"]: p for p in _c.get("projetos", [])}
        is_first_run      = False
        print(f"[Cache] Snapshot anterior: {len(snapshot_anterior)} contratos.")
    except Exception as _e:
        print(f"[Cache] Erro ao ler cache: {_e}")

print("\n[Airtable] Buscando Marcas...")
marcas_recs = airtable_get("Marcas", {"fields[]": ["Marca"]})
marcas = {r["id"]: r["fields"].get("Marca", "—") for r in marcas_recs}
print(f"  {len(marcas)} marcas.")

print("\n[Airtable] Buscando Projetos fechados...")
projetos_recs = airtable_get("Projetos", {
    "filterByFormula": "Status='Fechamento'",
    "fields[]": [
        "Projeto", "Marca", "Empresa", "Valor Total Líquido",
        "Data de início (Período)", "Data de Término (Período)",
        "Período", "Faturamento será no Brasil ou no exterior?",
    ],
})
print(f"  {len(projetos_recs)} projetos encontrados.")

projetos_todos, por_empresa = [], {"LMS": [], "CZTV": []}

for rec in projetos_recs:
    f     = rec["fields"]
    nome  = f.get("Projeto", "—") or "—"
    if "ESTRELAS" in nome.upper():
        print(f"  [SKIP] {nome} — casting, ignorado.")
        continue
    valor = float(f.get("Valor Total Líquido", 0) or 0)
    if valor <= 0:
        continue

    empresa   = classifica_empresa(f.get("Empresa", ""), nome)
    marca_ids = f.get("Marca", []) or []
    marca     = marcas.get(marca_ids[0], "—") if marca_ids else "—"
    ano_ini, ano_fim = parse_anos(
        f.get("Data de início (Período)", ""),
        f.get("Data de Término (Período)", ""),
        f.get("Período", ""),
        nome,
    )
    fat    = (f.get("Faturamento será no Brasil ou no exterior?", "") or "").lower()
    is_brl = "exterior" not in fat

    impacto = calcular_impacto(valor, ano_ini, ano_fim, is_brl)

    proj = {
        "id":          rec["id"],
        "nome":        nome,
        "marca":       marca,
        "empresa":     empresa,
        "valor_total": round(valor, 2),
        "ano_ini":     ano_ini,
        "ano_fim":     ano_fim,
        "is_brl":      is_brl,
        "impacto":     impacto,
    }
    projetos_todos.append(proj)
    por_empresa[empresa].append(proj)
    print(f"  [{empresa}] {nome[:55]:55s} | R$ {valor:>12,.0f} | {ano_ini}–{ano_fim}")

print(f"\nTotal com valor: {len(projetos_todos)} | LMS: {len(por_empresa['LMS'])} | CZTV: {len(por_empresa['CZTV'])}")

# ── Detectar mudanças vs. snapshot anterior ───────────────────────────────────
snapshot_atual = {p["id"]: p for p in projetos_todos}

novos      = [p for p in projetos_todos if p["id"] not in snapshot_anterior]
cancelados = [p for id_, p in snapshot_anterior.items() if id_ not in snapshot_atual]
atualizados = []
for p in projetos_todos:
    if p["id"] in snapshot_anterior:
        ant = snapshot_anterior[p["id"]]
        if abs(p["valor_total"] - ant.get("valor_total", 0)) > 0.01:
            atualizados.append((ant, p))

mudancas = bool(novos or cancelados or atualizados)

if is_first_run:
    print(f"\n[Primeira run] Criando snapshot inicial com {len(projetos_todos)} contratos.")
elif mudancas:
    print(f"\n[Mudanças] Novos: {len(novos)} | Atualizados: {len(atualizados)} | Cancelados: {len(cancelados)}")
else:
    print("\n[Mudanças] Nenhuma alteração desde o último run.")

# Salvar snapshot atualizado
_cache_payload = {
    "gerado":   datetime.now().isoformat(),
    "projetos": [
        {"id": p["id"], "nome": p["nome"], "empresa": p["empresa"], "valor_total": p["valor_total"]}
        for p in projetos_todos
    ],
}
CACHE_FILE.write_text(json.dumps(_cache_payload, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"[Cache] Snapshot salvo: {len(projetos_todos)} contratos.")

# ── Notificar se houve mudanças (não notifica na primeira run) ────────────────
if mudancas and not is_first_run:
    print("\n[Notificações] Enviando alertas...")
    notificar_slack(novos, cancelados, atualizados, len(projetos_todos))
    notificar_email(novos, cancelados, atualizados, len(projetos_todos))

# ── Gerar HTML ────────────────────────────────────────────────────────────────
payload = {
    "gerado":         datetime.now().isoformat(),
    "anos":           ANOS,
    "rates":          {str(k): v for k, v in RATES.items()},
    "projetos":       projetos_todos,
    "lms":            por_empresa["LMS"],
    "cztv":           por_empresa["CZTV"],
    "total_projetos": len(projetos_todos),
}

tpl_path = pathlib.Path("reforma_tributaria_template.html")
if tpl_path.exists():
    tpl      = tpl_path.read_text(encoding="utf-8")
    html_out = tpl.replace("/*INJECT_DATA*/", json.dumps(payload, ensure_ascii=False))
    out      = pathlib.Path("REFORMA_TRIBUTARIA.html")
    out.write_text(html_out, encoding="utf-8")
    print(f"\n[OK] {out} gerado ({out.stat().st_size // 1024} KB).")
else:
    print("\n[AVISO] reforma_tributaria_template.html não encontrado.")

print("\n=== Concluído ===")
