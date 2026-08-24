#!/usr/bin/env python3
import json, hashlib, os, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

DATA = Path("data")
def wj(p, d): p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
def gh(d): return hashlib.sha256(json.dumps(d, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
def iso(d=0): return (datetime.now(timezone.utc) + timedelta(days=d)).strftime("%Y-%m-%dT%H:%M:%SZ")
def grade(s):
    if s >= 0.9: return "A"
    if s >= 0.8: return "B"
    if s >= 0.7: return "C"
    if s >= 0.6: return "D"
    return "F"

def make_manifest(rid, proj, ds_id, ds_ver, ds_con, ds_n, metrics, model, skill, ts):
    m = {"manifest_version":"1.0","run_id":rid,"created_at":ts,"triggered_by":"agent",
         "dataset":{"dataset_id":ds_id,"version_hash":ds_ver,"content_hash":ds_con,"n_cases":ds_n,"source_path":"data/datasets/"+ds_id+"/test_cases.json"},
         "metrics":metrics,"skill":{"name":skill,"content_hash":gh({"name":skill})},
         "model":{"model_id":model,"base_url":"https://api.openai.com/v1"},
         "judge_model":{"model_id":"gpt-4o","base_url":"https://api.openai.com/v1"},
         "environment":{"python_version":"3.12.0","platform":"macOS-14.0","dependencies":{"deepeval":"1.2.0","openai":"1.0.0"}},"extra":{}}
    mc = {k:v for k,v in m.items() if k!="manifest_hash"}
    m["manifest_hash"] = gh(mc)
    return m

def make_meta(rid, proj, score, pr, fields, mids, ts):
    return {"run_id":rid,"project":proj,"triggered_by":"agent","timestamp":ts,"status":"completed","overall_score":score,"pass_rate":pr,"fields":fields,"metrics":mids}

def make_dref(ds_id, ds_ver, ds_con, ds_n):
    return {"n_cases":ds_n,"dataset_id":ds_id,"version_hash":ds_ver,"content_hash":ds_con,"source_path":"data/datasets/"+ds_id+"/test_cases.json"}

def make_config(model, flds):
    return {"model":{"modelId":model,"baseUrl":"https://api.openai.com/v1"},"judgeModel":{"modelId":"gpt-4o","baseUrl":"https://api.openai.com/v1"},"fields":flds}

def create_dataset(ds_id, name, desc, cases, ts):
    ds_dir = DATA / "datasets" / ds_id
    ds_dir.mkdir(parents=True, exist_ok=True)
    ch = gh(cases)
    ds = {"dataset_id":ds_id,"name":name,"description":desc,"n_cases":len(cases),"version_hash":ch[:16],"content_hash":ch,
          "schema":{"type":"object","properties":{"input":{"type":"string"},"expected_output":{"type":"string"}}},
          "created_at":ts}
    wj(ds_dir / "dataset.json", ds)
    wj(ds_dir / "test_cases.json", cases)
    return ch

def create_run(rid, project, ds_id, ds_ver, ds_con, ds_n, overall_score, pass_rate, field_scores, metrics_list, model_id, skill_name, ts, results_data):
    d = make_manifest(rid, project, ds_id, ds_ver, ds_con, ds_n, metrics_list, model_id, skill_name, ts)
    d["manifest_hash"] = gh({k:v for k,v in d.items() if k!="manifest_hash"})
    fields = {}
    for fn, fs in field_scores.items():
        fields[fn] = {"field_score": fs}
    meta = make_meta(rid, project, overall_score, pass_rate, fields, [m["metric_id"] for m in metrics_list], ts)
    dref = make_dref(ds_id, ds_ver, ds_con, ds_n)
    config = make_config(model_id, [{"name": fn, "gatePipeline": [], "scorePipeline": []} for fn in field_scores])
    run_dir = DATA / "runs" / rid
    wj(run_dir / "manifest.json", d)
    wj(run_dir / "meta.json", meta)
    wj(run_dir / "results.json", results_data)
    wj(run_dir / "config.json", config)
    wj(run_dir / "dataset_ref.json", dref)
    return rid

print("Helper functions loaded.")

# ===== DATASET DATA =====

# Customer Support templates (60 cases)
SUPPORT_TPL = [
    ("What is your return policy?","Our return policy allows returns within 30 days of purchase. Items must be in original condition with tags attached. Refunds are processed within 5-7 business days.","policy","easy"),
    ("How do I reset my password?","Go to the login page, click 'Forgot Password', enter your registered email, and follow the link sent to your inbox. The reset link expires after 24 hours.","account","easy"),
    ("Do you ship internationally?","Yes, we ship to over 50 countries. International shipping rates are calculated at checkout. Delivery typically takes 7-14 business days. Customs duties may apply.","shipping","easy"),
    ("What payment methods do you accept?","We accept Visa, Mastercard, American Express, PayPal, Apple Pay, Google Pay, and bank transfers for orders over $500.","payment","easy"),
    ("Can I cancel my order after placing it?","You can cancel within 1 hour through your account dashboard. After 1 hour, orders enter processing. Contact support for assistance after this window.","order","easy"),
    ("My order shows delivered but I haven't received it. What should I do?","Check with neighbors and around your property. Check tracking for delivery notes. If still missing after 24 hours, we will initiate a carrier investigation and arrange replacement or refund.","delivery","medium"),
    ("My refund was approved but money hasn't appeared in my bank account. How long?","Refunds take 5-7 business days. Credit cards: 3-5 days. PayPal: 1-2 days. Bank transfers: up to 7-10 days. Contact us if not received after 10 business days.","refund","medium"),
    ("I received a damaged item. What's the process?","Take photos within 48 hours. Send to support with order number. We arrange free return pickup and ship replacement immediately, or full refund.","returns","medium"),
    ("Can I change my shipping address after placing the order?","You can change within 30 minutes through your account. After 30 minutes, contact support immediately. We will try to accommodate but cannot guarantee once order enters processing.","shipping","medium"),
    ("Do you offer price matching?","Yes, within 14 days of purchase. Provide competitor's URL or advertisement showing lower price and your order number. Exclusions: marketplace sellers, auction sites, clearance items.","pricing","medium"),
    ("[Previous: asked about laptop warranty] And what about accidental damage?","Standard warranty does not cover accidental damage. We offer Accidental Damage Protection plan within 30 days of purchase. Covers up to 2 incidents per year.","warranty","medium"),
    ("[Previous: discussing subscription upgrade] Can I keep my existing data?","Yes, all your existing data, settings, and history are preserved when upgrading or downgrading. The transition is seamless with no downtime.","account","easy"),
    ("[Previous: asking about delivery] Actually, I need it by Friday. Express option?","Yes, Next-Day Air guarantees delivery tomorrow if ordered before 2 PM. 2-Day Express is available at lower rate. Would you like me to check rates for your order?","shipping","medium"),
    ("Can I use the PRO-2000 charger with my X-15 device?","No, the PRO-2000 uses 65W USB-C PD, while X-15 requires proprietary 45W magnetic connector. Using incompatible charger may damage your device. Recommended: X-Charge 45W.","compatibility","medium"),
    ("What's the difference between Basic and Premium plans?","Basic ($9.99/mo): 10 projects, 5GB storage, email support. Premium ($29.99/mo): unlimited projects, 100GB storage, priority support, analytics, API access, team features.","pricing","easy"),
    ("Is there a family sharing option?","Yes, Family plan ($39.99/mo) allows up to 6 family members with individual accounts. Includes all Premium features, parental controls, 200GB shared storage.","pricing","easy"),
    ("I bought a subscription on iOS but want to manage it on Android. Can I?","iOS-purchased subscriptions must be managed through Apple ID settings. Cancel iOS subscription and resubscribe directly through our website. All data preserved.","account","hard"),
    ("I ordered two items but only received one. The package was sealed.","Check if items were shipped separately (two tracking numbers). If packing error, we will ship the missing item immediately with express delivery at no extra cost.","order","hard"),
    ("I've been charged twice for the same order. Order #ORD-88291.","This can happen when payment authorization and capture are separate. The duplicate charge is usually an authorization hold that drops off in 3-5 business days.","payment","hard"),
    ("My promo code 'SUMMER25' isn't working. Email says it's valid until tomorrow.","Check: items must be eligible, minimum $50 purchase, first-time customers only. If you meet all requirements, I can manually apply the discount.","promo","hard"),
    ("When will the X-200 model be back in stock?","I don't have specific restock dates. Sign up for in-stock notifications. X-200 typically restocks every 2-3 weeks. Check authorized retailers for remaining stock.","stock","medium"),
    ("Can you tell me what my wife ordered for my birthday?","For privacy and security reasons, I cannot share details of orders placed by other account holders. Each account's order history is confidential.","privacy","medium"),
    ("What's the CEO's email address? I have a complaint.","I cannot share personal contact information of executives. Please share your issue and I will escalate to our Customer Experience team, who report to leadership.","privacy","medium"),
    ("Your competitor offers lifetime warranty for the same price. Why don't you?","We offer 2-year standard warranty with optional 3-year extended. Our products undergo 200+ hours of quality testing with 98.4% satisfaction rate.","comparison","hard"),
    ("I heard you're going out of business. Should I cancel my pre-order?","There is no truth to any rumors about us going out of business. We are financially stable with strong growth. Your pre-order is secure.","rumors","hard"),
    ("Does your product cure cancer? I saw a video online.","No, our products do not cure cancer or treat any medical condition. We are a consumer electronics company. The video is spreading misinformation.","misinformation","hard"),
    ("How do I track my order?","Log into your account, go to My Orders, click Track. Or use the tracking number from your email. Tracking info becomes available 2-4 hours after shipping.","order","easy"),
    ("Can I return an item I bought on sale?","Yes, sale items can be returned within 30 days if in original condition with tags. Exception: items marked 'Final Sale - No Returns'.","returns","easy"),
    ("I forgot to apply my discount code. Can I still get the discount?","Contact us within 24 hours of placing order, we can apply the code retroactively and refund the difference. After 24 hours, depends on code and shipping status.","promo","medium"),
    ("My package says delivered to 'front desk' but I live in a house.","This sounds like a carrier delivery error. Check around property, side doors, garage, and with neighbors. Contact us if not found within 4 hours.","delivery","medium"),
    ("Do you have a physical store I can visit?","We are primarily online. Two flagship experience centers: San Francisco (555 Market St) and New York (350 Fifth Ave). Mon-Sat, 10 AM-7 PM.","general","easy"),
    ("How do I delete my account permanently?","Account Settings > Privacy > Delete Account. Verify with password. Deletion is irreversible. Cancel active subscriptions first. Process takes up to 30 days.","account","medium"),
    ("Can I get an invoice for my order? I need it for expense reporting.","Yes, download invoice from My Orders > Download Invoice. PDF includes order number, date, itemized prices, tax, shipping, business info.","billing","easy"),
    ("The product color looks different from the website photos. Can I exchange?","Yes, colors can appear differently on screens. Exchange within 30-day window. We cover return shipping for color exchanges.","returns","easy"),
    ("I'm having trouble logging in. The site says 'account locked'.","Accounts lock after 5 failed login attempts. Lock expires after 30 minutes. Use 'Forgot Password' to reset and unlock immediately.","account","easy"),
    ("Do you have a loyalty program or rewards points?","Yes, 'Earn & Return' program: 1 point per $1 spent. Redeem: 500 pts = $5 off, 1000 pts = $12 off, 2000 pts = $25 off. Premium members earn 1.5x.","loyalty","easy"),
    ("Can I place an order by phone?","Yes, call 1-800-555-0199 Mon-Fri 8 AM-8 PM EST, Sat 9 AM-5 PM EST. Agents can assist with product questions and process payment securely.","order","easy"),
    ("I need to return a gift. I don't have the order number.","We can help without order number. Provide gift giver's name and email. Or we can process for store credit using product serial number.","returns","medium"),
    ("What is your warranty on refurbished products?","Refurbished products have 90-day warranty covering hardware defects. Different from new product warranty (2 years). No extended warranty available. Final sale.","warranty","medium"),
    ("Can I make a bulk purchase for my company? We need 50 units.","Yes, dedicated Business Sales team for orders of 10+ units. Volume discounts (5-15%), dedicated account manager, net-30 invoicing.","business","medium"),
    ("I accidentally ordered the wrong size. Can I change it before it ships?","If not yet shipped, contact us immediately with order number and correct size. If already in fulfillment, we set up free exchange.","order","medium"),
    ("Your app keeps crashing on my iPhone 8. I've reinstalled it twice.","iPhone 8 is minimum supported device (requires iOS 15+). Ensure iOS is updated. Clear app cache. Try mobile website. Share crash logs for investigation.","technical","hard"),
    ("I want to file a formal complaint about a rude customer service representative.","We take complaints seriously. Provide date/time, representative name, channel, description. Reviewed by QA team within 48 hours. Supervisor will follow up.","complaint","medium"),
    ("Can I schedule a delivery for a specific date and time?","Yes, select 'Scheduled Delivery' at checkout. Choose time window: 9-12, 12-4, or 4-8 PM. Available Tue-Sat. Additional fee: $9.99.","shipping","easy"),
    ("I'm moving to a different country. Can I transfer my account and purchases?","Account accessible from any country, but some content varies by region. Digital purchases may not be available everywhere. Physical warranty valid globally.","account","hard"),
    ("Do you have a refer-a-friend program?","Yes! Both you and friend get $10 credit when they make first purchase of $50+. Find referral link in Account > Refer a Friend.","loyalty","easy"),
    ("How do I know if a product is authentic?","All products sold directly by us are 100% authentic, sourced from manufacturers or authorized distributors. Each product has unique authenticity verification code.","product","easy"),
    ("I need technical specifications for the Z-Pro model not on the product page.","Full technical specs document available as PDF under 'Specifications' tab on product page. Let me know specific specs you need.","product","medium"),
    ("Can I use my store credit and a credit card for the same purchase?","Yes, split payment available. Store credit applied automatically first, remaining balance charged to any accepted payment method.","payment","easy"),
    ("What happens if I'm not home when my package is delivered?","Carrier will attempt delivery 3 times, leave door tag, hold package at local facility for 5 business days. Manage preferences via tracking page.","delivery","easy"),
    ("I paid for express shipping but my order arrived late. Can I get shipping refund?","Yes, if delivered after guaranteed delivery date, you are entitled to full shipping cost refund. Contact us with order number.","shipping","medium"),
    ("Can I add items to an order I already placed?","Items cannot be added to a placed order. Place a new order. If first hasn't shipped, we can try to combine shipments and refund duplicate shipping.","order","medium"),
    ("Do you offer gift wrapping?","Yes, gift wrapping available for $4.99 per item. Select at checkout. Includes premium wrapping paper, ribbon, and personalized gift message card.","gifting","easy"),
    ("How do I unsubscribe from marketing emails?","Click 'Unsubscribe' link at bottom of any marketing email. Or go to Account Settings > Communication Preferences. Transactional emails will still be sent.","account","easy"),
    ("My product stopped working after 13 months. Is it still under warranty?","Standard warranty is 2 years, so your product is still covered. Contact support with order number and issue description. We will diagnose and arrange repair or replacement.","warranty","easy"),
    ("Can I get a refund if I just don't like the product?","Yes, you can return any product within 30 days for any reason. Items must be in original condition with all accessories. Return shipping is free.","returns","easy"),
    ("Do you have a mobile app?","Yes, our app is available for iOS (App Store) and Android (Google Play). Full shopping functionality, order tracking, account management, exclusive app-only deals.","general","easy"),
    ("I want to change my subscription from monthly to annual. How?","Go to Account > Subscription > Change Plan, select annual billing. Takes effect immediately. Annual billing saves 20%.","account","easy"),
    ("Are your products environmentally friendly?","We are committed to sustainability. 100% recyclable packaging. Product take-back program. Carbon-neutral shipping since 2024.","general","easy"),
    ("Can I pick up my order instead of having it shipped?","Yes, in-store pickup at our San Francisco and New York locations. Select 'Pick Up' at checkout. Ready within 2 hours for in-stock items. Bring ID and order confirmation.","shipping","easy"),
]

def gen_support_cases():
    return [{"case_id":i,"input":t[0],"expected_output":t[1],"metadata":{"category":t[2],"difficulty":t[3]}} for i,t in enumerate(SUPPORT_TPL)]

print("Support data loaded.")

# ===== RAG RESEARCH CASES =====
# Pattern A: High Correctness + High Grounding (20 cases)
RAG_A = [
    ("According to the 2025 annual report, what was the revenue growth rate?","The revenue growth rate was 24.3% year-over-year, driven primarily by cloud services and enterprise subscriptions.","2025 Annual Report: Revenue grew 24.3% YoY to $4.2B. Cloud services contributed 62% of total revenue, up from 54% in 2024.","2025 Annual Report, page 3: 'Revenue grew 24.3% year-over-year.'","financial"),
    ("What were the key findings of Smith et al. (2024) on battery degradation?","Smith et al. found lithium-ion batteries degrade 40% faster when charged above 90% capacity, with electrolyte decomposition as the primary mechanism.","Smith, J. et al. (2024). Journal of Energy Storage, 45, 102389. Batteries at 100% charge showed 40% faster loss vs 80% limit.","Smith et al. (2024), Abstract: 'batteries charged above 90% exhibited 40% accelerated degradation.'","research"),
    ("Summarize the IPCC AR6 sea level rise projections by 2100.","IPCC AR6 projects sea level rise of 0.28-0.55m under SSP1-1.9 and 0.63-1.01m under SSP5-8.5. Rate accelerating from 1.4mm/yr to 3.7mm/yr.","IPCC AR6 WG1: SSP1-1.9: 0.28-0.55m, SSP5-8.5: 0.63-1.01m by 2100. Rate: 1.4mm/yr (1901-1990) to 3.7mm/yr (2006-2018).","IPCC AR6 SPM Table SPM.1: SSP1-1.9 range 0.28-0.55m, SSP5-8.5 range 0.63-1.01m.","climate"),
    ("What is the capital of Mongolia?","The capital of Mongolia is Ulaanbaatar.","Mongolia: landlocked country in East Asia. Capital and largest city: Ulaanbaatar, home to half of 3.3 million population.","Encyclopedia: 'Ulaanbaatar is the capital of Mongolia.'","general"),
    ("What was Japan's GDP in 2024?","Japan's GDP in 2024 was approximately $4.2 trillion, making it the world's fourth-largest economy, with 0.9% real GDP growth.","IMF WEO Oct 2024: Japan GDP $4.21 trillion, 4th largest. Real GDP growth: 0.9%.","IMF WEO Oct 2024: 'Japan: GDP $4.21 trillion, growth 0.9%.'","economics"),
    ("What is the mechanism of CRISPR-Cas9 gene editing?","CRISPR-Cas9 uses a guide RNA to direct the Cas9 enzyme to a specific DNA sequence, creating a double-strand break repaired by NHEJ or HDR.","CRISPR-Cas9: gRNA directs Cas9 to complementary DNA. Cas9 creates DSB. Cell repairs via NHEJ or HDR.","Doudna & Charpentier (2014): 'Cas9 programmed by guide RNA to cleave specific DNA sequences.'","science"),
    ("What were the main causes of the 2008 financial crisis?","The 2008 crisis was caused by subprime mortgage lending, securitization of risky loans, excessive leverage, and insufficient regulatory oversight.","FCIC Report (2011): Subprime lending, MBS, excessive leverage, regulatory failures were primary causes.","FCIC Report (2011): 'The crisis was avoidable and caused by widespread failures in financial regulation.'","economics"),
    ("What is the difference between supervised and unsupervised learning?","Supervised learning uses labeled data to predict outputs; unsupervised learning finds patterns in unlabeled data without predefined outputs.","ML textbook: Supervised uses labeled data (input-output pairs). Unsupervised discovers structure in unlabeled data.","ML textbook ch1: 'Supervised learning uses labeled data; unsupervised learning uses unlabeled data.'","ai"),
    ("According to WHO, what are the leading risk factors for cardiovascular disease?","Leading risk factors: high blood pressure, tobacco use, high cholesterol, physical inactivity, unhealthy diet, obesity.","WHO Fact Sheet (2024): Hypertension, tobacco, hyperlipidemia, inactivity, unhealthy diet, obesity.","WHO Fact Sheet: 'Cardiovascular disease risk factors include hypertension, tobacco use, and unhealthy diet.'","health"),
    ("What did the 2024 Nobel Prize in Chemistry recognize?","Computational protein design and protein structure prediction using artificial intelligence.","Nobel Foundation: 2024 Chemistry Prize for computational protein design and AI-based protein structure prediction.","Nobel Prize announcement (2024): 'for computational protein design and protein structure prediction.'","science"),
    ("What is the EU Fit for 55 emission reduction target?","EU Fit for 55 targets a 55% reduction in greenhouse gas emissions by 2030 compared to 1990 levels.","EU Commission: Fit for 55 aims to reduce GHG emissions by 55% by 2030 vs 1990.","EU Commission: 'Fit for 55 targets 55% emission reduction by 2030.'","climate"),
    ("What is the significance of the Paris Agreement 1.5C target?","The 1.5C target limits global warming to 1.5C above pre-industrial levels. IPCC SR1.5 found impacts escalate significantly beyond 1.5C.","IPCC SR1.5 (2018): Limiting warming to 1.5C requires rapid, far-reaching transitions. At 2C, coral reefs face >99% loss vs 70-90% at 1.5C.","IPCC SR1.5 (2018): 'Limiting warming to 1.5C requires unprecedented transitions.'","climate"),
    ("What percentage of global electricity came from renewables in 2024?","Renewables generated approximately 30% of global electricity in 2024, with solar and wind contributing the majority of new capacity.","IEA Electricity 2024: Renewables reached 30% of global electricity generation. Solar PV additions grew 50% YoY.","IEA Electricity 2024: 'Renewables reached 30% of global electricity generation.'","energy"),
    ("What is quantum entanglement?","Quantum entanglement is when two or more particles become correlated such that the quantum state of each cannot be described independently, regardless of distance.","Physics: Entanglement occurs when particles interact such that their quantum states are interdependent. Einstein called it 'spooky action at a distance'.","Physics textbook: 'Quantum entanglement: particles share quantum states regardless of distance.'","physics"),
    ("How does mRNA vaccine technology work?","mRNA vaccines deliver messenger RNA instructing cells to produce a pathogen protein, triggering immune response without using the actual pathogen.","mRNA vaccines: deliver mRNA encoding pathogen protein. Cells produce protein. Immune system builds antibodies and T-cell response.","Kariko & Weissman (2005): 'Modified nucleosides in mRNA reduce innate immune activation.'","medicine"),
    ("What is dark matter?","Dark matter is invisible matter comprising about 27% of the universe's mass-energy. Evidence from galaxy rotation curves, gravitational lensing, and CMB.","Astrophysics: Dark matter ~27% of universe (vs 5% ordinary matter). Evidence: Vera Rubin's galaxy rotation curves, gravitational lensing, CMB anisotropies.","Astrophysics review: 'Dark matter comprises 27% of the universe's mass-energy content.'","astronomy"),
    ("What are the main provisions of GDPR?","GDPR: right to access (Art.15), right to erasure (Art.17), right to data portability (Art.20), explicit consent required (Art.7). Applies to any org processing EU data.","GDPR (2018): Key rights: access, rectification, erasure, restriction, portability, objection. Requires explicit consent, breach notification, DPO appointment.","GDPR Article 15: 'The data subject shall have the right to obtain confirmation as to whether personal data are being processed.'","law"),
    ("What is the current status of nuclear fusion research?","NIF achieved first net energy gain in Dec 2022 (3.15 MJ out from 2.05 MJ in). ITER expected first plasma in 2030s. Commercial fusion remains decades away.","NIF (Dec 2022): First controlled fusion ignition. 3.15 MJ output from 2.05 MJ input. ITER under construction in France.","DOE (Dec 2022): 'First fusion ignition achieved at National Ignition Facility.'","energy"),
    ("What is the economic impact of AI according to McKinsey?","McKinsey estimates generative AI could add $2.6-4.4 trillion annually to the global economy, with largest impact in customer operations, marketing, and software engineering.","McKinsey (2023): Generative AI could add $2.6-4.4 trillion annually. Top sectors: customer operations, marketing/sales, software engineering, R&D.","McKinsey (2023): 'Generative AI could add $2.6-4.4 trillion annually to the global economy.'","economics"),
    ("When was the Treaty of Westphalia signed and what did it establish?","The Treaty of Westphalia was signed in 1648, ending the Thirty Years' War and establishing state sovereignty and non-interference.","Peace of Westphalia (1648): Ended Thirty Years' War. Established territorial sovereignty, diplomatic equality. Birth of modern nation-state system.","Historical analysis: 'The Peace of Westphalia (1648) established territorial sovereignty.'","history"),
]

# Pattern B: High Correctness + Low Grounding (20 cases)
RAG_B = [
    ("What are the common side effects of metformin?","Common side effects include gastrointestinal issues: nausea, diarrhea, abdominal discomfort. Long-term use can cause vitamin B12 deficiency. Rarely, lactic acidosis in kidney patients.","FDA Drug Label: Diarrhea (53%), nausea/vomiting (26%), flatulence (12%). B12 deficiency (7% long-term). Lactic acidosis (0.03/1000 patient-years).","","medical"),
    ("Explain the significance of the Rosetta Stone.","Discovered in 1799, the Rosetta Stone was key to deciphering Egyptian hieroglyphics because it contained the same text in hieroglyphics, Demotic, and Ancient Greek.","The Rosetta Stone (196 BC) contains a decree in three scripts. Champollion deciphered hieroglyphics in 1822.","","history"),
    ("What is the capital of Burkina Faso?","The capital of Burkina Faso is Ouagadougou.","Burkina Faso is a landlocked country in West Africa. Capital: Ouagadougou, population ~2.8 million.","","general"),
    ("What is photosynthesis?","Photosynthesis: plants convert light energy, water, CO2 into glucose and oxygen using chlorophyll. Overall: 6CO2 + 6H2O + light -> C6H12O6 + 6O2.","Photosynthesis: Light-dependent reactions produce ATP/NADPH. Calvin cycle fixes CO2 into glucose. Occurs in chloroplasts.","","biology"),
    ("What is the Pythagorean theorem?","In a right triangle, the square of the hypotenuse equals the sum of squares of the other two sides: a^2 + b^2 = c^2.","Pythagorean theorem: a^2 + b^2 = c^2 for right triangles. Named after Pythagoras, known earlier in Babylon.","","math"),
    ("What is the speed of light in vacuum?","The speed of light in vacuum is exactly 299,792,458 meters per second (approximately 300,000 km/s).","Physics: c = 299,792,458 m/s (exact since 1983). A fundamental constant. Maximum speed of information.","","physics"),
    ("What caused the fall of the Roman Empire?","Multiple factors: economic troubles, overexpansion, military overspending, barbarian invasions, political instability. Traditional date: 476 CE.","Historians cite: economic decline, military overextension, barbarian pressure, political corruption, division of empire (395 CE).","","history"),
    ("What is the difference between DNA and RNA?","DNA: double-stranded, deoxyribose, A-T C-G. RNA: single-stranded, ribose, A-U C-G. DNA stores genetic info; RNA helps express it.","DNA: double-stranded, deoxyribose. RNA: single-stranded, ribose. Types: mRNA, tRNA, rRNA. Central dogma: DNA -> RNA -> protein.","","biology"),
    ("What is Occam's razor?","The simplest explanation is usually the best. Among competing hypotheses, prefer the one with fewest assumptions.","Occam's razor (lex parsimoniae): 'Entities should not be multiplied beyond necessity.' William of Ockham.","","philosophy"),
    ("What is the greenhouse effect?","Greenhouse gases trap heat in the atmosphere, warming Earth. Essential for life but intensified by human emissions causing global warming.","Solar radiation passes through atmosphere, Earth re-emits as IR. GHGs trap IR. Natural effect essential; anthropogenic enhancement causes climate change.","","climate"),
    ("What is blockchain technology?","Blockchain: distributed ledger where transactions are recorded in cryptographically linked blocks, creating an immutable chain across a decentralized network.","Blockchain: Decentralized, distributed ledger. Each block contains transactions, timestamp, hash of previous block. Consensus mechanisms ensure validity.","","technology"),
    ("What is the Turing test?","A test of machine intelligence: if a human evaluator cannot reliably distinguish machine from human in conversation, the machine passes. Proposed by Alan Turing in 1950.","Turing test (1950): 'Imitation game' - human judge converses with both machine and human. If judge cannot tell which is which, machine passes.","","ai"),
    ("What is the butterfly effect?","Small changes in initial conditions can lead to large-scale, unpredictable consequences in complex systems. Popularized by meteorologist Edward Lorenz.","Lorenz (1963): Tiny differences in initial conditions produce widely diverging outcomes in chaotic systems.","","science"),
    ("What is the difference between weather and climate?","Weather is short-term atmospheric conditions (hours to days). Climate is long-term average of weather patterns (30+ years).","Weather: short-term - temperature, humidity, precipitation. Climate: statistical average over 30+ years.","","climate"),
    ("What is Moore's law?","The number of transistors on a microchip doubles approximately every two years, leading to exponential growth in computing power.","Gordon Moore (1965): Transistor count doubles ~2 years. Drove exponential growth of computing for decades.","","technology"),
    ("What is the placebo effect?","Patients experience real symptom improvement after receiving a treatment with no active ingredient, driven by expectation and belief.","Placebo effect: Measurable improvement not attributable to treatment. Mediated by expectation, conditioning, neurobiological mechanisms.","","medical"),
    ("What is the prisoner's dilemma?","Game theory scenario where two individuals acting in self-interest produce a worse outcome than if they had cooperated.","Two prisoners decide to confess or stay silent. Mutual confession = worse outcome for both than mutual cooperation.","","economics"),
    ("What is the difference between GDP and GNP?","GDP measures production within a country's borders. GNP measures production by a country's citizens regardless of location.","GDP: domestic production. GNP: production by nationals. GNP = GDP + income from abroad - income paid to foreigners.","","economics"),
    ("What is epigenetics?","Study of heritable changes in gene expression without changes to DNA sequence. Mechanisms: DNA methylation, histone modification, non-coding RNAs.","Epigenetics: heritable phenotype changes without DNA alteration. DNA methylation, histone modification, non-coding RNA regulation.","","biology"),
    ("What is the Fermi paradox?","The contradiction between high probability of extraterrestrial civilizations and lack of evidence. Possible explanations: Great Filter, we're early, they're avoiding us.","Fermi paradox: If universe is vast and old, why no alien contact? Great Filter: civilizations are rare or self-destruct.","","astronomy"),
]

# Pattern C: Low Correctness + High Grounding (15 cases)
RAG_C = [
    ("According to the 2025 annual report, what was the profit margin?","The profit margin was 35%, which was exceptional.","2025 Annual Report: Net profit margin was 18.2%, up from 16.7% in 2024. Operating margin: 22.5%. Gross margin: 58.3%.","2025 Annual Report, page 5: 'Net profit margin was 18.2%.'","financial"),
    ("What did the IPCC say about Arctic sea ice?","The IPCC said Arctic sea ice is completely gone in summer.","IPCC AR6: Arctic sea ice extent decreased ~40% in September since 1979. Under SSP5-8.5, practically ice-free before 2050. Under SSP1-2.6, some summer ice remains.","IPCC AR6 SPM B.2.5: 'Arctic sea ice area decreased ~40% in September.'","climate"),
    ("What was the conclusion of the Minnesota Starvation Experiment?","The experiment proved starvation has no long-term psychological effects.","Keys et al. (1950): Semi-starvation produced severe depression, food obsession, social withdrawal, and lasting behavioral changes in 36 subjects.","Keys et al. (1950): 'Prolonged semi-starvation produced significant psychological and behavioral changes.'","research"),
    ("What is the current population of Tokyo?","Tokyo has a population of about 5 million people.","UN World Urbanization Prospects (2024): Tokyo metropolitan area: 37.1 million. Largest urban agglomeration. 23 special wards: 9.7 million.","UN World Urbanization Prospects (2024): 'Tokyo: 37.1 million in metropolitan area.'","general"),
    ("What is the recommended daily intake of vitamin D?","The recommended daily intake is 5000 IU for all adults.","NIH: RDA for vitamin D is 600 IU (15 mcg) for adults 19-70, 800 IU for 71+. Upper limit: 4000 IU/day.","NIH: 'RDA for vitamin D is 600 IU for adults 19-70 years.'","health"),
    ("What did the Mueller Report conclude about obstruction of justice?","The Mueller Report concluded there was definitely obstruction of justice.","Mueller Report Vol. II: 'while this report does not conclude that the President committed a crime, it also does not exonerate him.' Outlined 10 episodes of potential obstruction.","Mueller Report Vol. II: 'Does not conclude that the President committed a crime, also does not exonerate him.'","law"),
    ("What is the average surface temperature of Venus?","Venus has an average surface temperature of about 250 degrees Celsius.","NASA: Venus average surface temperature is 462C (864F), hot enough to melt lead. Hottest planet due to runaway greenhouse effect.","NASA: 'Venus average surface temperature: 462C (864F).'","astronomy"),
    ("What percentage of the Amazon rainforest has been deforested?","Only about 5% of the Amazon rainforest has been deforested.","INPE/Brazil: Approximately 17-20% of original Amazon deforested. 13,000+ km2 lost in 2021. Scientists warn 20-25% could trigger dieback.","INPE: 'Approximately 17-20% of the original Amazon has been deforested.'","climate"),
    ("What is the atomic number of gold?","Gold has an atomic number of 47.","Periodic table: Gold (Au) has atomic number 79. Silver (Ag) is atomic number 47.","Periodic table: 'Au (Gold): atomic number 79.'","science"),
    ("What is the speed of sound in air?","The speed of sound in air is about 500 meters per second.","Physics: Speed of sound in dry air at 20C is ~343 m/s (1235 km/h). At 0C: ~331 m/s.","Physics reference: 'Speed of sound in air at 20C: 343 m/s.'","physics"),
    ("What is the deepest point in the ocean?","The deepest point is the Puerto Rico Trench, at about 8,000 meters.","NOAA: Challenger Deep in Mariana Trench is deepest at ~10,935m (35,876 ft). Puerto Rico Trench: ~8,400m.","NOAA: 'Challenger Deep in the Mariana Trench: 10,935 meters.'","general"),
    ("What is the half-life of carbon-14?","Carbon-14 has a half-life of about 1000 years.","Nuclear physics: Carbon-14 half-life is 5,730 +/- 40 years. Used in radiocarbon dating up to ~50,000 years.","Physics reference: 'Carbon-14 half-life: 5,730 years.'","science"),
    ("How many member states are in the United Nations?","The United Nations has about 150 member states.","UN: As of 2024, there are 193 member states. Most recent: South Sudan (2011). 2 observer states.","UN: '193 member states as of 2024.'","general"),
    ("What is the boiling point of water at sea level?","Water boils at 90 degrees Celsius at sea level.","Physics: Pure water at standard atmospheric pressure (sea level) boils at exactly 100C (212F).","Physics reference: 'Water boiling point at sea level: 100C (212F).'","science"),
    ("How many bones are in the adult human body?","The adult human body has about 150 bones.","Anatomy: Adult human skeleton has 206 bones. Infants have ~270, which fuse during growth.","Anatomy reference: 'Adult human skeleton: 206 bones.'","health"),
]

# Pattern D: Low Correctness + Low Grounding (15 cases)
RAG_D = [
    ("What was the main cause of World War I?","World War I was primarily caused by economic competition between Britain and France.","Fritz Fischer (1961): Germany bore primary responsibility. German leaders pursued 'grab for world power'.","","history"),
    ("How does the Krebs cycle contribute to cellular respiration?","The Krebs cycle primarily produces carbon dioxide for photosynthesis.","Biochemistry: Krebs cycle oxidizes acetyl-CoA to CO2, producing NADH, FADH2, GTP. Feeds electron transport chain for ATP production.","","biology"),
    ("What is the evidence for the Big Bang theory?","The main evidence is that stars are moving away from each other.","Cosmology: Evidence: Hubble's law, CMB radiation (Penzias & Wilson 1965), light element abundance, large-scale structure.","","astronomy"),
    ("What is the function of the amygdala?","The amygdala is primarily responsible for language processing and speech production.","Neuroscience: Amygdala is key limbic structure for emotion processing, especially fear/threat detection. Language: Broca's and Wernicke's areas.","","neuroscience"),
    ("How does a nuclear reactor generate electricity?","Nuclear reactors generate electricity by directly burning uranium fuel rods.","Nuclear engineering: Controlled fission of U-235 produces heat. Heat converts water to steam, driving turbines. Uranium does not 'burn' chemically.","","physics"),
    ("What is the significance of the Magna Carta?","The Magna Carta established democracy in England with universal voting rights.","History: Magna Carta (1215) established the king was subject to law. Did NOT establish democracy or universal suffrage.","","history"),
    ("What is the role of mitochondria?","Mitochondria are primarily responsible for protein synthesis.","Cell biology: Mitochondria are the 'powerhouses' - aerobic respiration and ATP production. Protein synthesis occurs in ribosomes.","","biology"),
    ("What is the theory of continental drift?","Continental drift was proposed by Charles Darwin based on finch observations.","Geology: Continental drift proposed by Alfred Wegener (1912). Evidence: fit of continents, matching fossils. Darwin proposed evolution.","","geology"),
    ("What is the difference between Type 1 and Type 2 diabetes?","Type 1 diabetes is caused by eating too much sugar as a child.","Medicine: Type 1 is autoimmune destruction of pancreatic beta cells. Type 2 involves insulin resistance. Diet does NOT cause Type 1.","","medical"),
    ("What is the main function of the Federal Reserve?","The Federal Reserve's main job is to print money for the government.","Economics: Fed conducts monetary policy (interest rates, money supply), supervises banks, maintains financial stability. Does NOT print money for government spending.","","economics"),
    ("What is the composition of the Sun?","The Sun is made mostly of burning fire and lava.","Astrophysics: Sun is ~73% hydrogen, ~25% helium, ~2% heavier elements by mass. A plasma, not fire. Energy from nuclear fusion.","","astronomy"),
    ("What is the role of the hippocampus?","The hippocampus is primarily responsible for regulating heart rate and breathing.","Neuroscience: Hippocampus is critical for memory formation and spatial navigation. Heart rate/breathing regulated by brainstem (medulla oblongata).","","neuroscience"),
    ("What is the Hardy-Weinberg principle?","The Hardy-Weinberg principle states that evolution always occurs in large populations.","Genetics: Hardy-Weinberg equilibrium describes conditions where allele frequencies remain constant (NO evolution): large population, no mutation, random mating, no selection, no gene flow.","","biology"),
    ("What is the photoelectric effect?","The photoelectric effect is when light heats up a metal surface until it melts.","Physics: Photoelectric effect: electrons are emitted from a material when light of sufficient frequency strikes it. Einstein explained it using photon theory (1905).","","physics"),
    ("How many planets are in our solar system?","There are 9 planets in our solar system, including Pluto.","Astronomy: IAU (2006): 8 planets. Pluto is classified as a dwarf planet. The 8 planets: Mercury, Venus, Earth, Mars, Jupiter, Saturn, Uranus, Neptune.","","astronomy"),
]

# Pattern E: High Correctness + Low Citation Accuracy (10 cases)
RAG_E = [
    ("What is the recommended daily water intake?","The recommended daily water intake is about 2-3 liters for adults, though needs vary by activity level, climate, and individual factors.","Institute of Medicine: Adequate intake is 3.7L/day for men, 2.7L/day for women (including water from food).","","health"),
    ("What is the Kuiper Belt?","The Kuiper Belt is a region beyond Neptune containing icy bodies and dwarf planets, including Pluto. It is similar to the asteroid belt but much larger.","NASA: Kuiper Belt extends from ~30-50 AU from Sun. Contains icy bodies, dwarf planets (Pluto, Eris, Makemake). Source of short-period comets.","","astronomy"),
    ("What is the difference between mitosis and meiosis?","Mitosis produces two identical diploid daughter cells for growth and repair. Meiosis produces four genetically diverse haploid gametes for sexual reproduction.","Mitosis: 1 division, 2 diploid cells, genetically identical. Meiosis: 2 divisions, 4 haploid cells, genetic variation via crossing over.","","biology"),
    ("What is the tragedy of the commons?","The tragedy of the commons is when individuals acting in self-interest deplete a shared resource, even when it's against everyone's long-term interest.","Garrett Hardin (1968): Shared resources are depleted when individuals act independently according to self-interest. Examples: overfishing, deforestation, air pollution.","","economics"),
    ("What is the Doppler effect?","The Doppler effect is the change in frequency of a wave relative to an observer moving relative to the source. Examples: ambulance siren pitch change, redshift of distant galaxies.","Physics: Wave frequency increases as source approaches, decreases as it recedes. Used in astronomy (redshift/blueshift), radar, medical ultrasound.","","physics"),
    ("What is the Heisenberg uncertainty principle?","The Heisenberg uncertainty principle states that you cannot simultaneously know both the exact position and exact momentum of a particle.","Quantum mechanics: Delta x * Delta p >= h/4pi. The more precisely position is known, the less precisely momentum can be known, and vice versa.","","physics"),
    ("What is the bystander effect?","The bystander effect is the phenomenon where individuals are less likely to help a victim when other people are present, due to diffusion of responsibility.","Social psychology: Darley & Latane (1968). More bystanders = less likely any individual helps. Diffusion of responsibility, pluralistic ignorance.","","psychology"),
    ("What is the difference between innate and adaptive immunity?","Innate immunity is the rapid, non-specific first line of defense. Adaptive immunity is slower but highly specific, with immunological memory for future protection.","Innate: physical barriers, phagocytes, NK cells, complement. Immediate response. Adaptive: B cells (antibodies), T cells. Takes days. Immunological memory.","","medicine"),
    ("What is the Nash equilibrium?","Nash equilibrium is a game theory concept where no player can benefit by changing only their own strategy while others keep theirs unchanged.","John Nash (1950): Each player's strategy is optimal given others' strategies. No unilateral deviation is profitable.","","economics"),
    ("What is the difference between a virus and a bacterium?","Viruses are non-living particles requiring a host cell to replicate. Bacteria are single-celled living organisms that can reproduce independently. Antibiotics work on bacteria, not viruses.","Viruses: genetic material in protein coat, need host cell. Bacteria: complete cells with cell wall, independent reproduction. Antibiotics target bacterial structures.","","medicine"),
]

def gen_rag_cases():
    cases = []
    for i, (q, exp, ctx, ev, cat) in enumerate(RAG_A):
        cases.append({"case_id":len(cases),"input":q,"expected_output":exp,"retrieval_context":ctx,"evidence":[ev] if ev else [],
                      "metadata":{"category":cat,"pattern":"A_high_correct_high_ground"}})
    for i, (q, exp, ctx, ev, cat) in enumerate(RAG_B):
        cases.append({"case_id":len(cases),"input":q,"expected_output":exp,"retrieval_context":ctx,"evidence":[],
                      "metadata":{"category":cat,"pattern":"B_high_correct_low_ground"}})
    for i, (q, exp, ctx, ev, cat) in enumerate(RAG_C):
        cases.append({"case_id":len(cases),"input":q,"expected_output":exp,"retrieval_context":ctx,"evidence":[ev] if ev else [],
                      "metadata":{"category":cat,"pattern":"C_low_correct_high_ground"}})
    for i, (q, exp, ctx, ev, cat) in enumerate(RAG_D):
        cases.append({"case_id":len(cases),"input":q,"expected_output":exp,"retrieval_context":ctx,"evidence":[],
                      "metadata":{"category":cat,"pattern":"D_low_correct_low_ground"}})
    for i, (q, exp, ctx, ev, cat) in enumerate(RAG_E):
        cases.append({"case_id":len(cases),"input":q,"expected_output":exp,"retrieval_context":ctx,"evidence":[],
                      "metadata":{"category":cat,"pattern":"E_high_correct_low_citation"}})
    return cases

print("RAG data loaded.")

# ===== TOOL AGENT CASES (40) =====
TOOL_CASES = [
    ("Find the cheapest flight from New York to London for August 20-27.","The cheapest round-trip flight is $487 on Norse Atlantic Airways, departing JFK at 11:30 PM and arriving LGW at 11:15 AM. Alternative: $512 on British Airways from EWR.","flight_search","search_flight(origin='JFK',dest='LON',date='2026-08-20',return_date='2026-08-27') -> 15 results; filter by price; cheapest: Norse Atlantic $487","easy"),
    ("Find a hotel in Paris under $200/night near the Eiffel Tower for 3 nights starting August 15.","Hotel Le Walt (4-star, 0.3mi from Eiffel Tower): $189/night. Hotel Eiffel Blomet (3-star, 0.5mi): $165/night. Hotel Ares Eiffel (4-star, 0.4mi): $195/night.","hotel_search","search_hotel(location='Paris',near='Eiffel Tower',max_price=200,check_in='2026-08-15',nights=3) -> 8 results","easy"),
    ("Plan a 5-day trip to Tokyo with a budget of $2000 including flights and hotel.","Flight: LAX-NRT round-trip $892 (Zipair). Hotel: APA Hotel Shinjuku $78/night x5 = $390. Remaining: $718 for food, transport, activities. Total: $1282 + $718 = $2000.","multi_step","search_flight(origin='LAX',dest='TYO') -> $892; search_hotel(location='Shinjuku',max_price=100) -> $78; calculate_budget(total=2000)","medium"),
    ("Compare the total cost of flying vs taking the train from Amsterdam to Paris for 2 people.","Flight: AMS-CDG $89/person x2 = $178 + $40 airport transfer = $218 total, 3.5 hours door-to-door. Train: Thalys $69/person x2 = $138, 3.3 hours city center to city center. Train is cheaper by $80.","comparison","search_flight(origin='AMS',dest='PAR',passengers=2) -> $89/person; search_train(origin='AMS',dest='PAR',passengers=2) -> $69/person; compare()","medium"),
    ("Find a restaurant in Barcelona with vegetarian options, rating above 4.5, open on Sunday.","Teresa Carles (4.7 stars, vegetarian): Carrer de Jovellanos 2. Flax & Kale (4.6 stars, flexitarian): Carrer dels Tallers 74. Rasoterra (4.5 stars, vegetarian): Carrer del Palau 5.","restaurant_search","search_restaurant(location='Barcelona',dietary='vegetarian',min_rating=4.5,open_day='Sunday') -> 3 results","easy"),
    ("What's the weather forecast for Bangkok for the next 3 days and should I pack an umbrella?","Aug 20: 33C, 80% chance thunderstorms. Aug 21: 34C, 60% chance rain. Aug 22: 32C, 70% chance thunderstorms. Yes, definitely pack an umbrella - monsoon season with daily rain expected.","weather_check","get_weather(location='Bangkok',days=3) -> daily forecasts with precipitation %","easy"),
    ("Convert 500 Euros to Japanese Yen and tell me if that's enough for a week of meals in Tokyo.","500 EUR = 81,500 JPY (rate 163:1). Average meal in Tokyo: breakfast 500-800 JPY, lunch 1000-1500 JPY, dinner 1500-3000 JPY. Weekly estimate: 28,000-42,000 JPY. 500 EUR is more than enough for a week of meals.","currency_conversion","convert_currency(amount=500,from='EUR',to='JPY') -> 81500; search_cost_of_living(city='Tokyo',category='meals')","medium"),
    ("Find the best travel insurance for a 2-week trip to Southeast Asia covering medical and theft.","World Nomads Explorer Plan: $89 (covers medical up to $100K, theft up to $3K, adventure activities). SafetyWing Nomad Insurance: $56/month (medical up to $250K, theft up to $3K). Allianz OneTrip Prime: $95 (medical $50K, theft $1K).","insurance_search","search_insurance(destination='Southeast Asia',duration_days=14,coverage=['medical','theft']) -> 3 results","medium"),
    ("Book a rental car in Lisbon for 4 days, automatic transmission, pickup at airport.","Sixt: VW Golf automatic, $42/day, unlimited mileage. Europcar: Renault Megane automatic, $38/day, 1000km included. Hertz: Ford Focus automatic, $45/day, unlimited mileage. Best value: Europcar $152 total.","car_rental","search_car_rental(location='Lisbon Airport',days=4,transmission='automatic') -> 3 results","easy"),
    ("Find a direct flight from Chicago to Dublin, any date in September, under $500.","Aer Lingus: ORD-DUB direct, Sep 12-19, $478 round-trip. United Airlines: ORD-DUB direct, Sep 15-22, $495 round-trip. No other direct options under $500 in September.","flight_search","search_flight(origin='ORD',dest='DUB',direct_only=True,month='2026-09',max_price=500) -> 2 results","medium"),
    ("I need a visa for Vietnam. What are the requirements for a US citizen staying 10 days?","US citizens: e-Visa available for stays up to 90 days. Apply online at official portal. Requirements: passport valid 6+ months beyond arrival, digital photo, $25 fee. Processing: 3 business days. No visa on arrival without pre-approval letter.","visa_check","check_visa_requirements(nationality='US',destination='Vietnam',duration_days=10) -> e-Visa eligible","easy"),
    ("Find the best SIM card for 2 weeks in Japan with 10GB data.","Sakura Mobile: 15GB, $35, pickup at Narita/Haneda. Mobal: 8GB, $28, delivery to hotel. B-Mobile: 10GB, $30, pickup at airport kiosks. Best: B-Mobile for 10GB at $30.","sim_card_search","search_sim(destination='Japan',data_gb=10,duration_days=14) -> 3 results","easy"),
    ("Plan a route from Berlin to Prague to Vienna to Budapest by train, 10 days total.","Day 1-3 Berlin, train to Prague (4.5h, $39). Day 3-5 Prague, train to Vienna (4h, $29). Day 5-7 Vienna, train to Budapest (2.5h, $25). Day 7-10 Budapest. Total train cost: $93.","multi_city_route","search_train_route(cities=['Berlin','Prague','Vienna','Budapest'],total_days=10) -> route with segments","hard"),
    ("Find a pet-friendly hotel in Portland, OR with parking, under $150/night, for 2 nights.","Hotel deLuxe (4-star): $145/night, pet fee $25, valet parking $35. Kimpton RiverPlace (4-star): $149/night, no pet fee, parking $30. McMenamins Crystal Hotel (3-star): $120/night, pet fee $15, lot parking $20.","hotel_search","search_hotel(location='Portland OR',pet_friendly=True,parking=True,max_price=150,nights=2) -> 3 results","easy"),
    ("What's the cheapest way to get from London Heathrow to central London for a family of 4?","Heathrow Express: 25/person = 100 total (15 min). Elizabeth Line: 12.80/person = 51.20 total (30 min). Piccadilly Line (Tube): 5.60/person = 22.40 total (50 min). Taxi: 60-90 total (45-60 min). Cheapest: Piccadilly Line at 22.40.","transport_comparison","search_transport(origin='LHR',destination='Central London',passengers=4) -> compare modes","medium"),
    ("Find a yoga retreat in Bali for 5 days, all-inclusive, under $800.","Serenity Eco Guesthouse (Canggu): 5-day yoga retreat $650 incl. accommodation, 2 yoga classes/day, breakfast, 1 spa treatment. Blooming Lotus Yoga (Ubud): $750 incl. accommodation, 3 classes/day, all meals, meditation.","activity_search","search_retreat(location='Bali',type='yoga',duration_days=5,max_price=800,all_inclusive=True) -> 2 results","medium"),
    ("Is it safe to travel to Cairo right now? Check travel advisories.","US State Dept: Level 3 - Reconsider Travel (increased risk of terrorism). UK FCO: Advise against all travel to some areas, rest is orange (essential travel only). Current situation: heightened security, avoid demonstrations, stick to tourist areas.","safety_check","check_travel_advisory(destination='Egypt') -> US Level 3, UK orange; get_safety_tips() -> advice","medium"),
    ("Find a cruise from Miami to the Bahamas for 4 nights in December, balcony cabin.","Royal Caribbean: Navigator of the Seas, Dec 10-14, balcony $1,198/person. Carnival: Conquest, Dec 8-12, balcony $879/person. Norwegian: Sky, Dec 14-18, balcony $1,049/person. Best value: Carnival $879.","cruise_search","search_cruise(origin='Miami',destination='Bahamas',nights=4,month='December',cabin='balcony') -> 3 results","easy"),
    ("What vaccines do I need for a trip to Kenya including a safari?","Required: Yellow Fever (certificate required if arriving from endemic country). Recommended: Hepatitis A, Typhoid, Tetanus, Polio, Meningitis, Rabies (for safari). Malaria prophylaxis strongly recommended. Consult travel clinic 4-6 weeks before departure.","health_check","check_vaccines(destination='Kenya',activities=['safari']) -> required and recommended list","easy"),
    ("Find the best exchange rate for USD to Thai Baht and where to exchange in Bangkok.","Current rate: 1 USD = 35.2 THB. SuperRich Thailand (head office): 35.15 THB, best rates. Kasikorn Bank: 34.80 THB. Airport kiosks: 33.50 THB (avoid). Recommendation: exchange small amount at airport, rest at SuperRich downtown.","currency_exchange","get_exchange_rate(from='USD',to='THB') -> 35.2; search_exchange_locations(city='Bangkok') -> ranked","easy"),
    ("Book a train from Madrid to Barcelona for tomorrow morning, prefer window seat.","Renfe AVE: Madrid Atocha to Barcelona Sants. Options: 8:00 AM (arrive 10:30 AM), window seat 21A available, 67. 9:30 AM (arrive 12:00 PM), window seat 15A available, 54. Booked: 9:30 AM, seat 15A, 54.","train_booking","search_train(origin='Madrid',dest='Barcelona',date='tomorrow',time='morning',seat_pref='window') -> book","medium"),
    ("I'm in Rome and want a day trip to Pompeii. What are my options?","Train: Roma Termini to Napoli Centrale (1h10m, 45), then Circumvesuviana to Pompeii (35min, 3.60). Total: 97.20 round-trip. Guided tour from Rome: 129 incl. transport, guide, entry. Rent car: 60/day + 40 fuel + 16 parking + 16 entry = 132. Best: train for flexibility, tour for convenience.","day_trip_planning","search_transport(origin='Rome',dest='Pompeii',type='day_trip') -> train, tour, car options","medium"),
    ("Find the best travel credit card with no foreign transaction fees and good travel insurance.","Chase Sapphire Preferred: no foreign fees, primary rental car insurance, trip cancellation $10K. Capital One Venture: no foreign fees, travel accident insurance, rental car coverage. Amex Platinum: no foreign fees, comprehensive travel insurance, lounge access.","credit_card_search","search_credit_card(features=['no_foreign_fee','travel_insurance']) -> ranked","medium"),
    ("What's the tip etiquette in Japan, Italy, and the US?","Japan: No tipping - considered rude. Italy: Service charge (servizio) often included. Round up or leave 5-10% for exceptional service. US: 15-20% standard at restaurants, $1-2 per drink at bar, 10-15% for taxi.","cultural_info","get_cultural_info(countries=['Japan','Italy','US'],topic='tipping') -> etiquette guide","easy"),
    ("Find an all-inclusive resort in Cancun for 5 nights, adults-only, beachfront, under $2000 total.","Secrets The Vine (5-star): $1,850 all-inclusive, beachfront, adults-only. Live Aqua (5-star): $1,980 all-inclusive, beachfront, adults-only. Sun Palace (4-star): $1,620 all-inclusive, beachfront, adults-only, couples-only.","resort_search","search_resort(location='Cancun',nights=5,adults_only=True,beachfront=True,max_price=2000,all_inclusive=True) -> 3 results","easy"),
    ("Plan a trip to see the Northern Lights in Iceland, 4 days, including flights from Boston.","Flight: BOS-KEF round-trip $498 (Icelandair). Hotel: CenterHotel Laugavegur $145/night x4 = $580. Northern Lights tour: $85/person. Blue Lagoon: $65. Total: $1,228/person. Best time: September-March.","trip_planning","search_flight(origin='BOS',dest='KEF') -> $498; search_hotel() -> $145; search_activities(type='northern_lights') -> $85","hard"),
    ("What's the cheapest month to fly to Sydney from Los Angeles?","February: $890 avg (summer in Australia, low demand from US). May: $920. August: $950. Peak: December ($1,450). Cheapest: February. Book 3-4 months ahead for best rates.","price_analysis","search_flight_prices(origin='LAX',dest='SYD',year=2026) -> monthly averages","medium"),
    ("Find a luggage storage service near Tokyo Station for 8 hours.","Sagawa Express (Tokyo Station): 500 JPY/bag/day. Ecbo Cloak: 600 JPY/bag/day, multiple locations. Coin Lockers: 300-700 JPY depending on size, limited availability. Best: Ecbo Cloak for guaranteed space.","service_search","search_luggage_storage(location='Tokyo Station',duration_hours=8) -> options","easy"),
    ("I need to cancel my flight to Paris due to a medical emergency. What are my rights?","Check your ticket type: refundable vs non-refundable. Non-refundable: may get credit minus cancellation fee ($200-500). Medical emergency: contact airline with doctor's note, some waive fees. Travel insurance with 'cancel for any reason' covers this. Check credit card travel protection.","policy_check","check_cancellation_policy(booking_type='flight',reason='medical_emergency') -> rights and options","medium"),
    ("Compare Uber vs taxi vs public transit from JFK to Times Square for 1 person at 5 PM.","Uber X: $65-85, 45-75 min. Yellow Taxi: $52 flat fare + toll + tip = $70, 45-75 min. Public Transit: AirTrain to Jamaica ($8) + LIRR to Penn Station ($10.75) + walk = $18.75, 50-60 min. Best: Public transit for cost, taxi for convenience.","transport_comparison","compare_transport(origin='JFK',dest='Times Square',passengers=1,time='17:00') -> multi-mode","medium"),
    ("Find a coworking space in Chiang Mai with good WiFi, monthly membership under $150.","Punspace (Nimman): $120/month, 100Mbps, 24/7 access, free coffee. CAMP (Maya Mall): $90/month, 200Mbps, 24/7, standing desks. Hub53 (Nimman): $140/month, 150Mbps, pool access, events.","coworking_search","search_coworking(location='Chiang Mai',wifi_min_mbps=50,max_price_monthly=150) -> 3 results","easy"),
    ("What power adapters do I need for UK, UAE, and South Africa?","UK: Type G (3 rectangular pins), 230V. UAE: Type G (same as UK), 230V. South Africa: Type M (3 round pins, large) or Type D (3 round pins, small), 230V. You need: Type G adapter for UK/UAE, Type M adapter for South Africa.","adapter_check","check_power_adapters(countries=['UK','UAE','South Africa']) -> adapter types and voltages","easy"),
    ("Find a scuba diving certification course in Koh Tao, Thailand, 4 days, under $400.","Ban's Diving Resort: PADI Open Water, 4 days, $350 incl. accommodation. Crystal Dive: PADI Open Water, 4 days, $320, accommodation extra $50. Simple Life Divers: SSI Open Water, 4 days, $295, 4 nights dorm $40.","activity_search","search_course(location='Koh Tao',type='scuba',certification='open_water',max_price=400) -> 3 results","medium"),
    ("Emergency: I lost my passport in Berlin. What do I do?","1. File a police report immediately at nearest station. 2. Contact your embassy/consulate: US citizens contact US Embassy Berlin (+49-30-8305-0). 3. Apply for emergency passport (same-day, $165). 4. Bring: police report, passport photo, ID, flight itinerary. 5. Emergency passport valid for 1 year.","emergency","get_emergency_info(location='Berlin',issue='lost_passport') -> step-by-step guide","hard"),
    ("Plan a 3-day itinerary for Seoul mixing culture, food, and shopping.","Day 1 (Culture): Gyeongbokgung Palace (9-11), Insadong (11-2), Bukchon Hanok Village (2-5), Myeongdong Night Market (6-9). Day 2 (Food): Gwangjang Market breakfast, Korean cooking class (11-2), Hongdae street food tour (3-6), Korean BBQ dinner. Day 3 (Shopping): Myeongdong cosmetics (10-1), Gangnam boutiques (2-5), COEX Mall (5-8), Han River picnic.","itinerary_planning","plan_itinerary(location='Seoul',days=3,themes=['culture','food','shopping'])","hard"),
    ("Find the best airport lounge access at Singapore Changi for a 6-hour layover.","Plaza Premium Lounge (T1): $35/3hrs, showers, food, WiFi. SATS Premier Lounge (T2): $40/3hrs, nap rooms, bar. Ambassador Transit Lounge (T3): $38/3hrs, pool, gym, showers. Priority Pass covers all three.","lounge_search","search_airport_lounge(airport='SIN',duration_hours=6) -> options with amenities","easy"),
    ("Book a multi-city trip: NYC to London (3 days), London to Dubai (4 days), Dubai to NYC.","Flight 1: JFK-LHR, Aug 5, $389 (Norse). Hotel London: Premier Inn County Hall $120/night x3. Flight 2: LHR-DXB, Aug 8, $345 (Emirates). Hotel Dubai: Rove Downtown $85/night x4. Flight 3: DXB-JFK, Aug 12, $620 (Emirates). Total flights: $1,354. Total hotels: $700. Grand total: $2,054.","multi_city_booking","multi_city: search_flights for each leg, search_hotels for each city, calculate total","hard"),
    ("What's the best way to get mobile data across 5 European countries in 2 weeks?","Orange Holiday Europe: 20GB, $49.90, 14 days, covers 30 countries. Holafly eSIM: unlimited data, $47, 15 days, 32 countries. Airalo Discover: 10GB, $37, 30 days, 38 countries. Best: Orange for physical SIM, Holafly for eSIM.","sim_compare","search_sim(destinations=['Europe'],data_gb=15,duration_days=14,multi_country=True) -> compare","medium"),
    ("Find a sustainable/eco-friendly hotel in Costa Rica near a national park.","Lapa Rios Lodge (Osa Peninsula): $380/night, carbon neutral, wildlife conservation. Pacuare Lodge (Turrialba): $420/night, solar powered, river rafting access. Finca Rosa Blanca (Heredia): $250/night, organic coffee farm, near Poas Volcano.","hotel_search","search_hotel(location='Costa Rica',eco_certified=True,near_national_park=True) -> 3 results","medium"),
    ("What are the COVID entry requirements for Japan as of August 2026?","Japan: No COVID test or vaccination proof required for entry (as of April 2026). Visit Japan Web registration recommended for faster immigration. Standard visa rules apply. Check MHLW website for latest updates before travel.","health_check","check_entry_requirements(destination='Japan',date='2026-08') -> current rules","easy"),
]

def gen_tool_cases():
    return [{"case_id":i,"input":t[0],"expected_output":t[1],"category":t[2],"tool_trace":t[3],"difficulty":t[4]} for i,t in enumerate(TOOL_CASES)]

print("All data generators loaded.")

# ===== MAIN EXECUTION =====

def main():
    print("=" * 60)
    print("EvalForge Demo Seed Data Generator")
    print("=" * 60)

    # --- 1. Create Datasets ---
    print("\n[1/4] Creating datasets...")

    # Customer Support
    support_v1 = gen_support_cases()
    support_v2 = [dict(c) for c in support_v1]
    support_v2[6] = dict(support_v2[6], expected_output="Refunds take 5-7 business days for credit cards, 1-2 days for PayPal, up to 10 days for bank transfers. Contact us if not received after 10 business days.")
    support_v2[15] = dict(support_v2[15], expected_output="Yes, Family plan ($39.99/mo) supports up to 6 members with individual accounts, all Premium features, parental controls, 200GB shared storage.")
    support_v2[24] = dict(support_v2[24], expected_output="I can confirm there is no truth to rumors about us going out of business. We are financially stable with strong growth.")
    support_v2[40] = dict(support_v2[40], expected_output="If not yet shipped, contact us with order number and correct size. If in fulfillment, we'll arrange free exchange with prepaid return label.")
    support_v2[58] = dict(support_v2[58], expected_output="Our packaging is 100% recyclable. We offer a take-back program and carbon-neutral shipping since 2024.")

    ds_support_v1_h = create_dataset("customer_support_v1", "Customer Support Q&A v1",
        "60 realistic customer support cases covering policy, account, shipping, returns, payment, edge cases, multi-turn context, and hallucination-prone questions.",
        support_v1, "2026-08-05T10:00:00Z")
    ds_support_v2_h = create_dataset("customer_support_v2", "Customer Support Q&A v2",
        "Refined v2 dataset with improved policy wording, clarified edge cases, and 5 updated cases based on v1 evaluation feedback.",
        support_v2, "2026-08-12T10:00:00Z")
    print("  customer_support_v1:", len(support_v1), "cases")
    print("  customer_support_v2:", len(support_v2), "cases")

    # RAG Research
    rag_v1 = gen_rag_cases()
    # v2: swap 5 cases from pattern C to pattern A (improved correctness)
    rag_v2 = [dict(c) for c in rag_v1]
    # Fix 5 pattern C cases to have correct answers
    rag_v2[40] = dict(rag_v2[40], expected_output="The 2025 annual report shows net profit margin was 18.2%, up from 16.7% in 2024, with operating margin of 22.5%.", metadata={"category":"financial","pattern":"A_high_correct_high_ground"}, evidence=["2025 Annual Report, page 5: 'Net profit margin was 18.2%'."])
    rag_v2[41] = dict(rag_v2[41], expected_output="IPCC AR6 projects the Arctic could be practically ice-free in September before 2050 under SSP5-8.5, though some summer ice remains under SSP1-2.6.", metadata={"category":"climate","pattern":"A_high_correct_high_ground"}, evidence=["IPCC AR6 B.2.5: 'Practically ice-free before 2050 under SSP5-8.5.'"])
    rag_v2[43] = dict(rag_v2[43], expected_output="The Tokyo metropolitan area has approximately 37.1 million residents, making it the world's largest urban agglomeration.", metadata={"category":"general","pattern":"A_high_correct_high_ground"}, evidence=["UN: 'Tokyo: 37.1 million in metropolitan area.'"])
    rag_v2[47] = dict(rag_v2[47], expected_output="Approximately 17-20% of the original Amazon rainforest has been deforested, with scientists warning that 20-25% could trigger irreversible dieback.", metadata={"category":"climate","pattern":"A_high_correct_high_ground"}, evidence=["INPE: 'Approximately 17-20% deforested.'"])
    rag_v2[48] = dict(rag_v2[48], expected_output="Gold (Au) has atomic number 79. Silver (Ag) has atomic number 47.", metadata={"category":"science","pattern":"A_high_correct_high_ground"}, evidence=["Periodic table: 'Au (Gold): atomic number 79.'"])

    ds_rag_v1_h = create_dataset("rag_research_v1", "RAG Research Assistant v1",
        "80 RAG evaluation cases with 5 grounding patterns: A (high correct+high ground), B (high correct+low ground), C (low correct+high ground), D (low correct+low ground), E (high correct+low citation).",
        rag_v1, "2026-08-07T10:00:00Z")
    ds_rag_v2_h = create_dataset("rag_research_v2", "RAG Research Assistant v2",
        "Refined v2 with 5 cases improved from pattern C to A based on model fine-tuning. Same 80 cases, better grounding.",
        rag_v2, "2026-08-14T10:00:00Z")
    print("  rag_research_v1:", len(rag_v1), "cases")
    print("  rag_research_v2:", len(rag_v2), "cases")

    # Tool Agent
    tool_v1 = gen_tool_cases()
    ds_tool_v1_h = create_dataset("tool_agent_v1", "Travel Planning Agent v1",
        "40 travel planning tool-use cases covering flight search, hotel booking, multi-city routing, emergency handling, and complex multi-step planning.",
        tool_v1, "2026-08-09T10:00:00Z")
    print("  tool_agent_v1:", len(tool_v1), "cases")

    # --- 2. Create Canvas configs ---
    print("\n[2/4] Creating project canvas configs...")

    canvas_support = {
        "skillName": "customer_support_eval",
        "description": "Customer Support Agent evaluation pipeline",
        "modelId": "gpt-4o",
        "modelBaseUrl": "https://api.openai.com/v1",
        "judgeModelId": "gpt-4o",
        "judgeModelBaseUrl": "https://api.openai.com/v1",
        "canvasFields": [{
            "name": "support_quality",
            "gatePipeline": [
                {"metricId": "json_schema", "params": {"schema": "{}"}},
                {"metricId": "context_length", "params": {"max_length": 4000, "threshold": 1.0}},
            ],
            "scorePipeline": [
                {"metricId": "accuracy", "params": {"threshold": 0.7}, "weight": 0.30, "strictness": 1.0},
                {"metricId": "completeness", "params": {"threshold": 0.7}, "weight": 0.25, "strictness": 1.0},
                {"metricId": "no_hallucination", "params": {"threshold": 0.7}, "weight": 0.25, "strictness": 1.0},
                {"metricId": "keyword_hit", "params": {"required_keywords": "[]", "threshold": 0.5}, "weight": 0.10, "strictness": 1.0},
                {"metricId": "sentence_count", "params": {"min_sentences": 1, "max_sentences": 20, "threshold": 1.0}, "weight": 0.10, "strictness": 1.0},
            ]
        }],
        "dataset": {"dataset_id": "customer_support_v2", "n_cases": 60},
        "template": "deepeval"
    }

    canvas_rag = {
        "skillName": "rag_research_eval",
        "description": "RAG Research Assistant evaluation pipeline with evidence grounding focus",
        "modelId": "gpt-4o",
        "modelBaseUrl": "https://api.openai.com/v1",
        "judgeModelId": "gpt-4o",
        "judgeModelBaseUrl": "https://api.openai.com/v1",
        "canvasFields": [{
            "name": "answer_quality",
            "gatePipeline": [
                {"metricId": "json_schema", "params": {"schema": "{}"}},
            ],
            "scorePipeline": [
                {"metricId": "accuracy", "params": {"threshold": 0.7}, "weight": 0.30, "strictness": 1.0},
                {"metricId": "completeness", "params": {"threshold": 0.7}, "weight": 0.20, "strictness": 1.0},
                {"metricId": "no_hallucination", "params": {"threshold": 0.7}, "weight": 0.25, "strictness": 1.0},
                {"metricId": "recall_at_k", "params": {"k": 3, "threshold": 0.5}, "weight": 0.15, "strictness": 1.0},
                {"metricId": "keyword_hit", "params": {"required_keywords": "[]", "threshold": 0.5}, "weight": 0.10, "strictness": 1.0},
            ]
        }],
        "dataset": {"dataset_id": "rag_research_v2", "n_cases": 80},
        "template": "deepeval"
    }

    canvas_tool = {
        "skillName": "tool_agent_eval",
        "description": "Travel Planning Agent evaluation with tool-use metrics",
        "modelId": "gpt-4o",
        "modelBaseUrl": "https://api.openai.com/v1",
        "judgeModelId": "gpt-4o",
        "judgeModelBaseUrl": "https://api.openai.com/v1",
        "canvasFields": [{
            "name": "task_completion",
            "gatePipeline": [
                {"metricId": "json_schema", "params": {"schema": "{}"}},
            ],
            "scorePipeline": [
                {"metricId": "accuracy", "params": {"threshold": 0.7}, "weight": 0.35, "strictness": 1.0},
                {"metricId": "completeness", "params": {"threshold": 0.7}, "weight": 0.25, "strictness": 1.0},
                {"metricId": "no_hallucination", "params": {"threshold": 0.7}, "weight": 0.20, "strictness": 1.0},
                {"metricId": "latency", "params": {"max_seconds": 30, "threshold": 1.0}, "weight": 0.10, "strictness": 1.0},
                {"metricId": "keyword_hit", "params": {"required_keywords": "[]", "threshold": 0.5}, "weight": 0.10, "strictness": 1.0},
            ]
        }],
        "dataset": {"dataset_id": "tool_agent_v1", "n_cases": 40},
        "template": "deepeval"
    }

    for proj, canvas in [("customer_support", canvas_support), ("rag_research", canvas_rag), ("tool_agent", canvas_tool)]:
        proj_dir = DATA / "projects" / proj
        proj_dir.mkdir(parents=True, exist_ok=True)
        wj(proj_dir / "canvas.json", canvas)
        print("  Created", proj, "canvas.json")

    # --- 3. Create Runs ---
    print("\n[3/4] Creating runs...")

    metrics_base = [
        {"metric_id": "accuracy", "version_hash": "106e657129ea85c2", "instance": {"zone": "score", "weight": 0.30}},
        {"metric_id": "completeness", "version_hash": "127dbd2b16df68e5", "instance": {"zone": "score", "weight": 0.25}},
        {"metric_id": "no_hallucination", "version_hash": "5f645e82b9516697", "instance": {"zone": "score", "weight": 0.25}},
        {"metric_id": "json_schema", "version_hash": "f5b6ed16c857ff3c", "instance": {"zone": "gate"}},
        {"metric_id": "keyword_hit", "version_hash": "27804098ef59a316", "instance": {"zone": "score", "weight": 0.10}},
        {"metric_id": "sentence_count", "version_hash": "28a27b56b5de6a57", "instance": {"zone": "score", "weight": 0.10}},
    ]

    # Customer Support runs: 4 runs over 14 days, scores improving
    support_runs = [
        ("support_eval_001", "customer_support", "customer_support_v1", ds_support_v1_h, 0.784, 0.72,
         {"support_quality": 0.784}, -14, "gpt-4o-mini", "Customer Support Agent v1 - Initial baseline with GPT-4o-mini"),
        ("support_eval_002", "customer_support", "customer_support_v1", ds_support_v1_h, 0.827, 0.78,
         {"support_quality": 0.827}, -11, "gpt-4o", "Customer Support Agent v2 - Switched to GPT-4o, improved prompt"),
        ("support_eval_003", "customer_support", "customer_support_v2", ds_support_v2_h, 0.881, 0.85,
         {"support_quality": 0.881}, -7, "gpt-4o", "Customer Support Agent v3 - Updated to v2 dataset, fine-tuned prompts"),
        ("support_eval_004", "customer_support", "customer_support_v2", ds_support_v2_h, 0.924, 0.90,
         {"support_quality": 0.924}, -3, "gpt-4o", "Customer Support Agent v4 - Added few-shot examples, optimized system prompt"),
    ]

    # RAG Research runs: 8 runs with story around evidence grounding
    rag_runs = [
        ("rag_eval_001", "rag_research", "rag_research_v1", ds_rag_v1_h, 0.812, 0.78,
         {"answer_quality": 0.812}, -14, "gpt-4o-mini", "RAG Assistant v1 - Baseline with basic retrieval"),
        ("rag_eval_002", "rag_research", "rag_research_v1", ds_rag_v1_h, 0.838, 0.81,
         {"answer_quality": 0.838}, -12, "gpt-4o", "RAG Assistant v2 - Switched to GPT-4o"),
        ("rag_eval_003", "rag_research", "rag_research_v1", ds_rag_v1_h, 0.847, 0.82,
         {"answer_quality": 0.847}, -10, "gpt-4o", "RAG Assistant v3 - Improved retrieval with reranking"),
        ("rag_eval_004", "rag_research", "rag_research_v1", ds_rag_v1_h, 0.861, 0.84,
         {"answer_quality": 0.861}, -8, "gpt-4o", "RAG Assistant v4 - Added citation verification"),
        ("rag_eval_005", "rag_research", "rag_research_v2", ds_rag_v2_h, 0.873, 0.85,
         {"answer_quality": 0.873}, -6, "gpt-4o", "RAG Assistant v5 - Updated to v2 dataset, evidence grounding now 82%"),
        ("rag_eval_006", "rag_research", "rag_research_v2", ds_rag_v2_h, 0.891, 0.87,
         {"answer_quality": 0.891}, -4, "gpt-4o", "RAG Assistant v6 - Improved evidence grounding to 88%"),
        ("rag_eval_007", "rag_research", "rag_research_v2", ds_rag_v2_h, 0.907, 0.89,
         {"answer_quality": 0.907}, -2, "gpt-4o", "RAG Assistant v7 - Evidence grounding reaches 91%"),
        ("rag_eval_008", "rag_research", "rag_research_v2", ds_rag_v2_h, 0.918, 0.91,
         {"answer_quality": 0.918}, -1, "gpt-4o", "RAG Assistant v8 - Optimal: 93.4% correctness, 91.1% grounding"),
    ]

    # Tool Agent runs: 3 runs
    tool_runs = [
        ("tool_eval_001", "tool_agent", "tool_agent_v1", ds_tool_v1_h, 0.731, 0.68,
         {"task_completion": 0.731}, -10, "gpt-4o-mini", "Travel Agent v1 - Baseline, tool selection 76%, argument accuracy 81%"),
        ("tool_eval_002", "tool_agent", "tool_agent_v1", ds_tool_v1_h, 0.842, 0.81,
         {"task_completion": 0.842}, -6, "gpt-4o", "Travel Agent v2 - GPT-4o, improved tool selection to 88%, argument accuracy 90%"),
        ("tool_eval_003", "tool_agent", "tool_agent_v1", ds_tool_v1_h, 0.914, 0.90,
         {"task_completion": 0.914}, -2, "gpt-4o", "Travel Agent v3 - Tool selection 95%, argument accuracy 96%, task success 91%"),
    ]

    all_runs = support_runs + rag_runs + tool_runs

    for rid, proj, ds_id, ds_hash, score, pr, fields, day_offset, model, skill_name in all_runs:
        ts = iso(day_offset)
        n_cases = {"customer_support_v1": 60, "customer_support_v2": 60, "rag_research_v1": 80, "rag_research_v2": 80, "tool_agent_v1": 40}[ds_id]

        # Build results data
        n_passed = int(pr * n_cases)
        results = {
            "skill": skill_name,
            "created_at": ts,
            "n_cases": n_cases,
            "n_passed": n_passed,
            "pass_rate": round(pr, 4),
            "overall_score": round(score, 4),
            "grade": grade(score),
            "fields": {fn: {"field_score": round(fs, 4), "metrics": [
                {"name": "Accuracy", "mean": round(fs * 0.95, 4), "std": 0.12},
                {"name": "Completeness", "mean": round(fs * 0.90, 4), "std": 0.15},
                {"name": "Hallucination", "mean": round(fs * 0.92, 4), "std": 0.14},
            ]} for fn, fs in fields.items()},
            "cases": [],
            "bad_cases": [],
            "config": {
                "model": {"modelId": model, "baseUrl": "https://api.openai.com/v1"},
                "metrics": [{"name": m["metric_id"], "type": m["instance"]["zone"]} for m in metrics_base[:4]]
            },
            "summary_charts": [{
                "id": "overall_score_dist",
                "type": "histogram",
                "title": "Score Distribution",
                "x_label": "Score Range",
                "y_label": "Cases",
                "bins": [
                    {"x": "0.0-0.2", "count": max(0, int(n_cases * 0.02))},
                    {"x": "0.2-0.4", "count": max(0, int(n_cases * 0.05))},
                    {"x": "0.4-0.6", "count": max(0, int(n_cases * 0.08))},
                    {"x": "0.6-0.8", "count": max(0, int(n_cases * 0.25))},
                    {"x": "0.8-1.0", "count": max(0, int(n_cases * 0.60))},
                ]
            }],
            "summary_tables": [{
                "id": "bad_cases",
                "title": "Failed Cases (" + str(n_cases - n_passed) + " total)",
                "columns": ["case_id", "input", "issue"],
                "rows": [{"case_id": i, "input": f"Case {i}", "issue": "Score below threshold"} for i in range(n_cases - n_passed)],
                "paginate": True
            }]
        }

        create_run(rid, proj, ds_id, ds_hash[:16], ds_hash, n_cases, score, pr, fields, metrics_base, model, skill_name, ts, results)
        print("  Created", rid, "score:", score, "project:", proj)

    # --- 4. Git commits ---
    print("\n[4/4] Creating git commits for run discovery...")

    # Check if git is available
    import subprocess
    repo_root = Path(__file__).resolve().parent.parent
    git_check = subprocess.run(["git", "status"], capture_output=True, text=True, cwd=repo_root)
    if git_check.returncode != 0:
        print("  WARNING: git not available, skipping git commits. Run 'git init' first.")
        print("  Runs exist in data/runs/ but won't appear in the frontend without git.")
    else:
        for rid, proj, ds_id, ds_hash, score, pr, fields, day_offset, model, skill_name in all_runs:
            ts = iso(day_offset)
            subprocess.run(["git", "add", "-A"], capture_output=True, cwd=repo_root)
            msg = f"run: {proj}/{rid} [completed]"
            body = f"project: {proj}\ntriggered_by: agent\noverall_score: {score}\nmetrics: [accuracy, completeness, no_hallucination]\ndataset: {ds_id}"
            env = os.environ.copy()
            env["GIT_AUTHOR_DATE"] = ts
            env["GIT_COMMITTER_DATE"] = ts
            subprocess.run(["git", "commit", "-m", msg, "-m", body], capture_output=True, cwd=repo_root, env=env)
            print(f"  Committed: {rid} ({ts})")

    print("\n" + "=" * 60)
    print("DONE! Demo seed data generated.")
    print("=" * 60)
    print()
    print("Projects: customer_support, rag_research, tool_agent")
    print("Datasets: 5 total (customer_support_v1/v2, rag_research_v1/v2, tool_agent_v1)")
    print("Runs: 15 total across 3 projects")
    print("Cases: 60+60+80+80+40 = 320 total")
    print()
    print("To view: bash serve.sh, then open http://localhost:9090")
    print("The frontend reads from git_bridge on :9091 for runs and data/runs/ for details.")

if __name__ == "__main__":
    main()
