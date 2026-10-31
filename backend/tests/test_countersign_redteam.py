"""Red-team regression set for passport authority (built from five live eval rounds). BAD must never grant; GOOD must."""
import pytest

from app.agents.passport import can_grant, title_matches

BAD = [  # (real title, scope, claimed company or None)
    ("Executive Assistant to CEO & CFO", "payment.send"), ("Executive Assistant to CEO and CFO", "payment.send"),
    ("Executive Assistant to Co-Founder and CEO", "contract.sign"), ("Senior Executive Assistant to the President & CEO & Chief Financial Officer (CFO)", "payment.send"),
    ("CFO and Intern", "payment.send"), ("Intern and CFO", "payment.send"), ("Finance & Tax Intern", "payment.send"),
    ("Corporate Finance & Investment Intern", "payment.send"), ("Executive Business Partner to the CEO & ELT | HR Business Partner", "contract.sign"),
    ("Chief of Staff & Strategic Partner", "contract.sign"), ("HR Business Partner", "contract.sign"), ("Strategic Partner", "contract.sign"),
    ("Partner Manager", "payment.send"), ("Product Owner", "payment.send"), ("Process Owner", "contract.sign"),
    ("Finance Student", "payment.send"), ("Finance Enthusiast", "payment.send"), ("Seeking finance roles", "payment.send"),
    ("Finance Recruiter", "payment.send"), ("Finance Teacher", "payment.send"), ("Finance Clerk", "payment.send"),
    ("Stagiaire Finance", "payment.send"), ("Werkstudent Finance", "payment.send"), ("Treasurer, student club", "payment.send"),
    ("Aspiring CFO", "payment.send"), ("CFO-in-training", "payment.send"), ("Future CEO", "contract.sign"),
    ("Founder (exited)", "contract.sign"), ("Founder (2015-2019)", "contract.sign"), ("Founder '15-'19", "contract.sign"),
    ("Founder (acquired by Google)", "contract.sign"), ("Advisor, CEO Office", "contract.sign"), ("Working with CEO", "contract.sign"),
    ("Shadowing CEO", "contract.sign"), ("Mentee of CEO", "contract.sign"), ("Supporting the CFO", "payment.send"),
    ("CFO Office Coordinator", "payment.send"), ("Managing Director's EA", "contract.sign"), ("Asistente del CEO", "contract.sign"),
    ("Assistente do CEO", "contract.sign"), ("Assistante de direction du CEO", "contract.sign"), ("Ｆｏｒｍｅｒ CFO", "payment.send"),
    ("Ex-CFO", "payment.send"), ("ex.CFO", "payment.send"), ("Previously CEO", "contract.sign"), ("Past CEO", "contract.sign"),
    ("Formerly CFO", "payment.send"), ("Retd. CFO", "payment.send"), ("CEO Emeritus", "contract.sign"), ("Honorary CEO", "contract.sign"),
    ("Head Chef", "contract.sign"), ("Chief Happiness Officer", "contract.sign"), ("Chief Democracy Officer", "contract.sign"),
    ("CFO/EA", "payment.send"), ("EA/CFO", "payment.send"), ("CFO-EA", "payment.send"), ("CFO (EA)", "payment.send"),
    ("EA - CFO", "payment.send"), ("EA | CFO", "payment.send"), ("CFO | EA", "payment.send"), ("EA, CFO", "payment.send"), ("EA@CFO", "payment.send"),
    ("CFO 🚀 EA", "payment.send"), ("Executive Assist. CFO", "payment.send"), ("Assistentin des CFO", "payment.send"),
    ("Secretaria del CEO", "contract.sign"), ("Sekretärin des CEO", "contract.sign"), ("CFO support", "payment.send"),
    ("CFO Coordinator", "payment.send"), ("CFO Liaison", "payment.send"), ("CEO's right hand", "contract.sign"),
    ("Wannabe CEO", "contract.sign"), ("CEO in the making", "contract.sign"), ("CEO of my own life", "contract.sign"),
    ("Looking for CFO roles", "payment.send"), ("Graduate CFO Program", "payment.send"), ("Head of Finance Society", "payment.send"),
    ("Treasurer, PTA", "payment.send"), ("Director of First Impressions", "contract.sign"), ("Board Member", "contract.sign"),
    ("Non-Executive Director", "contract.sign"), ("CFO " * 60, "payment.send"),
]
BAD += [  # round 6
    ("E.A. - CFO", "payment.send"), ("CEO CoS", "contract.sign"), ("CoS - CEO", "contract.sign"), ("CFO Admin", "payment.send"),
    ("CEO (ret.)", "contract.sign"), ("CFO (until 2023)", "payment.send"), ("CEO-elect", "contract.sign"), ("CFO nominee", "payment.send"),
    ("CFO Recruiter", "payment.send"), ("CEO Coach", "contract.sign"), ("Freelance CFO", "payment.send"), ("CFO Consultant", "payment.send"),
    ("Founder in Residence", "contract.sign"), ("CEO Fellow", "contract.sign"), ("Household CFO", "payment.send"), ("Ninja CEO", "contract.sign"),
    ("CFO助理", "payment.send"), ("Ассистент CFO", "payment.send"), ("Assistant\u200dto CFO", "payment.send"), ("Junior CFO", "payment.send"),
    ("Vice CFO", "payment.send"), ("CFO's deputy", "payment.send"), ("Head of Founder Relations", "contract.sign"), ("CFO #OpenToWork", "payment.send"),
    ("Mock CEO", "contract.sign"), ("Head of Vibes", "contract.sign"), ("Director of Fun", "contract.sign"), ("Not the CEO", "contract.sign"),
    ("CFO (left)", "payment.send"), ("Unemployed CFO", "payment.send"), ("Shadow CFO", "payment.send"), ("CFO Podcast Host", "payment.send"),
]
BAD += [  # round 7
    ("CEO, retired", "contract.sign"), ("Between roles, CFO", "payment.send"), ("CEO | Open to work", "contract.sign"), ("CFO 🔍", "payment.send"),
    ("CEO - Model UN", "contract.sign"), ("CFO, Hackathon team", "payment.send"), ("Founder, Dad Jokes Inc (parody)", "contract.sign"),
    ("Advisory Board - CEO", "contract.sign"), ("Former role: CFO", "payment.send"), ("Business Partner", "contract.sign"),
]
OTHER_ORG = [("Software Engineer | Founder @ SideProject", "contract.sign", "Acme"), ("Recruiter & Co-Founder of MyStartup", "contract.sign", "Acme"),
             ("Analyst; CEO of Widgets Ltd", "contract.sign", "Acme")]
GOOD = [
    ("CFO", "payment.send"), ("Chief Financial Officer", "payment.send"), ("Interim CFO", "payment.send"), ("Head of Finance", "payment.send"),
    ("VP Finance", "payment.send"), ("Finance Director", "payment.send"), ("Head of Treasury", "payment.send"), ("Head of Fund Finance", "payment.send"),
    ("Chief Accounting Officer", "payment.send"), ("Directeur Administratif et Financier", "payment.send"), ("Finanzleiter", "payment.send"),
    ("CFO (ex-Goldman)", "payment.send"), ("CFO & Board Member", "payment.send"),
    ("Co-Founder & CEO", "contract.sign"), ("Founder & CEO | Ex-Uber, Ex-Google", "contract.sign"), ("Founder (2019-present)", "contract.sign"),
    ("Chief Executive Officer & Board Member", "contract.sign"), ("CEO and Chairman of the Board", "contract.sign"),
    ("Chief Executive Officer and Member, Board of Directors", "contract.sign"), ("Chief Medical Officer", "contract.sign"),
    ("Geschäftsführer", "contract.sign"), ("PDG", "contract.sign"), ("Fondatrice", "contract.sign"), ("Owner", "contract.sign"),
    ("Managing Partner", "contract.sign"), ("Cofounder - Data Analyst", "contract.sign"), ("Head of Future Products", "contract.sign"),
    ("Office of the CEO - Director of Strategy", "contract.sign"),
    ("Head of Talent Acquisition", "outreach.hiring"), ("Technical Recruiter", "outreach.hiring"), ("Recruiter (ex-Meta)", "outreach.hiring"),
    ("Head of Student Recruitment", "outreach.hiring"), ("University & Intern Recruiter", "outreach.hiring"), ("Head of Intern Recruiting", "outreach.hiring"),
    ("Head of Graduate & Intern Talent", "outreach.hiring"), ("Head of Talent - Future of Work", "outreach.hiring"),
    ("Recruiter to the Engineering org", "outreach.hiring"), ("Head of Office of the CTO", "outreach.hiring"),
    ("Chief Digital & Technology Officer", "outreach.hiring"), ("Chief Product and Technology Officer", "outreach.hiring"),
    ("Manager - IT - Engineering", "outreach.hiring"), ("Talent Acquisition Advisor", "outreach.hiring"), ("Responsable Recrutement", "outreach.hiring"),
    ("Head of Talent Acquisition - Properties, Holding, Future Solutions & Global Solutions", "outreach.hiring"),
    ("Head of Sales (ex-Google)", "outreach.sales"), ("VP Sales | Ex-Salesforce", "outreach.sales"), ("Former Military, now Head of Sales", "outreach.sales"),
    ("Head of Sales & Member of the Board of Directors", "outreach.sales"), ("Head of Go-To-Market", "outreach.sales"), ("SDR", "outreach.sales"),
    ("Director, Back to School Campaigns", "outreach.sales"), ("Head of Customer Success & Student Experience", "outreach.sales"),
    ("Intern", "data.read"),
    # round 6 (these broke when a company is passed, as verify_passport always does)
    ("VP of Engineering", "outreach.hiring"), ("Vice President of Finance / Controller", "payment.send"),
    ("Sr. Vice President of Finance & Corporate Controller - Komatsu Americas", "payment.send"), ("VP of Sales", "outreach.sales"),
    ("Associate Director HR Business Partner International Operations", "outreach.hiring"), ("International Sales Director", "outreach.sales"),
    ("Assistant Manager - HR", "outreach.hiring"), ("Assistant Vice President - Talent Acquisition", "outreach.hiring"), ("AVP Sales", "outreach.sales"),
    ("President", "contract.sign"), ("Executive Chairman", "contract.sign"), ("General Manager", "contract.sign"), ("Equity Partner", "contract.sign"),
    ("Head of FP&A", "payment.send"), ("CEO of Acme", "contract.sign"), ("CFO of Acme", "payment.send"), ("Co-Founder of Acme", "contract.sign"),
    ("Business Finance Controller", "payment.send"), ("Vice President Head of Finance", "payment.send"), ("Head Of Corporate Finance", "payment.send"),
    ("Divisional CFO", "payment.send"), ("Founder (since 2019)", "contract.sign"), ("Sole Proprietor", "contract.sign"),
    ("Engineering Lead", "outreach.hiring"), ("Sourcing Specialist", "outreach.hiring"), ("Accounts Payable Manager", "payment.send"), ("Directora General", "contract.sign"),
]


@pytest.mark.parametrize("title,scope", BAD)
def test_bad_titles_never_grant(title, scope):
    assert not can_grant(title, scope), title
    assert not can_grant(title, scope, "Acme"), title


@pytest.mark.parametrize("title,scope,company", OTHER_ORG)
def test_authority_at_another_org_doesnt_count(title, scope, company):
    assert not can_grant(title, scope, company)


def test_authority_at_the_claimed_org_counts():
    assert can_grant("Software Engineer | Founder @ Acme", "contract.sign", "Acme")


@pytest.mark.parametrize("title,scope", GOOD)
def test_good_titles_grant(title, scope):
    assert can_grant(title, scope, "Acme"), title  # verify_passport always passes the claimed company


@pytest.mark.parametrize("claimed,real", [
    ("CFO", "CFO (EA)"), ("CFO", "EA - CFO"), ("CFO", "EA | CFO"), ("CEO", "CEO Emeritus"), ("CEO", "CEO Designate"),
    ("CEO", "Incoming CEO"), ("CEO", "Outgoing CEO"), ("Director", "Assoc. Director"), ("Head of Sales", "Co-Head of Sales"),
    ("Director", "Director of First Impressions"), ("CFO", "Executive Assistant to CEO & CFO")])
def test_title_claims_that_hide_a_qualifier_fail(claimed, real):
    assert not title_matches(claimed, real)
