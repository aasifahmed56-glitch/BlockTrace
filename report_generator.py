import os
import re
from datetime import datetime
from dotenv import load_dotenv
from neo4j import GraphDatabase
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

from logic import (
    short, risk_tier, compute_wallet_risk, build_narrative, check_sanctions, get_entity_label
)

load_dotenv()

NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USER = os.getenv("NEO4J_USER")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE")

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

# BlockTrace brand colors (matching the dashboard/Stitch UI)
BRAND_ORANGE = colors.HexColor('#FF6D1F')
BRAND_BLACK = colors.HexColor('#222222')
BRAND_RED = colors.HexColor('#D62839')
BRAND_GREEN = colors.HexColor('#4C8C4A')
BRAND_BLUE = colors.HexColor('#2E6F95')
BRAND_VIOLET = colors.HexColor('#6B4E8E')
BRAND_CREAM = colors.HexColor('#F5E7C6')
BRAND_MUTED = colors.HexColor('#6B6255')


def get_summary_stats(session):
    result = session.run(
        "MATCH (w:Wallet) OPTIONAL MATCH (w)-[r:SENT]->() RETURN count(DISTINCT w) AS wallets, count(r) AS txs"
    )
    record = result.single()
    return record["wallets"], record["txs"]


def get_hub_wallets(session, top_n=10):
    result = session.run(
        """
        MATCH (w:Wallet)-[r:SENT]-()
        RETURN w.address AS wallet, count(r) AS total_txs
        ORDER BY total_txs DESC LIMIT $top_n
        """, top_n=top_n
    )
    return [(r["wallet"], r["total_txs"]) for r in result]


def get_fanout_wallets(session, min_recipients=4):
    result = session.run(
        """
        MATCH (a:Wallet)-[:SENT]->(b:Wallet)
        WITH a, count(DISTINCT b) AS distinct_recipients
        WHERE distinct_recipients >= $min_recipients
        RETURN a.address AS wallet, distinct_recipients
        ORDER BY distinct_recipients DESC LIMIT 10
        """, min_recipients=min_recipients
    )
    return [(r["wallet"], r["distinct_recipients"]) for r in result]


def get_peel_chains(session):
    result = session.run(
        """
        MATCH (mid:Wallet)-[r2:SENT]->(next1:Wallet)
        MATCH (mid)-[r3:SENT]->(next2:Wallet)
        WHERE elementId(next1) < elementId(next2) AND r2.value > 0.001 AND r3.value > 0.001
        WITH mid,
             CASE WHEN r2.value > r3.value THEN r2.value ELSE r3.value END AS bigger,
             CASE WHEN r2.value > r3.value THEN r3.value ELSE r2.value END AS smaller
        WHERE (smaller / bigger) < 0.15
        WITH mid, bigger, smaller
        ORDER BY bigger DESC
        WITH mid, collect({main: bigger, peel: smaller})[0] AS top_match
        RETURN mid.address AS wallet, top_match.main AS main_amount, top_match.peel AS peel_amount
        ORDER BY main_amount DESC
        LIMIT 10
        """
    )
    return [(r["wallet"], r["main_amount"], r["peel_amount"]) for r in result]


def get_round_number_transactions(session, min_value=1.0, limit=10):
    result = session.run(
        """
        MATCH (a:Wallet)-[r:SENT]->(b:Wallet)
        WHERE r.value >= $min_value AND r.value = toInteger(r.value)
        RETURN a.address AS from_addr, b.address AS to_addr, r.value AS value
        ORDER BY r.value DESC
        LIMIT $limit
        """, min_value=min_value, limit=limit
    )
    return [(r["from_addr"], r["to_addr"], r["value"]) for r in result]


def get_circular_flows(session, max_hops=4, limit=10):
    result = session.run(
        """
        MATCH path = (a:Wallet)-[:SENT*2..%d]->(a)
        RETURN DISTINCT a.address AS wallet, length(path) AS hops
        ORDER BY hops ASC
        LIMIT $limit
        """ % max_hops, limit=limit
    )
    return [(r["wallet"], r["hops"]) for r in result]


def get_all_wallet_addresses(session):
    result = session.run("MATCH (w:Wallet) RETURN w.address AS address")
    return [r["address"] for r in result]


def narrative_to_reportlab_markup(html_text):
    """build_narrative() in logic.py produces browser-style HTML (<span class='tc-mono'>,
    <strong>) meant for Streamlit's renderer. ReportLab's Paragraph parser only understands
    a small, different tag set and has no concept of a 'class' attribute at all — passing
    the raw narrative HTML straight into a Paragraph raises a parser error. This converts
    the narrative's specific tags into ReportLab-compatible equivalents."""
    text = html_text.replace("<strong>", "<b>").replace("</strong>", "</b>")
    text = re.sub(r"<span class='tc-mono'>", "<font face='Courier'>", text)
    text = text.replace("</span>", "</font>")
    return text


def build_table_section(heading_text, heading_style, header_row, data_rows, col_widths, header_bg):
    """Builds a heading + table as one block so it never splits awkwardly across a page."""
    heading = Paragraph(heading_text, heading_style)
    table_data = [header_row] + data_rows
    t = Table(table_data, colWidths=col_widths)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), header_bg),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    return KeepTogether([heading, t])


def build_accent_box(heading_text, heading_style, body_flowables, accent_color, bg_color=BRAND_CREAM):
    """Mimics the dashboard's colored-left-border card using a 2-column table:
    a thin colored bar in column 0, the actual content in column 1."""
    content = [Paragraph(heading_text, heading_style)] + body_flowables
    bar_and_content = Table(
        [['', content]],
        colWidths=[0.3 * cm, 16.15 * cm]
    )
    bar_and_content.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, 0), accent_color),
        ('BACKGROUND', (1, 0), (1, 0), bg_color),
        ('LEFTPADDING', (0, 0), (0, 0), 0),
        ('RIGHTPADDING', (0, 0), (0, 0), 0),
        ('TOPPADDING', (0, 0), (0, 0), 0),
        ('BOTTOMPADDING', (0, 0), (0, 0), 0),
        ('LEFTPADDING', (1, 0), (1, 0), 14),
        ('TOPPADDING', (1, 0), (1, 0), 12),
        ('BOTTOMPADDING', (1, 0), (1, 0), 12),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    return KeepTogether([bar_and_content])


def build_badge_row(badges, styles):
    """badges: list of (label, value, color) tuples. Renders as a row of colored pill-like cells."""
    label_style = ParagraphStyle('BadgeLabel', parent=styles['Normal'], fontSize=7,
                                  textColor=colors.white, alignment=1)
    value_style = ParagraphStyle('BadgeValue', parent=styles['Normal'], fontSize=13,
                                  textColor=colors.white, alignment=1, fontName='Helvetica-Bold')
    cells = []
    col_widths = []
    for label, value, color in badges:
        cell_content = [Paragraph(str(value), value_style), Paragraph(label.upper(), label_style)]
        cells.append(cell_content)
        col_widths.append(16.5 * cm / len(badges))

    t = Table([cells], colWidths=col_widths)
    style_cmds = [
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]
    for i, (_, _, color) in enumerate(badges):
        style_cmds.append(('BACKGROUND', (i, 0), (i, 0), color))
    t.setStyle(TableStyle(style_cmds))
    return t


def generate_report(start_wallet, output_path="investigation_report.pdf", certificate_info=None):
    """certificate_info: optional dict with keys 'certificate_hash', 'previous_hash',
    'created_at' — if provided, embeds a Certificate of Integrity section at the end."""
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('TitleStyle', parent=styles['Title'], fontSize=22,
                                  spaceAfter=2, textColor=BRAND_BLACK, fontName='Helvetica-Bold')
    subtitle_style = ParagraphStyle('SubtitleStyle', parent=styles['Normal'], fontSize=11,
                                     textColor=BRAND_ORANGE, spaceAfter=10, fontName='Helvetica-Bold')
    meta_style = ParagraphStyle('MetaStyle', parent=styles['Normal'], fontSize=9, textColor=BRAND_MUTED)
    heading_style = ParagraphStyle('HeadingStyle', parent=styles['Heading2'], fontSize=13,
                                    spaceBefore=16, spaceAfter=8, textColor=BRAND_BLACK)
    accent_heading_style = ParagraphStyle('AccentHeadingStyle', parent=styles['Heading2'],
                                           fontSize=13, spaceAfter=6, textColor=BRAND_BLACK)
    normal_style = styles['Normal']
    mono_style = ParagraphStyle('Mono', parent=styles['Normal'], fontName='Courier', fontSize=8)
    signal_style = ParagraphStyle('SignalStyle', parent=styles['Normal'], fontName='Helvetica',
                                   fontSize=8, textColor=BRAND_MUTED)
    disclaimer_style = ParagraphStyle('DisclaimerStyle', parent=styles['Normal'], fontSize=8,
                                       textColor=BRAND_MUTED, italic=True)

    doc = SimpleDocTemplate(output_path, pagesize=A4,
                             topMargin=1.8 * cm, bottomMargin=1.8 * cm, leftMargin=1.8 * cm, rightMargin=1.8 * cm)
    elements = []

    # ---- Branded header ----
    elements.append(Paragraph("BLOCKTRACE", title_style))
    elements.append(Paragraph("FORENSIC INVESTIGATION REPORT", subtitle_style))
    elements.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", meta_style))
    elements.append(Paragraph(f"Starting wallet: <font face='Courier'>{start_wallet}</font>", meta_style))
    elements.append(Spacer(1, 14))

    with driver.session(database=NEO4J_DATABASE) as session:
        wallets, txs = get_summary_stats(session)
        hub_data = get_hub_wallets(session)
        fanout_data = get_fanout_wallets(session)
        peel_data = get_peel_chains(session)
        round_data = get_round_number_transactions(session)
        circular_data = get_circular_flows(session)
        all_addresses = get_all_wallet_addresses(session)
        sanctions_matches = check_sanctions(all_addresses)
        sanctioned_set = {addr for addr, _ in sanctions_matches}
        risk_rows = compute_wallet_risk(hub_data, fanout_data, peel_data, round_data, circular_data,
                                         sanctioned_addresses=sanctioned_set)

        # ---- Summary badge row ----
        overall_tier_label = "LOW"
        overall_tier_color = BRAND_GREEN
        if risk_rows:
            top_score = risk_rows[0][2]
            if any(s == "OFAC Sanctioned" for _, signals, _ in risk_rows for s in signals):
                overall_tier_label, overall_tier_color = "SANCTIONED MATCH", BRAND_RED
            elif top_score >= 3:
                overall_tier_label, overall_tier_color = "HIGH RISK", BRAND_RED
            elif top_score == 2:
                overall_tier_label, overall_tier_color = "MEDIUM RISK", BRAND_ORANGE

        badges = [
            ("Overall", overall_tier_label, overall_tier_color),
            ("Wallets Traced", wallets, BRAND_BLACK),
            ("Transactions", txs, BRAND_BLACK),
            ("Flagged Wallets", len(risk_rows), BRAND_BLACK),
        ]
        elements.append(build_badge_row(badges, styles))
        elements.append(Spacer(1, 16))

        # ---- What This Trail Shows (shared narrative logic) ----
        narrative_paragraphs = build_narrative(
            start_wallet, wallets, txs, hub_data, fanout_data, peel_data, round_data, circular_data, risk_rows
        )
        narrative_flowables = [Paragraph(narrative_to_reportlab_markup(p), normal_style) for p in narrative_paragraphs]
        narrative_flowables.append(Spacer(1, 4))
        narrative_flowables.append(Paragraph(
            "These patterns are heuristic indicators derived from public blockchain data, not proof "
            "of wrongdoing. Review by a qualified investigator is recommended before drawing conclusions.",
            disclaimer_style
        ))
        elements.append(build_accent_box("What This Trail Shows", accent_heading_style,
                                          narrative_flowables, BRAND_ORANGE))
        elements.append(Spacer(1, 10))

        # ---- Sanctions Screening ----
        if sanctions_matches:
            sanctions_rows = [
                [Paragraph(addr, mono_style), Paragraph(f"{entry['name']} — {entry['authority']}", signal_style)]
                for addr, entry in sanctions_matches
            ]
            elements.append(build_table_section(
                "Sanctions Screening", heading_style,
                ["Wallet Address", "Match Details"], sanctions_rows,
                [7 * cm, 9.5 * cm], BRAND_RED
            ))
        else:
            elements.append(Paragraph("Sanctions Screening", heading_style))
            elements.append(Paragraph(
                "No wallets in this trace matched the verified sanctions list on file.", normal_style
            ))
        elements.append(Spacer(1, 10))

        # ---- Wallet Risk Overview ----
        elements.append(Paragraph("Wallet Risk Overview", heading_style))
        if risk_rows:
            for wallet, signals, score in risk_rows[:10]:
                tier_label, _ = risk_tier(score)
                tier_color = BRAND_GREEN if tier_label == "Low" else (BRAND_ORANGE if tier_label == "Medium" else BRAND_RED)
                if "OFAC Sanctioned" in signals:
                    tier_color = BRAND_RED
                row = Table(
                    [[Paragraph(f"{wallet}<br/><font color='#6B6255' size=7>{' · '.join(signals)}</font>", mono_style),
                      Paragraph(f"{tier_label.upper()} · {score} signals", ParagraphStyle('TierBadge', fontSize=8, textColor=colors.white, alignment=1))]],
                    colWidths=[12.5 * cm, 4 * cm]
                )
                row.setStyle(TableStyle([
                    ('BACKGROUND', (1, 0), (1, 0), tier_color),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('TOPPADDING', (0, 0), (-1, -1), 6),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                    ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#E0D3B0')),
                ]))
                elements.append(row)
                elements.append(Spacer(1, 3))
        else:
            elements.append(Paragraph("No wallets triggered any detection signal in this dataset.", normal_style))
        elements.append(Spacer(1, 10))

        # ---- Detection technique sections (all 5) ----
        hub_rows = [[Paragraph(w, mono_style), str(c)] for w, c in hub_data]
        if hub_data:
            elements.append(build_table_section(
                "Hub Wallets (High Activity)", heading_style,
                ["Wallet Address", "Total Transactions"], hub_rows,
                [11 * cm, 5 * cm], BRAND_BLACK
            ))
        else:
            elements.append(Paragraph("Hub Wallets (High Activity)", heading_style))
            elements.append(Paragraph("No hub wallets detected.", normal_style))
        elements.append(Spacer(1, 6))

        fanout_rows = [[Paragraph(w, mono_style), str(c)] for w, c in fanout_data]
        if fanout_data:
            elements.append(build_table_section(
                "High Fan-Out Wallets (Possible Fund Splitting)", heading_style,
                ["Wallet Address", "Distinct Recipients"], fanout_rows,
                [11 * cm, 5 * cm], BRAND_RED
            ))
        else:
            elements.append(Paragraph("High Fan-Out Wallets (Possible Fund Splitting)", heading_style))
            elements.append(Paragraph("No high fan-out wallets detected.", normal_style))
        elements.append(Spacer(1, 6))

        if peel_data:
            peel_rows = [[Paragraph(w, mono_style), f"{m:.4f}", f"{p:.4f}"] for w, m, p in peel_data]
            elements.append(build_table_section(
                "Possible Peel Chains (Laundering Pattern)", heading_style,
                ["Wallet Address", "Main Amount", "Peel Amount"], peel_rows,
                [9 * cm, 3.5 * cm, 3.5 * cm], BRAND_BLUE
            ))
        else:
            elements.append(Paragraph("Possible Peel Chains (Laundering Pattern)", heading_style))
            elements.append(Paragraph("No peel chain patterns detected.", normal_style))
        elements.append(Spacer(1, 6))

        if round_data:
            round_rows = [[Paragraph(f"{short(f)} → {short(t)}", mono_style), f"{v:.0f}"] for f, t, v in round_data]
            elements.append(build_table_section(
                "Round-Number Transactions", heading_style,
                ["Transaction", "Amount"], round_rows,
                [11 * cm, 5 * cm], BRAND_ORANGE
            ))
        else:
            elements.append(Paragraph("Round-Number Transactions", heading_style))
            elements.append(Paragraph("No round-number transactions detected.", normal_style))
        elements.append(Spacer(1, 6))

        if circular_data:
            circular_rows = [[Paragraph(w, mono_style), f"{h} hops"] for w, h in circular_data]
            elements.append(build_table_section(
                "Circular Flows (Possible Wash Trading)", heading_style,
                ["Wallet Address", "Loop Length"], circular_rows,
                [11 * cm, 5 * cm], BRAND_VIOLET
            ))
        else:
            elements.append(Paragraph("Circular Flows (Possible Wash Trading)", heading_style))
            elements.append(Paragraph("No circular flows detected.", normal_style))

        # ---- Certificate of Integrity (optional) ----
        if certificate_info:
            cert_flowables = [
                Paragraph(
                    f"Certificate Hash: <font face='Courier'>{certificate_info['certificate_hash']}</font>",
                    mono_style
                ),
                Paragraph(
                    f"Previous Hash: <font face='Courier'>{certificate_info['previous_hash']}</font>",
                    mono_style
                ),
                Paragraph(f"Issued: {certificate_info.get('created_at', 'N/A')}", signal_style),
                Spacer(1, 4),
                Paragraph(
                    "This report's findings are sealed under the certificate hash above. Anyone can "
                    "independently verify this report has not been altered by recomputing the SHA-256 "
                    "hash of the recorded findings concatenated with the previous hash, and confirming "
                    "it matches the certificate hash — without needing to trust this document's source.",
                    signal_style
                ),
            ]
            elements.append(Spacer(1, 10))
            elements.append(build_accent_box("Certificate of Integrity", accent_heading_style,
                                              cert_flowables, BRAND_BLACK))

        elements.append(Spacer(1, 16))
        elements.append(Paragraph(
            "This report was generated using automated graph-based heuristics (hub detection, "
            "fan-out detection, peel-chain detection, round-number detection, circular-flow detection) "
            "and sanctions-list screening applied to public blockchain transaction data. Findings should "
            "be reviewed by a qualified investigator before use in any formal proceeding.",
            disclaimer_style
        ))

    doc.build(elements)
    print(f"Report saved to {output_path}")


if __name__ == "__main__":
    generate_report("0x098B716B8Aaf21512996dC57EB0615e2383E2f96")
