"""Self-contained report; never embeds raw CSV rows."""

from __future__ import annotations

from html import escape


def _e(value: object) -> str:
    return escape(str(value), quote=True)


def _percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def _feature_card(item: dict, thresholds: dict) -> str:
    score = item["score"]
    label = "Numeric distribution" if item["kind"] == "numeric" else "Category distribution"
    score_text = "Needs more rows" if score is None else f"{score:.3f}"
    threshold = thresholds[item["score_name"]]
    width = 0 if score is None else min(100, score / threshold * 50)
    extras = (f"Median {item['median_before']:,} → {item['median_after']:,}"
              if item["kind"] == "numeric" and score is not None else
              f"{item.get('categories', '—')} categories · {item.get('new_categories', '—')} new")
    alert_labels = []
    if "missing_delta" in item["alerts"]:
        alert_labels.append(f"Missing-rate change {_percent(item['missing_delta'])} ≥ {_percent(thresholds['missing_delta'])} limit")
    if item["score_name"] in item["alerts"]:
        alert_labels.append(f"Distribution score {item['score']:.6f} ≥ {threshold:.6f} limit")
    alert_text = " · ".join(alert_labels) or (f"Needs at least {item['min_required']} nonmissing rows in each snapshot"
                                               if score is None else "Within configured thresholds")
    pill = "alert" if item["alerts"] else "review" if score is None else "pass"
    pill_text = "ALERT" if item["alerts"] else "NEEDS DATA" if score is None else "PASS"
    return f'''<article class="feature {'is-alert' if item['alerts'] else ''}">
      <div class="feature-top"><div><span class="label">{_e(label)}</span><h4>{_e(item['feature'])}</h4></div><span class="pill {pill}">{pill_text}</span></div>
      <div class="score"><strong>{_e(score_text)}</strong><span>{_e(item['score_name'])} · alert at ≥ {_e(threshold)}</span></div>
      <div class="track"><span style="width:{width:.1f}%"></span><i></i></div>
      <div class="details"><span>{_e(extras)}</span><span>Missing {_percent(item['missing_before'])} → {_percent(item['missing_after'])}</span><span>Nonmissing {item['before_count']:,} → {item['after_count']:,}</span></div>
      <p>{_e(alert_text)}</p>
    </article>'''


def _section(title: str, subtitle: str, items: list[dict], thresholds: dict) -> str:
    cards = "".join(_feature_card(item, thresholds) for item in items)
    return f'''<section class="feature-section"><div class="section-head"><div><span class="eyebrow">{_e(subtitle)}</span><h3>{_e(title)}</h3></div><span>{len(items)} features</span></div><div class="feature-grid">{cards or '<p class="muted">No configured features could be compared.</p>'}</div></section>'''


def render_html(report: dict) -> str:
    summary = report["summary"]
    thresholds = report["config"]["thresholds"]
    schema = report["schema"]
    schema_items = []
    for key, label in (("removed_columns", "Removed"), ("added_columns", "Added"),
                       ("missing_configured_features", "Configured feature unavailable")):
        schema_items.extend(f"<li><b>{_e(label)}</b><code>{_e(name)}</code></li>" for name in schema[key])
    if schema.get("segment_column_missing"):
        schema_items.append(f"<li><b>Segment column unavailable</b><code>{_e(schema['segment_column_missing'])}</code></li>")
    schema_html = f"<ul>{''.join(schema_items)}</ul>" if schema_items else "<p class='clean'>No column changes found.</p>"
    segment_missing = report.get("segment_missing")
    if segment_missing:
        coverage_html = (f"<p><b>Missing cohort labels:</b> {_percent(segment_missing['before'])} → "
                         f"{_percent(segment_missing['after'])}"
                         f"{' · ALERT' if segment_missing['alert'] else ' · within threshold'}</p>")
    else:
        coverage_html = "<p>No segment column configured or available.</p>"
    segment_html = "".join(
        _section(f"{segment['name']} · {segment['before_count']:,} → {segment['after_count']:,} rows",
                 f"COHORT / {segment['status'].replace('_', ' ').upper()}", segment["features"], thresholds)
        if segment["status"] == "compared" else
        f"<section class='small-note'><b>{_e(segment['name'])}</b> · {segment['before_count']:,} → {segment['after_count']:,} rows · {'new or removed cohort: alert' if not segment['before_count'] or not segment['after_count'] else 'too few rows: review needed'}</section>"
        for segment in report["segments"])
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="DriftLedger: reproducible feature-distribution comparison and dataset release evidence."><title>DriftLedger · Dataset release report</title>
<style>
:root{{font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;background:#0c121b;color:#e9f0f8}}*{{box-sizing:border-box}}body{{margin:0}}.wrap{{max-width:1160px;margin:auto;padding:0 28px}}header{{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #334151;padding:23px 0}}header strong{{font-size:21px;letter-spacing:-.06em}}header span,.eyebrow,.label{{color:#95cce7;font:11px ui-monospace,SFMono-Regular,monospace;letter-spacing:.14em;text-transform:uppercase}}main{{padding:70px 0 90px}}h1{{font-size:clamp(43px,6vw,76px);line-height:1.02;letter-spacing:-.07em;margin:14px 0 19px;max-width:830px}}.intro{{color:#b8c8d8;line-height:1.7;max-width:740px}}.hero{{display:grid;grid-template-columns:1.5fr .5fr;gap:40px;align-items:end}}.seal{{padding:24px;border:1px solid #53717a;border-radius:16px;background:#152631}}.seal b{{font-size:32px;display:block;margin:7px 0}}.seal small{{color:#b8c8d8;line-height:1.5;display:block}}.stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:49px 0 68px}}.stat,.panel,.feature,.small-note{{border:1px solid #334151;border-radius:16px;background:#172431;padding:22px}}.stat span,.stat small{{display:block;color:#b9c8d7;font-size:12px}}.stat strong{{font-size:37px;display:block;letter-spacing:-.06em;margin:10px 0 2px}}.panels{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:55px}}.panel h2,.section-head h3{{font-size:26px;letter-spacing:-.045em;margin:0 0 15px}}.panel p{{color:#b8c8d8;line-height:1.6}}.panel ul{{list-style:none;padding:0;margin:0;display:grid;gap:10px}}.panel li{{display:flex;justify-content:space-between;gap:10px;border-top:1px solid #334151;padding-top:10px}}code{{font:12px ui-monospace,monospace;color:#dbe9ef}}.clean{{color:#a7edca!important}}.feature-section{{margin:45px 0}}.section-head{{display:flex;justify-content:space-between;align-items:end;gap:20px;border-bottom:1px solid #334151;padding-bottom:12px;margin-bottom:20px}}.section-head h3{{margin:9px 0 0}}.section-head>span{{font-size:12px;color:#aebdcd}}.feature-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:15px}}.feature-top{{display:flex;justify-content:space-between;align-items:start;gap:10px}}.feature h4{{font-size:20px;margin:8px 0 0;letter-spacing:-.03em}}.pill{{border-radius:99px;padding:6px 10px;font-size:11px;text-transform:uppercase;white-space:nowrap}}.pill.alert{{color:#ffd2ae;background:#704631}}.pill.pass{{color:#a7edca;background:#244839}}.pill.review{{color:#ffe8a7;background:#5c4b26}}.score{{display:flex;justify-content:space-between;align-items:baseline;gap:10px;margin:24px 0 10px}}.score strong{{font-size:29px;letter-spacing:-.05em}}.score span{{color:#abbecd;font-size:11px;text-align:right}}.track{{height:7px;border-radius:8px;background:#30475a;position:relative;overflow:visible}}.track span{{display:block;height:7px;border-radius:8px;background:#8ccfe8}}.is-alert .track span{{background:#f0ad79}}.track i{{position:absolute;left:50%;top:-4px;height:15px;width:2px;background:#d7e9ee}}.details{{display:flex;flex-wrap:wrap;gap:7px;margin-top:17px}}.details span{{color:#b8c8d8;font-size:11px;border:1px solid #405365;border-radius:7px;padding:5px 7px}}.feature p{{font:11px ui-monospace,monospace;color:#a9bed0;margin:17px 0 0}}.small-note{{margin:15px 0;color:#b8c8d8}}.notice{{border-left:3px solid #8ccfe8;padding:4px 0 4px 18px;color:#b7c8d7;line-height:1.65;margin-top:55px}}footer{{border-top:1px solid #334151;color:#94aaba;font-size:12px;padding:25px 0 50px}}a{{color:#a7e2fb}}a:focus-visible{{outline:3px solid #a7e2fb;outline-offset:4px}}@media(max-width:780px){{.wrap{{padding:0 18px}}.hero,.panels,.feature-grid{{grid-template-columns:1fr}}.stats{{grid-template-columns:repeat(2,1fr)}}main{{padding-top:45px}}.score{{display:block}}.score span{{display:block;text-align:left}}}}
</style></head><body><div class="wrap"><header><strong>driftledger<span style="color:#95cce7">✳</span></strong><span>DATASET RELEASE EVIDENCE / V1</span></header><main>
<div class="hero"><div><span class="eyebrow">BASELINE → CANDIDATE</span><h1>{'Review the shift before you ship.' if summary['alerts'] else 'Checked. No configured alerts.'}</h1><p class="intro">Feature distributions, missing values, schema changes, and cohort coverage in one reproducible comparison. Scores are screening signals tied to explicit thresholds, not proof that model quality changed.</p></div><div class="seal"><span class="eyebrow">RELEASE GATE</span><b>{'REVIEW' if summary['alerts'] else 'PASS'}</b><small>{summary['alerts']} alert(s) · {summary['reviews']} item(s) needing more data</small></div></div>
<div class="stats"><div class="stat"><span>Reference rows</span><strong>{report['reference']['rows']:,}</strong><small>SHA-256 recorded in JSON</small></div><div class="stat"><span>Current rows</span><strong>{report['current']['rows']:,}</strong><small>SHA-256 recorded in JSON</small></div><div class="stat"><span>Feature alerts</span><strong>{summary['score_alerts']}</strong><small>Global + eligible cohorts</small></div><div class="stat"><span>Cohorts</span><strong>{len(report['segments'])}</strong><small>{_e(report['config']['segment_by'] or 'not configured')}</small></div></div>
<div class="panels"><section class="panel"><h2>Schema checks</h2>{schema_html}{coverage_html}</section><section class="panel"><h2>Interpretation</h2><p><b>Numeric TV</b> compares reference-quantile histograms; <b>categorical JS</b> compares observed category frequencies in bits. Missingness is checked separately. A threshold crossing means investigate, not that the candidate data is wrong.</p></section></div>
{_section('Whole dataset', 'GLOBAL VIEW', report['global'], thresholds)}{segment_html}
<p class="notice"><b>Read the limits.</b> These descriptive scores do not measure model accuracy, fairness, causality, or statistical significance. Small cohorts are marked for review; they are not silently counted as passing. The bundled example uses synthetic data. Reports omit raw rows but may reveal column and cohort names or aggregate values. Review before publishing.</p></main><footer>DriftLedger · Deterministic comparison with recorded input hashes · <a href="report.json">Download machine-readable evidence ↗</a></footer></div></body></html>'''
