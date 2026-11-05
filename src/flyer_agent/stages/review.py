"""Static review.html for Gate 1 (data) and Gate 2 (content). No server needed."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from jinja2 import Template

from ..core.models import ContentPack, FlyerData
from ..core.placeholders import day_month, eur

if TYPE_CHECKING:
    from .pipeline import Run

PAGE = Template(autoescape=True, source="""<!doctype html><html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Revisione · {{ data.title }}</title><style>
:root{--navy:#015176;--yellow:#FED061;--tint:#E6EEF2;--red:#B42318;--amber:#B54708;--ink:#0F2A3A}
*{box-sizing:border-box}body{margin:0;font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:var(--ink);background:#F6F9FB}
header{background:var(--navy);color:#fff;padding:20px 28px;display:flex;gap:24px;align-items:center;flex-wrap:wrap}
header h1{font-size:20px;margin:0}header .st{background:var(--yellow);color:var(--navy);padding:4px 10px;border-radius:99px;font-weight:700;font-size:13px}
main{max-width:1400px;margin:0 auto;padding:24px}h2{color:var(--navy);margin:32px 0 12px}
.cards{display:flex;gap:12px;flex-wrap:wrap}.kpi{background:#fff;border-radius:10px;padding:14px 18px;min-width:150px;box-shadow:0 1px 2px #0001}
.kpi b{display:block;font-size:24px;color:var(--navy)}
.tablewrap{overflow-x:auto;background:#fff;border-radius:10px;box-shadow:0 1px 2px #0001}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:8px 10px;border-bottom:1px solid #E4EBF0;text-align:left;vertical-align:top}
th{background:var(--tint);color:var(--navy);position:sticky;top:0}td.n{text-align:right;white-space:nowrap}
.tag{display:inline-block;padding:1px 7px;border-radius:99px;font-size:12px;font-weight:600;margin:1px}
.t-med{background:#FDE8E8;color:var(--red)}.t-my{background:var(--navy);color:var(--yellow)}.t-hero{background:var(--yellow);color:var(--navy)}
.blocking{color:var(--red);font-weight:700}.warning{color:var(--amber);font-weight:600}.review{color:var(--navy);font-weight:600}
ul.issues{background:#fff;border-radius:10px;padding:14px 32px;box-shadow:0 1px 2px #0001}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:18px}
.item{background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 1px 2px #0001;display:flex;flex-direction:column}
.item img{width:100%;display:block;background:var(--tint)}.item .b{padding:12px 14px;font-size:13.5px}
.item .meta{color:#5B7383;font-size:12px;margin-bottom:6px}.item .cap{white-space:pre-wrap}.item .disc{color:#5B7383;font-size:12px;margin-top:8px}
.screens{grid-template-columns:repeat(auto-fill,minmax(420px,1fr))}
code{background:var(--tint);padding:2px 6px;border-radius:4px}
</style></head><body>
<header><h1>{{ data.title }} · {{ period }}</h1><span class="st">{{ manifest.state }}</span>
<span>run <code style="color:var(--navy)">{{ run_id }}</code></span><span>costo AI €{{ '%.3f'|format(manifest.cost_eur) }}</span></header>
<main>
<div class="cards">
<div class="kpi"><b>{{ data.products|length }}</b>prodotti</div>
<div class="kpi"><b>{{ data.products|selectattr('is_medicine')|list|length }}</b>farmaci</div>
<div class="kpi"><b>{{ data.promotions|length }}</b>promozioni</div>
<div class="kpi"><b>{{ data.services|length }}</b>servizi</div>
<div class="kpi"><b>{{ issues|selectattr('severity','equalto','blocking')|list|length }}</b>bloccanti</div>
{% if pack %}<div class="kpi"><b>{{ pack.posts|length }}</b>post + storie</div><div class="kpi"><b>{{ pack.screens|length }}</b>schermi</div>{% endif %}
</div>

{% if pack %}
<h2>Gate 2 · Contenuti</h2>
{% if pack.compliance.issues %}<ul class="issues">{% for i in pack.compliance.issues %}<li><span class="{{ i.severity }}">{{ i.severity }}</span> · <code>{{ i.target }}</code> · {{ i.message }}</li>{% endfor %}</ul>{% endif %}
<p>Approva con <code>flyer approve-pack</code> · rigenera un post con <code>flyer regen --item post-03 --note "..."</code></p>
<div class="grid">{% for p in pack.posts %}<div class="item">
{% if p.image_path %}<img src="{{ p.image_path }}" loading="lazy" alt="{{ p.spec.id }}">{% endif %}
<div class="b"><div class="meta">{{ p.spec.id }} · {{ p.spec.publish_date }} · {{ p.spec.kind }} · {{ p.spec.topic }}</div>
<div class="cap">{{ p.caption_final or '⚠ ' ~ p.copy_.caption }}</div>
{% if p.copy_.hashtags %}<div class="meta" style="margin-top:6px">{{ p.copy_.hashtags|join(' ') }}</div>{% endif %}
{% if p.disclaimers %}<div class="disc">{{ p.disclaimers|join(' · ') }}</div>{% endif %}</div></div>{% endfor %}</div>
<h2>Schermi in farmacia</h2>
<div class="grid screens">{% for s in pack.screens %}<div class="item">{% if s.image_path %}<img src="{{ s.image_path }}" loading="lazy" alt="{{ s.spec.id }}">{% endif %}
<div class="b"><div class="meta">{{ s.spec.id }} · {{ s.headline }}</div></div></div>{% endfor %}</div>
{% endif %}

<h2>Gate 1 · Dati estratti dal volantino</h2>
{% if issues %}<ul class="issues">{% for i in issues %}<li><span class="{{ i.severity }}">{{ i.severity }}</span> · <code>{{ i.target }}</code> · {{ i.message }}</li>{% endfor %}</ul>{% endif %}
<p>Correggi <code>flyer_data.json</code> se serve, poi <code>flyer validate</code> e <code>flyer approve-data</code>.</p>
<div class="tablewrap"><table><thead><tr><th>pag.</th><th>prodotto</th><th>formato</th><th>categoria</th><th>tipo</th><th class="n">prima</th><th class="n">ora</th><th class="n">sconto</th><th>badge</th></tr></thead><tbody>
{% for p in data.products %}<tr><td>{{ p.page }}</td><td><b>{{ p.name }}</b>{% if p.description %}<br><small>{{ p.description }}</small>{% endif %}</td>
<td>{{ p.format or '' }}</td><td>{{ p.flyer_category }}</td><td>{{ p.product_type }}</td>
<td class="n">{{ fmt(p.price.previous_eur) if p.price.previous_eur else '' }}</td><td class="n"><b>{{ fmt(p.price.current_eur) }}</b></td>
<td class="n">{{ ('-' ~ p.price.discount_pct ~ '%') if p.price.discount_pct else '' }}</td>
<td>{% if p.is_medicine %}<span class="tag t-med">farmaco</span>{% endif %}{% if p.my_agora_only %}<span class="tag t-my">My Agorà</span>{% endif %}{% if p.hero %}<span class="tag t-hero">imperdibile</span>{% endif %}{% if p.price_group %}<span class="tag">gruppo {{ p.price_group }}</span>{% endif %}</td></tr>{% endfor %}
</tbody></table></div>
{% if data.promotions %}<h2>Promozioni</h2><ul class="issues">{% for p in data.promotions %}<li><b>{{ p.title }}</b> · {{ p.scope }} · {{ p.tiers|map(attribute='value')|join(', ') }}</li>{% endfor %}</ul>{% endif %}
{% if data.services %}<h2>Servizi</h2><ul class="issues">{% for s in data.services %}<li><b>{{ s.title }}</b>{% if s.price_eur %} · {{ fmt(s.price_eur) }}{% endif %}{% if s.valid_to %} · fino al {{ dm(s.valid_to) }}{% endif %} · {{ s.items|join(', ') }}</li>{% endfor %}</ul>{% endif %}
{% if data.loyalty %}<h2>Carta My Agorà</h2><ul class="issues"><li>{{ fmt(data.loyalty.reward_eur) }} ogni {{ fmt(data.loyalty.every_eur) }} di spesa{% if data.loyalty.exclusions %} · esclusi: {{ data.loyalty.exclusions|join(', ') }}{% endif %}</li></ul>{% endif %}
</main></body></html>""")


def build_review(run: Run) -> None:
    data = run.load("flyer_data.json", FlyerData)
    issues_path = run.path("validation.json")
    from ..core.models import Issue
    issues = [Issue(**i) for i in json.loads(issues_path.read_text())] if issues_path.exists() else []
    pack = run.load("content_pack.json", ContentPack) if run.path("content_pack.json").exists() else None
    html = PAGE.render(data=data, issues=issues, pack=pack, manifest=run.manifest, run_id=run.id, fmt=eur,
                       dm=day_month, period=f"{day_month(data.valid_from)} – {day_month(data.valid_to)} {data.valid_to.year}")
    run.path("review.html").write_text(html, encoding="utf-8")
