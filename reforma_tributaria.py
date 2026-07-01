#!/usr/bin/env python3
"""
Reforma Tributária 2026 — Portfólio Livemode
Extrai projetos fechados do Airtable e calcula impacto tributário
por contrato, marca e empresa ao longo de 2026–2033.
"""

import os, json, re, pathlib, urllib.request, urllib.parse
from datetime import datetime, date

AIRTABLE_TOKEN = os.environ["AIRTABLE_TOKEN"]
BASE_ID        = "appm3CiLOmaJYRPuv"
ANO_HOJE       = date.today().year

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

def parse_anos(ini_str, fim_str, periodo_str):
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

# ── Main ──────────────────────────────────────────────────────────────────────
print(f"=== Reforma Tributária — Portfólio Livemode — {date.today()} ===")

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
    valor = float(f.get("Valor Total Líquido", 0) or 0)
    if valor <= 0:
        continue

    empresa  = classifica_empresa(f.get("Empresa", ""), nome)
    marca_ids = f.get("Marca", []) or []
    marca    = marcas.get(marca_ids[0], "—") if marca_ids else "—"
    ano_ini, ano_fim = parse_anos(
        f.get("Data de início (Período)", ""),
        f.get("Data de Término (Período)", ""),
        f.get("Período", ""),
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
