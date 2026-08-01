"""
Realistic seed data + idempotent seeder.

Seeds 22 demo leads that span the full Hot/Warm/Cold/Converted/Lost spectrum
and multiple acquisition channels (LinkedIn, Webhook, Referral, Webinar,
Cold Email, Demo Request). Source taxonomy is normalized to channel-type
labels only — no strategy or event labels mixed in. This guarantees that
the very first time a recruiter opens the live demo, they see a populated
pipeline with consistent, scannable data — not an empty DB.

The seeder is idempotent: it only seeds when the DB is empty (or when
`force=True`, used by the periodic demo-reset).
"""
from __future__ import annotations

import logging
from typing import List, Dict

from db import clear_all_leads, init_db, insert_lead
from groq_classifier import classify_lead as _classify

logger = logging.getLogger("leadmind.seed")

# Each seed lead's message is deliberately written in a tone that exercises
# both the Groq classifier and the fallback keyword classifier, so the demo
# is interesting even without a Groq key configured.
SEED_LEADS: List[Dict[str, str]] = [
    {
        "name": "Sarah Chen",
        "contact_info": "sarah.chen@techcorp.com",
        "message": (
            "Hi, we need a CRM solution urgently — our team is growing fast and "
            "budget is approved for Q3. Can we get a demo this week? Decision needed by Friday."
        ),
        "source": "Webinar",
    },
    {
        "name": "Marcus Rodriguez",
        "contact_info": "marcus@brightpath.io",
        "message": (
            "Just browsing, looking at different options for our startup. "
            "Maybe in a few months we'll have budget. No rush right now."
        ),
        "source": "Webinar",
    },
    {
        "name": "Priya Sharma",
        "contact_info": "priya.sharma@globaltech.in",
        "message": (
            "We're evaluating 3 vendors right now. Your feature set looks interesting. "
            "What's the pricing for 50 seats? Happy to discuss next week."
        ),
        "source": "Cold Email",
    },
    {
        "name": "James O'Connor",
        "contact_info": "james@oconnor-consulting.ie",
        "message": (
            "Our current contract expires next month and we need to switch ASAP. "
            "Decision needs to be made by Friday. Send quote for annual plan."
        ),
        "source": "Referral",
    },
    {
        "name": "Aisha Patel",
        "contact_info": "aisha.patel@medsystems.com",
        "message": (
            "Interested in learning more, but no rush. We're thinking about a Q4 rollout. "
            "Send some info and case studies when you get a chance."
        ),
        "source": "LinkedIn",
    },
    {
        "name": "David Kim",
        "contact_info": "d.kim@financehub.co.kr",
        "message": (
            "Ready to sign immediately. We have budget approved and the team is ready. "
            "Just need the final contract for 100 seats."
        ),
        "source": "Demo Request",
    },
    {
        "name": "Elena Volkov",
        "contact_info": "elena.v@creative-studio.ru",
        "message": (
            "Curious about your product, just doing research. Not looking to buy anything "
            "for a year or so. Subscribed to your newsletter for now."
        ),
        "source": "LinkedIn",
    },
    {
        "name": "Thomas Müller",
        "contact_info": "t.muller@germanauto.de",
        "message": (
            "We have a meeting with our CFO tomorrow to discuss budget. Your proposal looks "
            "good. Need final pricing for 200 users urgently."
        ),
        "source": "Cold Email",
    },
    {
        "name": "Olivia Bennett",
        "contact_info": "olivia.b@retailgurus.com",
        "message": (
            "Can you schedule a call next week? Our team has some questions about integrations "
            "before we make a decision. Exploring options."
        ),
        "source": "Webinar",
    },
    {
        "name": "Raj Mehta",
        "contact_info": "raj.mehta@analyticspro.in",
        "message": (
            "Looking to invest in a CRM but exploring multiple options. Will get back to you "
            "in 2-3 weeks after internal review. Send pricing comparison please."
        ),
        "source": "Webinar",
    },
    {
        "name": "Sophia Rossi",
        "contact_info": "sophia@rossi-fashion.it",
        "message": (
            "URGENT: Our sales team is losing leads daily without a CRM. Budget approved, "
            "need demo today, ready to purchase this week. Call me immediately."
        ),
        "source": "Referral",
    },
    {
        "name": "Lucas Silva",
        "contact_info": "lucas.silva@fintechbrasil.com.br",
        "message": (
            "We're a small team, just starting out. Maybe in 6 months we'll be ready. "
            "Just subscribed to your newsletter for now."
        ),
        "source": "LinkedIn",
    },
    {
        "name": "Hannah Schmidt",
        "contact_info": "hannah@schmidt-consulting.de",
        "message": (
            "Our procurement team is reviewing your proposal. They have questions about "
            "security and compliance. Can we schedule a technical call this week?"
        ),
        "source": "Cold Email",
    },
    {
        "name": "Mohammed Al-Rashid",
        "contact_info": "m.alrashid@gulftech.ae",
        "message": (
            "Interested in your enterprise plan. We have budget allocated for this quarter. "
            "Need to see a demo and discuss custom integration ASAP."
        ),
        "source": "Demo Request",
    },
    {
        "name": "Emma Thompson",
        "contact_info": "emma.t@thompson-law.co.uk",
        "message": (
            "Just looking at what's out there. No immediate plans to purchase. "
            "Maybe next year. Just gathering info."
        ),
        "source": "LinkedIn",
    },
    {
        "name": "Yuki Tanaka",
        "contact_info": "yuki.tanaka@japaninnovate.jp",
        "message": (
            "We're ready to move forward. Approved budget, decision maker is on board. "
            "Send the contract and pricing for annual plan immediately."
        ),
        "source": "Referral",
    },
    {
        "name": "Diego Fernandez",
        "contact_info": "d.fernandez@saborfoods.mx",
        "message": (
            "Evaluating CRM options for our sales expansion. Will decide in the next 30 days. "
            "Send pricing comparison please, and let's discuss soon."
        ),
        "source": "Cold Email",
    },
    {
        "name": "Grace Wangari",
        "contact_info": "grace@savannahtech.ke",
        "message": (
            "Need to discuss with my co-founder before any commitment. Just gathering info "
            "for now. Reach out in a month. Not ready to buy."
        ),
        "source": "Webinar",
    },
    # --- Converted leads (closed-won) — makes Conversion Rate non-zero ---
    {
        "name": "Liam O'Brien",
        "contact_info": "liam.obrien@northstar-logistics.com",
        "message": (
            "We signed the annual contract last week — onboarding went smoothly. "
            "Already seeing ROI, the team adopted it fast. Invoices paid, ready to expand to 150 seats."
        ),
        "source": "Referral",
        "force_status": "Converted",
    },
    {
        "name": "Mei Lin Chen",
        "contact_info": "meilin.chen@horizonmedia.tw",
        "message": (
            "Contract signed, kickoff call done, our marketing team is fully onboarded. "
            "Loving the dashboard and the MCP integration with our internal tools. Reference customer here."
        ),
        "source": "Demo Request",
        "force_status": "Converted",
    },
    # --- Lost leads (closed-lost) — makes Lost status badge appear in UI ---
    {
        "name": "Carlos Mendes",
        "contact_info": "carlos.mendes@portaldigital.br",
        "message": (
            "Went with a competitor — they offered a steeper discount. Was a close call, "
            "your product was great but pricing was the deciding factor. Re-engage in 6 months maybe."
        ),
        "source": "Cold Email",
        "force_status": "Lost",
    },
    {
        "name": "Ingrid Larsson",
        "contact_info": "ingrid.larsson@nordicfintech.se",
        "message": (
            "Project got deprioritized — our CTO left and the CRM initiative is on hold indefinitely. "
            "Budget frozen for the rest of the year. Not pursuing any vendors right now."
        ),
        "source": "LinkedIn",
        "force_status": "Lost",
    },
]


def seed_database(force: bool = False) -> bool:
    """
    Seed the DB with demo leads. Returns True if seeding happened.

    Args:
        force: when True, wipes existing leads/history and re-seeds.
               when False, only seeds if the leads table is empty.
    """
    init_db()
    if force:
        clear_all_leads()

    # Check current count
    from db import get_db
    with get_db() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM leads").fetchone()["c"]
    if count > 0 and not force:
        logger.info("Database already has %d leads; skipping seed.", count)
        return False

    seeded = 0
    for lead in SEED_LEADS:
        classification = _classify(lead["message"])
        # Allow seed entries to override the auto-classified status (e.g. for
        # Converted / Lost leads whose message tone doesn't match the rule-based
        # classifier but represents a later stage in the pipeline).
        forced_status = lead.get("force_status")
        final_status = forced_status if forced_status else classification["status"]
        history_entries = [
            {
                "event_type": "created",
                "event_description": f"Seeded demo lead from source: {lead['source']}",
                "new_value": final_status,
            },
            {
                "event_type": "classified",
                "event_description": (
                    f"Auto-classified as {classification['status']} "
                    f"({classification['reasoning']}) [source={classification['source']}] "
                    f"[score={classification.get('confidence', '?')}]"
                ),
                "old_value": None,
                "new_value": classification["status"],
            },
        ]
        if forced_status and forced_status != classification["status"]:
            history_entries.append({
                "event_type": "status_change",
                "event_description": (
                    f"Seeded as {forced_status} (overridden from auto-classified "
                    f"{classification['status']} to represent a {forced_status.lower()} lead)"
                ),
                "old_value": classification["status"],
                "new_value": forced_status,
            })
        insert_lead(
            name=lead["name"],
            contact_info=lead["contact_info"],
            message=lead["message"],
            status=final_status,
            source=lead["source"],
            history_entries=history_entries,
        )
        seeded += 1

    logger.info("Seeded %d demo leads into the database.", seeded)
    return True
