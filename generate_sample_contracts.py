"""
generate_sample_contracts.py

Generates a small set of sample contract PDFs used to test the Contract
Intelligence pipeline:
  - clean_msa.pdf              -> should pass with ~0 flags
  - defect_msa_liability.pdf   -> liability cap + missing carve-outs flagged
  - defect_msa_autorenewal.pdf -> auto-renewal + short termination notice flagged
  - clean_nda.pdf              -> should pass with ~0 flags
  - defect_nda_confidentiality.pdf -> short confidentiality survival + assignment flagged

Run once: python generate_sample_contracts.py
Outputs land in data/contracts/
"""

import os
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.units import inch

OUT_DIR = os.path.join(os.path.dirname(__file__), "data", "contracts")
os.makedirs(OUT_DIR, exist_ok=True)
styles = getSampleStyleSheet()


def render(filename, title, sections):
    path = os.path.join(OUT_DIR, filename)
    doc = SimpleDocTemplate(path, pagesize=letter,
                             topMargin=0.8 * inch, bottomMargin=0.8 * inch)
    story = [Paragraph(title, styles["Title"]), Spacer(1, 0.2 * inch)]
    for heading, body in sections:
        story.append(Paragraph(heading, styles["Heading3"]))
        story.append(Paragraph(body, styles["BodyText"]))
        story.append(Spacer(1, 0.15 * inch))
    doc.build(story)
    print(f"Wrote {path}")


# ---------------------------------------------------------------------------
# CLEAN MSA — should trigger no flags against playbook.yaml
# ---------------------------------------------------------------------------
clean_msa_sections = [
    ("1. Term and Termination",
     "This Agreement shall commence on the Effective Date and continue until terminated. "
     "Either party may terminate this Agreement for convenience by providing sixty (60) days "
     "written notice to the other party."),

    ("2. Payment Terms",
     "Client shall pay all undisputed invoiced amounts within thirty (30) days of the invoice date."),

    ("3. Limitation of Liability",
     "In no event shall either party's aggregate liability arising out of this Agreement exceed "
     "two (2) times the total fees paid or payable under this Agreement in the twelve (12) months "
     "preceding the claim. The foregoing limitation of liability shall not apply to breaches of "
     "confidentiality obligations, gross negligence or willful misconduct, or infringement of "
     "intellectual property rights."),

    ("4. Indemnification",
     "Each party shall indemnify, defend, and hold harmless the other party from and against any "
     "third-party claims arising out of the indemnifying party's breach of this Agreement or "
     "negligent acts or omissions."),

    ("5. Renewal",
     "This Agreement shall not renew automatically. Any renewal shall require a new written order "
     "form executed by both parties."),

    ("6. Assignment",
     "Neither party may assign or transfer this Agreement, in whole or in part, without the prior "
     "written consent of the other party, such consent not to be unreasonably withheld."),

    ("7. Dispute Resolution",
     "Any dispute arising under this Agreement shall first be submitted to good-faith negotiation "
     "between the parties, and if unresolved within thirty (30) days, shall be finally resolved by "
     "binding arbitration administered under the rules of the American Arbitration Association."),

    ("8. Governing Law",
     "This Agreement shall be governed by and construed in accordance with the laws of the State "
     "of Delaware, without regard to its conflict of laws principles."),
]

render("clean_msa.pdf", "Master Services Agreement", clean_msa_sections)


# ---------------------------------------------------------------------------
# DEFECT MSA #1 — liability cap too low + no carve-outs (2 flags expected)
# ---------------------------------------------------------------------------
defect_msa_liability_sections = [
    ("1. Term and Termination",
     "This Agreement shall commence on the Effective Date and continue until terminated. "
     "Either party may terminate this Agreement for convenience by providing forty-five (45) days "
     "written notice to the other party."),

    ("2. Payment Terms",
     "Client shall pay all undisputed invoiced amounts within forty-five (45) days of the invoice date."),

    ("3. Limitation of Liability",
     "In no event shall either party's aggregate liability arising out of this Agreement exceed "
     "fifty percent (0.5x) of the total fees paid or payable under this Agreement in the twelve (12) "
     "months preceding the claim. This limitation of liability applies to all claims without exception."),

    ("4. Indemnification",
     "Each party shall indemnify, defend, and hold harmless the other party from and against any "
     "third-party claims arising out of the indemnifying party's breach of this Agreement."),

    ("5. Renewal",
     "This Agreement shall not renew automatically and requires a new written order form."),

    ("6. Assignment",
     "Neither party may assign this Agreement without the prior written consent of the other party."),

    ("7. Dispute Resolution",
     "Any dispute arising under this Agreement shall be finally resolved by binding arbitration."),

    ("8. Governing Law",
     "This Agreement shall be governed by the laws of the State of New York."),
]

render("defect_msa_liability.pdf", "Master Services Agreement (Vendor Draft)",
       defect_msa_liability_sections)


# ---------------------------------------------------------------------------
# DEFECT MSA #2 — auto-renewal + short termination notice (2 flags expected)
# ---------------------------------------------------------------------------
defect_msa_autorenewal_sections = [
    ("1. Term and Termination",
     "This Agreement shall commence on the Effective Date and continue for an initial term of one "
     "year. Either party may terminate this Agreement for convenience by providing ten (10) days "
     "written notice to the other party."),

    ("2. Payment Terms",
     "Client shall pay all undisputed invoiced amounts within thirty (30) days of the invoice date."),

    ("3. Limitation of Liability",
     "In no event shall either party's aggregate liability exceed two (2) times the total fees paid "
     "under this Agreement. The foregoing shall not apply to breaches of confidentiality, gross "
     "negligence, or infringement of intellectual property rights."),

    ("4. Indemnification",
     "Each party shall indemnify and hold harmless the other party from third-party claims arising "
     "out of the indemnifying party's acts or omissions."),

    ("5. Renewal",
     "This Agreement shall automatically renew for successive one-year terms unless either party "
     "provides notice of non-renewal at least thirty (30) days prior to the end of the then-current term."),

    ("6. Assignment",
     "Neither party may assign this Agreement without the prior written consent of the other party."),

    ("7. Dispute Resolution",
     "Any dispute arising under this Agreement shall be resolved through litigation in a court of "
     "competent jurisdiction."),

    ("8. Governing Law",
     "This Agreement shall be governed by the laws of England and Wales."),
]

render("defect_msa_autorenewal.pdf", "Master Services Agreement (Renewal Terms)",
       defect_msa_autorenewal_sections)


# ---------------------------------------------------------------------------
# CLEAN NDA — should trigger no flags
# ---------------------------------------------------------------------------
clean_nda_sections = [
    ("1. Confidential Information",
     "Each party may disclose certain confidential and proprietary information to the other party "
     "in connection with the parties' business relationship."),

    ("2. Term and Termination",
     "This Agreement shall remain in effect for two (2) years from the Effective Date. Either party "
     "may terminate this Agreement by providing thirty (30) days written notice."),

    ("3. Survival of Confidentiality",
     "The obligations of confidentiality set forth herein shall survive termination of this Agreement "
     "for a period of three (3) years."),

    ("4. Indemnification",
     "Each party shall indemnify and hold harmless the other party from claims arising out of an "
     "unauthorized disclosure of Confidential Information by the indemnifying party."),

    ("5. Assignment",
     "Neither party may assign this Agreement without the prior written consent of the other party."),

    ("6. Dispute Resolution",
     "Any dispute arising under this Agreement shall be resolved through binding arbitration."),

    ("7. Governing Law",
     "This Agreement shall be governed by the laws of the State of Delaware."),
]

render("clean_nda.pdf", "Mutual Non-Disclosure Agreement", clean_nda_sections)


# ---------------------------------------------------------------------------
# DEFECT NDA — short confidentiality survival + assignable without consent
# ---------------------------------------------------------------------------
defect_nda_sections = [
    ("1. Confidential Information",
     "Each party may disclose certain confidential and proprietary information to the other party "
     "in connection with the parties' business relationship."),

    ("2. Term and Termination",
     "This Agreement shall remain in effect for one (1) year from the Effective Date. Either party "
     "may terminate this Agreement by providing fifteen (15) days written notice."),

    ("3. Survival of Confidentiality",
     "The obligations of confidentiality set forth herein shall survive termination of this Agreement "
     "for a period of six (6) months."),

    ("4. Indemnification",
     "Each party shall indemnify and hold harmless the other party from claims arising out of an "
     "unauthorized disclosure of Confidential Information."),

    ("5. Assignment",
     "This Agreement and all rights hereunder may be freely assigned by either party without the "
     "consent of the other party."),

    ("6. Dispute Resolution",
     "Any dispute arising under this Agreement shall be resolved through litigation."),

    ("7. Governing Law",
     "This Agreement shall be governed by the laws of the State of California."),
]

render("defect_nda_confidentiality.pdf", "Mutual Non-Disclosure Agreement (Counterparty Draft)",
       defect_nda_sections)

print("\nAll sample contracts generated.")
