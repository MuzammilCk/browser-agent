"""Comprehensive Indian government site registry.

All major Indian government portals categorized by service domain,
with detailed task descriptions for each portal.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class SiteTask(BaseModel):
    """A specific task that can be performed on a government portal."""

    name: str = Field(description="Task name")
    description: str = Field(description="What this task does")
    requires_auth: bool = Field(default=False, description="Whether login/OTP is needed")
    requires_payment: bool = Field(default=False, description="Whether payment is involved")
    difficulty: str = Field(default="easy", description="easy | medium | hard")


class DomainEntry(BaseModel):
    """A trusted government domain entry with full metadata."""

    domain: str = Field(description="Domain name")
    official_name: str = Field(default="", description="Official name of the service")
    category: str = Field(description="Service category")
    subcategory: str = Field(default="", description="Sub-category")
    government_level: str = Field(
        default="central", description="central | state | local"
    )
    state: str = Field(default="", description="State name if state-level")
    verified: bool = Field(default=True, description="Whether domain is verified")
    allowed: bool = Field(default=True, description="Whether automation is allowed")
    url: str = Field(default="", description="Full URL")
    description: str = Field(default="", description="Brief description of the portal")
    tasks: list[SiteTask] = Field(default_factory=list, description="Tasks available")
    special_constraints: list[str] = Field(
        default_factory=list, description="Special rules"
    )
    interaction_classes: list[str] = Field(
        default_factory=list, description="Form interaction classes"
    )


# ============================================================
# CENTRAL GOVERNMENT PORTALS
# ============================================================

_CENTRAL_PORTALS: list[dict[str, Any]] = [
    # --- Identity & Documents ---
    {
        "domain": "uidai.gov.in",
        "official_name": "UIDAI (Aadhaar)",
        "category": "Identity & Documents",
        "subcategory": "Identity",
        "url": "https://uidai.gov.in",
        "description": "Aadhaar — India's unique 12-digit identity number for every resident",
        "tasks": [
            {"name": "Download Aadhaar", "description": "Download e-Aadhaar PDF using Aadhaar number or enrollment ID"},
            {"name": "Verify Aadhaar", "description": "Check if an Aadhaar number is valid and active"},
            {"name": "Update Aadhaar Details", "description": "Name, address, DOB, gender, mobile, email updates online"},
            {"name": "Book Aadhaar Appointment", "description": "Schedule visit to Aadhaar Enrolment/Update Centre"},
            {"name": "Check Aadhaar Update Status", "description": "Track status of Aadhaar update/enrollment request"},
            {"name": "Generate Virtual ID", "description": "Create VID for Aadhaar authentication without sharing Aadhaar number"},
            {"name": "Lock/Unlock Biometrics", "description": "Temporarily lock Aadhaar biometrics for security"},
            {"name": "Aadhaar Paperless Offline eKYC", "description": "Download XML-based offline KYC for third-party verification"},
            {"name": "Retrieve Lost EID/Aadhaar", "description": "Find forgotten enrollment ID or Aadhaar number via mobile/email"},
        ],
        "interaction_classes": ["A", "C"],
    },
    {
        "domain": "meripasahal.nic.in",
        "official_name": "mAadhaar",
        "category": "Identity & Documents",
        "subcategory": "Identity",
        "url": "https://meripasahal.nic.in",
        "description": "Mobile Aadhaar — digital Aadhaar on smartphone",
        "tasks": [
            {"name": "View Digital Aadhaar", "description": "Access Aadhaar card on mobile device"},
            {"name": "Share OTP-based Verification", "description": "Share Aadhaar verification with service providers"},
        ],
        "interaction_classes": ["A", "C"],
    },
    {
        "domain": "passportindia.gov.in",
        "official_name": "Passport Seva",
        "category": "Identity & Documents",
        "subcategory": "Passport",
        "url": "https://passportindia.gov.in",
        "description": "Indian passport application, renewal, and related services",
        "tasks": [
            {"name": "Apply for New Passport", "description": "Fresh passport application with document upload and appointment"},
            {"name": "Renew/Reissue Passport", "description": "Renew expired passport or reissue for name change, damage, etc."},
            {"name": "Check Application Status", "description": "Track passport application by file number"},
            {"name": "Book Appointment at PSK", "description": "Schedule appointment at Passport Seva Kendra"},
            {"name": "Pay Passport Fee Online", "description": "Online fee payment for passport services"},
            {"name": "Download Passport Application Form", "description": "Print filled application form for PSK visit"},
            {"name": "View File Authentication Status", "description": "Check police verification and file status"},
            {"name": "Track Police Verification Status", "description": "See if police verification is complete"},
            {"name": "Get Police Clearance Certificate", "description": "Apply for PCC for immigration/employment"},
            {"name": "Surrender Certificate", "description": "Apply for surrender certificate for renounced Indian passport"},
        ],
        "interaction_classes": ["B", "F", "G"],
    },
    {
        "domain": "parivahan.gov.in",
        "official_name": "Parivahan Seva",
        "category": "Transport & Vehicles",
        "subcategory": "Driving License",
        "url": "https://parivahan.gov.in",
        "description": "Driving license, vehicle registration, and transport services",
        "tasks": [
            {"name": "Apply for Learner's License", "description": "Apply for new learner's driving license online"},
            {"name": "Apply for Permanent Driving License", "description": "Upgrade from learner's to permanent driving license"},
            {"name": "Renew Driving License", "description": "Renew expired or expiring driving license"},
            {"name": "International Driving Permit", "description": "Apply for IDP for driving abroad"},
            {"name": "Vehicle Registration", "description": "New vehicle registration, transfer of ownership"},
            {"name": "RC Renewal", "description": "Renew Registration Certificate"},
            {"name": "Address Change in DL/RC", "description": "Update address in driving license or RC"},
            {"name": "Fancy Number Booking", "description": "Book premium vehicle registration numbers"},
            {"name": "Pay Traffic Challan", "description": "View and pay pending traffic fines online"},
            {"name": "Check Vehicle Tax Status", "description": "Verify road tax payment status"},
            {"name": "NOC for Vehicle Transfer", "description": "Apply for No Objection Certificate for inter-state transfer"},
            {"name": "Duplicate DL/RC", "description": "Apply for duplicate license or registration certificate"},
            {"name": "Check DL/RC Status", "description": "Verify driving license or RC validity"},
            {"name": "Book Slot for Test", "description": "Schedule driving test at RTO"},
        ],
        "interaction_classes": ["B", "E", "F", "G"],
    },
    {
        "domain": "vahan.parivahan.gov.in",
        "official_name": "Vahan Portal",
        "category": "Transport & Vehicles",
        "subcategory": "Vehicle",
        "url": "https://vahan.parivahan.gov.in",
        "description": "Vehicle registration, tax, and ownership services",
        "tasks": [
            {"name": "Pay Road Tax Online", "description": "Pay motor vehicle tax for new/used vehicles"},
            {"name": "Vehicle Fitness Certificate", "description": "Apply for vehicle fitness certificate renewal"},
            {"name": "Ownership Transfer", "description": "Transfer vehicle ownership to new buyer"},
            {"name": "Hypothecation Addition/Removal", "description": "Add or remove bank lien on vehicle RC"},
            {"name": "Check Vehicle Details", "description": "View vehicle registration details, owner, tax status"},
            {"name": "Apply for BH Series", "description": "Bharat Series registration for seamless inter-state transfer"},
        ],
        "interaction_classes": ["B", "E", "G"],
    },

    # --- Tax & Finance ---
    {
        "domain": "incometax.gov.in",
        "official_name": "Income Tax Department",
        "category": "Tax & Finance",
        "subcategory": "Income Tax",
        "url": "https://incometax.gov.in",
        "description": "Income tax filing, PAN services, tax payment, and refunds",
        "tasks": [
            {"name": "File Income Tax Return (ITR)", "description": "File annual income tax return online with pre-filled data"},
            {"name": "Check ITR Status", "description": "Track processing status of filed returns"},
            {"name": "Link Aadhaar with PAN", "description": "Mandatory linking of Aadhaar and PAN"},
            {"name": "View Form 26AS", "description": "Download annual tax statement (TDS/TCS credits)"},
            {"name": "View AIS (Annual Information Statement)", "description": "Comprehensive view of financial transactions reported to IT dept"},
            {"name": "Download PAN Card", "description": "Get e-PAN using Aadhaar (instant/electronic PAN)"},
            {"name": "Apply for New PAN", "description": "Apply for new PAN card via Aadhaar-based e-KYC"},
            {"name": "Correct PAN Details", "description": "Update/correct name, DOB, address on PAN"},
            {"name": "Pay Advance Tax", "description": "Pay quarterly advance tax online"},
            {"name": "Check Refund Status", "description": "Track income tax refund status"},
            {"name": "View e-Proceedings", "description": "Access tax assessment and scrutiny notices"},
            {"name": "Submit Response to Notice", "description": "Respond to IT department notices online"},
            {"name": "Verify PAN", "description": "Check PAN validity and details"},
            {"name": "Check TDS Deduction", "description": "View TDS deducted by employers/payers"},
        ],
        "interaction_classes": ["A", "C"],
    },
    {
        "domain": "gst.gov.in",
        "official_name": "GST Portal",
        "category": "Tax & Finance",
        "subcategory": "GST",
        "url": "https://gst.gov.in",
        "description": "Goods and Services Tax registration, returns, and payments",
        "tasks": [
            {"name": "GST Registration", "description": "Register new business for GST with PAN/Aadhaar verification"},
            {"name": "File GST Returns (GSTR-1, GSTR-3B)", "description": "Monthly/quarterly GST return filing"},
            {"name": "Pay GST Online", "description": "Make GST payment via challan"},
            {"name": "Check GST Returns Status", "description": "Track filed returns and their processing"},
            {"name": "Apply for GST Refund", "description": "Claim refund of excess GST paid"},
            {"name": "View E-Way Bill", "description": "Generate and track e-way bills for goods movement"},
            {"name": "Check GST Registration Status", "description": "Verify GSTIN and registration details"},
            {"name": "Amend GST Registration", "description": "Update business details in GST registration"},
            {"name": "Surrender GST Registration", "description": "Cancel GST registration for closed businesses"},
            {"name": "Download GST Certificates", "description": "Get GST registration certificate"},
            {"name": "Input Tax Credit (ITC) Reconciliation", "description": "Match ITC claims with supplier returns"},
            {"name": "Check GST Demand/Order", "description": "View orders and demands from GST department"},
        ],
        "interaction_classes": ["B", "C"],
    },
    {
        "domain": "epfindia.gov.in",
        "official_name": "EPFO — Employees' Provident Fund",
        "category": "Tax & Finance",
        "subcategory": "Provident Fund",
        "url": "https://epfindia.gov.in",
        "description": "Employee provident fund — contributions, claims, and passbook",
        "tasks": [
            {"name": "UAN Activation", "description": "Activate Universal Account Number for EPF services"},
            {"name": "Check EPF Balance", "description": "View EPF passbook and balance via UAN"},
            {"name": "Online EPF Withdrawal (Claim)", "description": "Withdraw EPF amount online (Form 19, 10C, 31)"},
            {"name": "Transfer EPF Account", "description": "Transfer EPF balance from old to new employer"},
            {"name": "Link Aadhaar with UAN", "description": "Seed Aadhaar for direct benefit transfer"},
            {"name": "Update KYC in UAN", "description": "Update bank, PAN, Aadhaar details linked to UAN"},
            {"name": "Download EPF Passbook", "description": "Get monthly contribution statement"},
            {"name": "Check Claim Status", "description": "Track EPF withdrawal/transfer claim status"},
            {"name": "Generate UAN", "description": "Get new UAN if not provided by employer"},
        ],
        "interaction_classes": ["A", "C"],
    },
    {
        "domain": "nps.nsdl.com",
        "official_name": "National Pension System (NPS)",
        "category": "Tax & Finance",
        "subcategory": "Pension",
        "url": "https://nps.nsdl.com",
        "description": "Government pension scheme — registration, contributions, and withdrawals",
        "tasks": [
            {"name": "Open NPS Account", "description": "Register for National Pension System online"},
            {"name": "Contribute to NPS", "description": "Add voluntary or regular contributions"},
            {"name": "Check NPS Balance", "description": "View pension wealth and holdings"},
            {"name": "Request NPS Withdrawal", "description": "Partial or full withdrawal from NPS corpus"},
            {"name": "Change NPS Fund Manager", "description": "Switch between Pension Fund Managers"},
            {"name": "Update Nominee Details", "description": "Add or modify NPS nominee information"},
            {"name": "Print NPS Statement", "description": "Download transaction history and balance statement"},
            {"name": "Tier II Account Operations", "description": "Manage voluntary savings account under NPS"},
        ],
        "interaction_classes": ["A", "C"],
    },

    # --- Education ---
    {
        "domain": "scholarships.gov.in",
        "official_name": "National Scholarship Portal (NSP)",
        "category": "Education",
        "subcategory": "Scholarships",
        "url": "https://scholarships.gov.in",
        "description": "Central and state scholarship applications for students",
        "tasks": [
            {"name": "Register for Scholarship", "description": "Create student account and apply for eligible scholarships"},
            {"name": "Check Scholarship Status", "description": "Track application processing and disbursement status"},
            {"name": "Renew Scholarship", "description": "Renew existing scholarship for next academic year"},
            {"name": "Download Scholarship Certificate", "description": "Get award certificate after disbursement"},
            {"name": "Check Disbursement Status", "description": "Verify if scholarship amount has been credited"},
            {"name": "Update Bank Details", "description": "Change bank account for scholarship credit"},
        ],
        "interaction_classes": ["B", "C"],
    },
    {
        "domain": "udiseplus.gov.in",
        "official_name": "UDISE+ (Unified District Information System for Education)",
        "category": "Education",
        "subcategory": "School Data",
        "url": "https://udiseplus.gov.in",
        "description": "Education statistics, school profiles, and student enrollment data",
        "tasks": [
            {"name": "View School Profiles", "description": "Access detailed school information and infrastructure data"},
            {"name": "Check Enrollment Statistics", "description": "View student enrollment data by district/state"},
            {"name": "Report Card Generation", "description": "Download school performance report"},
            {"name": "Update School Data", "description": "School administrators update institutional information"},
        ],
        "interaction_classes": ["A"],
    },
    {
        "domain": "digilocker.gov.in",
        "official_name": "DigiLocker",
        "category": "Identity & Documents",
        "subcategory": "Digital Documents",
        "url": "https://digilocker.gov.in",
        "description": "Government-issued digital documents and certificates repository",
        "tasks": [
            {"name": "Access Digital Documents", "description": "View Aadhaar, PAN, driving license, marksheets, etc. digitally"},
            {"name": "Upload Documents", "description": "Store personal documents in cloud locker"},
            {"name": "Share Verified Documents", "description": "Share government-verified documents with organizations"},
            {"name": "Verify Document Authenticity", "description": "Verify if a document is genuine via DigiLocker"},
            {"name": "Download Documents", "description": "Get PDF copies of issued documents"},
            {"name": "Link Aadhaar to DigiLocker", "description": "Connect Aadhaar for accessing government-issued documents"},
        ],
        "interaction_classes": ["A", "C"],
    },

    # --- Agriculture ---
    {
        "domain": "pmkisan.gov.in",
        "official_name": "PM-KISAN",
        "category": "Agriculture",
        "subcategory": "Farmer Welfare",
        "url": "https://pmkisan.gov.in",
        "description": "Direct income support of ₹6,000/year to farmer families",
        "tasks": [
            {"name": "Register as Farmer", "description": "Register for PM-KISAN direct benefit transfer"},
            {"name": "Check PM-KISAN Status", "description": "Track installment status and beneficiary details"},
            {"name": "Update Bank Account", "description": "Change bank account for direct credit"},
            {"name": "Update Aadhaar Details", "description": "Correct Aadhaar linkage for PM-KISAN"},
            {"name": "Check Beneficiary List", "description": "View village/block/state-wise beneficiary list"},
            {"name": "Self-Registration", "description": "New farmer self-registration via Aadhaar eKYC"},
            {"name": "eKYC for PM-KISAN", "description": "Complete Aadhaar-based OTP eKYC for continued benefits"},
        ],
        "interaction_classes": ["A", "C"],
    },
    {
        "domain": "pmfby.gov.in",
        "official_name": "Pradhan Mantri Fasal Bima Yojana (PMFBY)",
        "category": "Agriculture",
        "subcategory": "Crop Insurance",
        "url": "https://pmfby.gov.in",
        "description": "Government-sponsored crop insurance scheme for farmers",
        "tasks": [
            {"name": "Register for Crop Insurance", "description": "Enroll in PMFBY for Kharif/Rabi season"},
            {"name": "Check Insurance Status", "description": "Track crop insurance application and coverage"},
            {"name": "File Crop Loss Claim", "description": "Report crop damage and file insurance claim"},
            {"name": "Check Claim Settlement Status", "description": "Track insurance claim processing and payout"},
            {"name": "View Policy Details", "description": "Download policy document and coverage details"},
            {"name": "Check Premium Subsidy", "description": "View government subsidy on insurance premium"},
        ],
        "interaction_classes": ["B", "C"],
    },
    {
        "domain": "soilhealth.dac.gov.in",
        "official_name": "Soil Health Card Portal",
        "category": "Agriculture",
        "subcategory": "Soil & Farming",
        "url": "https://soilhealth.dac.gov.in",
        "description": "Soil health cards with crop-wise fertilizer recommendations",
        "tasks": [
            {"name": "Download Soil Health Card", "description": "Get soil analysis report and fertilizer recommendations"},
            {"name": "Check Soil Test Status", "description": "Track soil sample testing progress"},
            {"name": "View Soil Health Dashboard", "description": "Access district/state-wise soil health data"},
        ],
        "interaction_classes": ["A"],
    },

    # --- Health ---
    {
        "domain": "abha.abdm.gov.in",
        "official_name": "ABHA (Ayushman Bharat Health Account)",
        "category": "Health",
        "subcategory": "Health ID",
        "url": "https://abha.abdm.gov.in",
        "description": "Digital health ID for accessing health records across India",
        "tasks": [
            {"name": "Create ABHA Number", "description": "Generate 14-digit health ID using Aadhaar or DL"},
            {"name": "Link Health Records", "description": "Connect prescriptions, lab reports, and records to ABHA"},
            {"name": "View Health Records", "description": "Access digital health history from linked facilities"},
            {"name": "Share Health Records", "description": "Share verified health data with doctors/hospitals"},
            {"name": "Download ABHA Card", "description": "Get digital ABHA health ID card"},
        ],
        "interaction_classes": ["A", "C"],
    },
    {
        "domain": "nha.gov.in",
        "official_name": "National Health Authority (NHA)",
        "category": "Health",
        "subcategory": "Insurance",
        "url": "https://nha.gov.in",
        "description": "Ayushman Bharat — PM-JAY health insurance for eligible families",
        "tasks": [
            {"name": "Check PM-JAY Eligibility", "description": "Verify if family is eligible for Ayushman Bharat coverage"},
            {"name": "Download Ayushman Card", "description": "Get digital Ayushman Bharat health insurance card"},
            {"name": "Find Empanelled Hospital", "description": "Search hospitals covered under PM-JAY in your area"},
            {"name": "Check Claim Status", "description": "Track insurance claim processing at empanelled hospitals"},
            {"name": "Search Beneficiary by Aadhaar", "description": "Find PM-JAY beneficiary details via Aadhaar number"},
        ],
        "interaction_classes": ["A", "C"],
    },
    {
        "domain": "ncdc.gov.in",
        "official_name": "National Centre for Disease Control",
        "category": "Health",
        "subcategory": "Disease Control",
        "url": "https://ncdc.gov.in",
        "description": "Disease surveillance, immunization tracking, and public health data",
        "tasks": [
            {"name": "View Disease Surveillance Data", "description": "Access outbreak and disease reporting data"},
            {"name": "Check Vaccination Schedule", "description": "View national immunization schedule"},
            {"name": "Report Disease Outbreak", "description": "Healthcare workers report disease incidents"},
        ],
        "interaction_classes": ["A"],
    },

    # --- Employment ---
    {
        "domain": "ncs.gov.in",
        "official_name": "National Career Service (NCS)",
        "category": "Employment",
        "subcategory": "Job Portal",
        "url": "https://ncs.gov.in",
        "description": "Government job portal connecting job seekers with employers",
        "tasks": [
            {"name": "Register as Job Seeker", "description": "Create profile and upload resume for government/private jobs"},
            {"name": "Search Jobs", "description": "Browse job listings by skill, location, and qualification"},
            {"name": "Apply for Jobs", "description": "Submit applications directly through NCS platform"},
            {"name": "Register as Employer", "description": "Companies register to post job openings"},
            {"name": "Post Job Opening", "description": "Employers publish job vacancies"},
            {"name": "Book Career Counselor", "description": "Schedule session with government career counselor"},
            {"name": "Register for Skill Training", "description": "Enroll in skill development programs listed on NCS"},
        ],
        "interaction_classes": ["A", "C"],
    },
    {
        "domain": "eshram.gov.in",
        "official_name": "e-Shram Portal",
        "category": "Employment",
        "subcategory": "Unorganized Workers",
        "url": "https://eshram.gov.in",
        "description": "National database of unorganized workers for social security",
        "tasks": [
            {"name": "Register as Unorganized Worker", "description": "Get e-Shram card using Aadhaar and bank details"},
            {"name": "Download e-Shram Card", "description": "Get digital UAN card for unorganized sector workers"},
            {"name": "Update Profile", "description": "Modify personal, skill, or occupation details"},
            {"name": "Check Social Security Benefits", "description": "View eligible welfare schemes linked to e-Shram"},
            {"name": "Check Accident Insurance Status", "description": "Verify Pradhan Mantri Suraksha Bima Yojana enrollment"},
        ],
        "interaction_classes": ["A", "C"],
    },

    # --- Business & MSME ---
    {
        "domain": "udyamregistration.gov.in",
        "official_name": "Udyam Registration (MSME)",
        "category": "Business & MSME",
        "subcategory": "MSME",
        "url": "https://udyamregistration.gov.in",
        "description": "MSME registration portal for micro, small, and medium enterprises",
        "tasks": [
            {"name": "Register as MSME", "description": "Get Udyam registration certificate via Aadhaar-based process"},
            {"name": "Check Udyam Status", "description": "Track MSME registration application status"},
            {"name": "Update Udyam Details", "description": "Modify enterprise information post-registration"},
            {"name": "Print Udyam Certificate", "description": "Download MSME registration certificate"},
            {"name": "Verify Udyam Number", "description": "Check validity of existing Udyam registration"},
        ],
        "interaction_classes": ["A", "C"],
    },
    {
        "domain": "mca.gov.in",
        "official_name": "Ministry of Corporate Affairs (MCA)",
        "category": "Business & MSME",
        "subcategory": "Company Registration",
        "url": "https://mca.gov.in",
        "description": "Company incorporation, compliance filing, and corporate governance",
        "tasks": [
            {"name": "Incorporate Company", "description": "Register new company (Private/Public/LLP/OPC) via MCA21"},
            {"name": "File Annual Returns", "description": "Submit annual return and financial statements"},
            {"name": "Check Company Name Availability", "description": "Verify if proposed company name is available"},
            {"name": "View Company Details", "description": "Access company registration info, directors, charges"},
            {"name": "File Director Change", "description": "Appoint or resign company directors"},
            {"name": "Check DIN Status", "description": "Verify Director Identification Number"},
            {"name": "Download Certificates", "description": "Get incorporation and other MCA certificates"},
            {"name": "File Charge Documents", "description": "Register or modify company charges/mortgages"},
        ],
        "interaction_classes": ["B", "C"],
    },
    {
        "domain": "startupindia.gov.in",
        "official_name": "Startup India",
        "category": "Business & MSME",
        "subcategory": "Startups",
        "url": "https://startupindia.gov.in",
        "description": "Government initiative for startup ecosystem — recognition, funding, and incentives",
        "tasks": [
            {"name": "Get Startup Recognition", "description": "Register DPIIT-recognized startup for tax benefits"},
            {"name": "Apply for Tax Exemption", "description": "Claim Section 80IAC tax holiday for eligible startups"},
            {"name": "Register for Fund of Funds", "description": "Apply for government-backed startup funding"},
            {"name": "View Startup Benefits", "description": "Check self-certification, IPR, and other benefits"},
            {"name": "Connect with Incubators", "description": "Find government-approved incubators and accelerators"},
        ],
        "interaction_classes": ["A", "C"],
    },

    # --- Digital Services ---
    {
        "domain": "india.gov.in",
        "official_name": "National Portal of India",
        "category": "Digital Services",
        "subcategory": "Portal",
        "url": "https://india.gov.in",
        "description": "Single-window gateway to all government information and services",
        "tasks": [
            {"name": "Search Government Services", "description": "Find services by ministry, state, or category"},
            {"name": "Access Government Directory", "description": "Find contact details of government officials and departments"},
            {"name": "View Government Schemes", "description": "Browse all central and state government schemes"},
            {"name": "File RTI Application", "description": "Initiate Right to Information application"},
        ],
        "interaction_classes": ["A"],
    },
    {
        "domain": "digitalindia.gov.in",
        "official_name": "Digital India",
        "category": "Digital Services",
        "subcategory": "Digital Initiatives",
        "url": "https://digitalindia.gov.in",
        "description": "Flagship program for digital governance and citizen services",
        "tasks": [
            {"name": "Explore Digital Services", "description": "Browse all digital government services"},
            {"name": "Check Digital Literacy Programs", "description": "Find digital skill development initiatives"},
            {"name": "Access MyGov Portal", "description": "Participate in government campaigns and discussions"},
        ],
        "interaction_classes": ["A"],
    },
    {
        "domain": "umang.gov.in",
        "official_name": "UMANG (Unified Mobile App for New-age Governance)",
        "category": "Digital Services",
        "subcategory": "Mobile Services",
        "url": "https://umang.gov.in",
        "description": "One-stop mobile app for 1000+ government services",
        "tasks": [
            {"name": "Access EPF Services", "description": "Check EPF balance, download passbook via UMANG"},
            {"name": "Access Pension Services", "description": "View NPS/CGHS pension details"},
            {"name": "Pay Gas/Electricity Bills", "description": "Pay utility bills through integrated services"},
            {"name": "Check Soil Health Card", "description": "Access soil health data via UMANG"},
            {"name": "Access Ayushman Bharat", "description": "View Ayushman card and find empanelled hospitals"},
            {"name": "Apply for Government Schemes", "description": "Search and apply for eligible schemes"},
        ],
        "interaction_classes": ["A", "C"],
    },
    {
        "domain": "myscheme.gov.in",
        "official_name": "myScheme",
        "category": "Digital Services",
        "subcategory": "Schemes Discovery",
        "url": "https://myscheme.gov.in",
        "description": "Search engine for government schemes — eligibility checker and finder",
        "tasks": [
            {"name": "Search Government Schemes", "description": "Find schemes by category, eligibility, or keyword"},
            {"name": "Check Eligibility", "description": "Answer questions to find schemes you qualify for"},
            {"name": "View Scheme Details", "description": "Read benefits, documents required, and how to apply"},
            {"name": "Apply for Scheme", "description": "Navigate to the official portal to apply"},
        ],
        "interaction_classes": ["A"],
    },
    {
        "domain": "indiapost.gov.in",
        "official_name": "India Post",
        "category": "Digital Services",
        "subcategory": "Postal Services",
        "url": "https://indiapost.gov.in",
        "description": "India Post — mail tracking, savings accounts, and postal services",
        "tasks": [
            {"name": "Track Speed Post / Registered Mail", "description": "Track consignment by tracking number"},
            {"name": "Open Post Office Savings Account", "description": "Open POSB account online"},
            {"name": "Check Post Office Interest Rates", "description": "View current RD, TD, NSC, KVP rates"},
            {"name": "Calculate postage", "description": "Estimate mailing cost by weight and destination"},
            {"name": "Find Post Office", "description": "Locate nearest post office by pincode or address"},
            {"name": "Apply for Passport (via Post Office)", "description": "Use post office as Passport Seva Kendra"},
        ],
        "interaction_classes": ["A"],
    },

    # --- Governance & Grievance ---
    {
        "domain": "pgportal.gov.in",
        "official_name": "Public Grievance Portal (CPGRAMS)",
        "category": "Governance",
        "subcategory": "Grievance",
        "url": "https://pgportal.gov.in",
        "description": "Centralized public grievance redress and monitoring system",
        "tasks": [
            {"name": "File Grievance", "description": "Submit complaint against government department/service"},
            {"name": "Track Grievance Status", "description": "Monitor grievance registration, transfer, and resolution"},
            {"name": "View Grievance History", "description": "Access all previously filed grievances"},
            {"name": "File Appeal", "description": "Appeal against unresolved grievance at higher level"},
            {"name": "Close Grievance", "description": "Mark grievance as resolved after satisfactory action"},
        ],
        "interaction_classes": ["A", "C"],
    },
    {
        "domain": "rtionline.gov.in",
        "official_name": "RTI Online",
        "category": "Governance",
        "subcategory": "Right to Information",
        "url": "https://rtionline.gov.in",
        "description": "File Right to Information applications to central government bodies",
        "tasks": [
            {"name": "File RTI Application", "description": "Submit RTI request to central public authority with ₹10 fee"},
            {"name": "File First Appeal", "description": "Appeal against unsatisfactory RTI response"},
            {"name": "Track RTI Status", "description": "Check application status and response date"},
            {"name": "Pay RTI Fee Online", "description": "Pay ₹10 application fee via net banking/UPI"},
            {"name": "View RTI Response", "description": "Download information provided by public authority"},
        ],
        "interaction_classes": ["A", "C", "G"],
    },
    {
        "domain": "ecourts.gov.in",
        "official_name": "eCourts Services",
        "category": "Governance",
        "subcategory": "Judiciary",
        "url": "https://ecourts.gov.in",
        "description": "Digital access to Indian judiciary — case status, cause lists, orders",
        "tasks": [
            {"name": "Check Case Status", "description": "Search by case number, party name, or advocate name"},
            {"name": "View Cause List", "description": "See daily court hearing schedule"},
            {"name": "Download Court Orders", "description": "Get PDF copies of judgments and orders"},
            {"name": "View Case History", "description": "See complete hearing and order history"},
            {"name": "Check Court Fee Payment", "description": "Pay court fees online for filing cases"},
            {"name": "Find Court Complex", "description": "Locate district court complexes with contact details"},
        ],
        "interaction_classes": ["A"],
    },
    {
        "domain": "cic.gov.in",
        "official_name": "Central Information Commission",
        "category": "Governance",
        "subcategory": "Transparency",
        "url": "https://cic.gov.in",
        "description": "Second appeals and complaints under Right to Information Act",
        "tasks": [
            {"name": "File Second Appeal", "description": "Appeal to CIC when first appeal is unsatisfactory"},
            {"name": "File Complaint to CIC", "description": "Complain about non-compliance with RTI Act"},
            {"name": "Track Case Status", "description": "Check status of second appeal/complaint"},
            {"name": "View CIC Orders", "description": "Download CIC decisions and orders"},
        ],
        "interaction_classes": ["A", "C"],
    },
    {
        "domain": "indiagovt.gov.in",
        "official_name": "MyGov India",
        "category": "Governance",
        "subcategory": "Citizen Participation",
        "url": "https://mygov.in",
        "description": "Government-citizen platform for participation, discussions, and campaigns",
        "tasks": [
            {"name": "Participate in Discussions", "description": "Give suggestions on government policy topics"},
            {"name": "Join Competitions", "description": "Participate in quizzes, poster design, essay contests"},
            {"name": "Submit Ideas", "description": "Propose ideas for government initiatives"},
            {"name": "Volunteer for Causes", "description": "Register for Swachh Bharat, tree plantation, etc."},
        ],
        "interaction_classes": ["A", "C"],
    },

    # --- Welfare Schemes ---
    {
        "domain": "pmaymis.gov.in",
        "official_name": "PM Awas Yojana (Urban)",
        "category": "Welfare",
        "subcategory": "Housing",
        "url": "https://pmaymis.gov.in",
        "description": "Housing for All — urban affordable housing scheme",
        "tasks": [
            {"name": "Apply for PMAY(U) Benefits", "description": "Register for affordable housing subsidy under CLSS"},
            {"name": "Check Application Status", "description": "Track PMAY housing application"},
            {"name": "Verify Beneficiary Status", "description": "Check if approved as PMAY beneficiary"},
            {"name": "View Subsidy Details", "description": "Check credit-linked subsidy amount"},
        ],
        "interaction_classes": ["B", "C"],
    },
    {
        "domain": "jayabharat.gov.in",
        "official_name": "PM-JAY (Ayushman Bharat)",
        "category": "Welfare",
        "subcategory": "Health Insurance",
        "url": "https://jayabharat.gov.in",
        "description": "Health assurance scheme for economically vulnerable families",
        "tasks": [
            {"name": "Check Eligibility", "description": "Verify family eligibility via SECC database"},
            {"name": "Download Ayushman Card", "description": "Get digital Ayushman Bharat card"},
            {"name": "Find Hospital", "description": "Search empanelled hospitals by location"},
            {"name": "Track Treatment Claim", "description": "Check hospitalization claim status"},
        ],
        "interaction_classes": ["A", "C"],
    },
    {
        "domain": "nrega.nic.in",
        "official_name": "MGNREGA",
        "category": "Welfare",
        "subcategory": "Rural Employment",
        "url": "https://nrega.nic.in",
        "description": "Mahatma Gandhi National Rural Employment Guarantee Act — 100 days guaranteed work",
        "tasks": [
            {"name": "Register for Job Card", "description": "Apply for MGNREGA job card as rural worker"},
            {"name": "Request Employment", "description": "Demand guaranteed 100 days of work under MGNREGA"},
            {"name": "Check Job Card Status", "description": "View job card details and work history"},
            {"name": "View Muster Roll", "description": "Check attendance and wage payment records"},
            {"name": "Track Wage Payment", "description": "Verify if wages have been credited to bank account"},
            {"name": "File Grievance", "description": "Complain about delayed wages or denied work"},
            {"name": "View Social Audit", "description": "Access gram sabha social audit reports"},
        ],
        "interaction_classes": ["A", "C"],
    },
    {
        "domain": "lpg.ujjwal.gov.in",
        "official_name": "Ujjwala Yojana (LPG)",
        "category": "Welfare",
        "subcategory": "Energy",
        "url": "https://lpg.ujjwal.gov.in",
        "description": "Free LPG connection scheme for BPL families",
        "tasks": [
            {"name": "Apply for Ujjwala Connection", "description": "Register for free LPG connection under PMUY"},
            {"name": "Check Ujjwala Status", "description": "Track LPG connection application status"},
            {"name": "Link Aadhaar with LPG", "description": "Seed Aadhaar for subsidy transfer"},
            {"name": "Check Subsidy Credit", "description": "View DBT subsidy credited to bank account"},
        ],
        "interaction_classes": ["A", "C"],
    },

    # --- Land & Revenue ---
    {
        "domain": "ngdrs.gov.in",
        "official_name": "National Generic Document Registration System (NGDRS)",
        "category": "Land & Revenue",
        "subcategory": "Registration",
        "url": "https://ngdrs.gov.in",
        "description": "Generic platform for property and document registration across states",
        "tasks": [
            {"name": "Register Property Document", "description": "Online property sale deed/gift deed registration"},
            {"name": "Pay Stamp Duty", "description": "Calculate and pay stamp duty and registration fees online"},
            {"name": "Check Registration Status", "description": "Track document registration application"},
            {"name": "View Registration Details", "description": "Access registered document details by registration number"},
            {"name": "Book Appointment at Sub-Registrar", "description": "Schedule visit for document execution"},
        ],
        "interaction_classes": ["B", "F", "G"],
    },
    {
        "domain": "dilrmp.gov.in",
        "official_name": "Digital India Land Records Modernization Programme",
        "category": "Land & Revenue",
        "subcategory": "Land Records",
        "url": "https://dilrmp.gov.in",
        "description": "Digitized land records — ownership, maps, and mutation tracking",
        "tasks": [
            {"name": "View Land Records (Khasra/Khata)", "description": "Access digitized land records by survey number"},
            {"name": "Check Mutation Status", "description": "Track land ownership transfer status"},
            {"name": "View Cadastral Maps", "description": "Access digitized land maps and boundaries"},
            {"name": "Download Land Extract", "description": "Get official land record extract"},
            {"name": "Verify Land Title", "description": "Check ownership and encumbrance status"},
        ],
        "interaction_classes": ["A"],
    },

    # --- Passport & Visa ---
    {
        "domain": "registration.gov.in",
        "official_name": "Foreigners Regional Registration Office (FRRO)",
        "category": "Identity & Documents",
        "subcategory": "Foreigners",
        "url": "https://registration.gov.in",
        "description": "Foreigners registration, visa extension, and exit/entry permits",
        "tasks": [
            {"name": "Apply for Visa Extension", "description": "Foreign nationals extend Indian visa online"},
            {"name": "FRRO Registration", "description": "Mandatory registration for foreign nationals staying 180+ days"},
            {"name": "Apply for Exit Permit", "description": "Get exit permit for visa overstayers or lost passport cases"},
            {"name": "Check FRRO Appointment", "description": "Book appointment at FRRO/FRO office"},
        ],
        "interaction_classes": ["B", "C"],
    },
]


# ============================================================
# STATE GOVERNMENT PORTALS
# ============================================================

_STATE_PORTALS: list[dict[str, Any]] = [
    # --- Andhra Pradesh ---
    {
        "domain": "ap.gov.in",
        "official_name": "Government of Andhra Pradesh",
        "category": "State Government",
        "subcategory": "State Portal",
        "government_level": "state",
        "state": "Andhra Pradesh",
        "url": "https://ap.gov.in",
        "description": "Official portal for Andhra Pradesh state government services",
        "tasks": [
            {"name": "Apply for Caste Certificate", "description": "Apply for SC/ST/OBC caste certificate online"},
            {"name": "Apply for Income Certificate", "description": "Get income certificate for scholarship/government scheme eligibility"},
            {"name": "Apply for Residence Certificate", "description": "Proof of residence certificate online"},
            {"name": "Check Certificate Status", "description": "Track application status for various certificates"},
            {"name": "Pay Government Fees", "description": "Pay fees for various government services"},
            {"name": "File Grievance", "description": "Submit grievance to AP government"},
        ],
        "interaction_classes": ["A", "B", "C"],
    },
    {
        "domain": "ap.meeseva.telangana.gov.in",
        "official_name": "MeeSeva AP",
        "category": "State Government",
        "subcategory": "Citizen Services",
        "government_level": "state",
        "state": "Andhra Pradesh",
        "url": "https://mee-seva.ap.gov.in",
        "description": "One-stop citizen services portal for AP",
        "tasks": [
            {"name": "Apply for Certificates", "description": "Birth, death, caste, income, and other certificates"},
            {"name": "Pay Utility Bills", "description": "Electricity and water bill payments"},
            {"name": "Apply for Licenses", "description": "Trade license, driving license applications"},
        ],
        "interaction_classes": ["A", "B"],
    },

    # --- Bihar ---
    {
        "domain": "state.bihar.gov.in",
        "official_name": "Government of Bihar",
        "category": "State Government",
        "subcategory": "State Portal",
        "government_level": "state",
        "state": "Bihar",
        "url": "https://state.bihar.gov.in",
        "description": "Official portal for Bihar state government services",
        "tasks": [
            {"name": "Apply for Caste Certificate", "description": "Online caste certificate application for SC/ST/OBC"},
            {"name": "Land Records (Bhumijankari)", "description": "Check land records, khasra, khatauni online"},
            {"name": "Apply for Income Certificate", "description": "Get income certificate from Revenue Department"},
            {"name": "Check Application Status", "description": "Track certificate application progress"},
        ],
        "interaction_classes": ["A", "B"],
    },
    {
        "domain": "serviceonline.bihar.gov.in",
        "official_name": "Bihar RTPS (Right to Public Services)",
        "category": "State Government",
        "subcategory": "Service Delivery",
        "government_level": "state",
        "state": "Bihar",
        "url": "https://serviceonline.bihar.gov.in",
        "description": "Bihar's citizen service delivery platform — certificates, permissions, and more",
        "tasks": [
            {"name": "Apply for Caste Certificate", "description": "SC/ST/OBC certificate application"},
            {"name": "Apply for Income Certificate", "description": "Get income certificate online"},
            {"name": "Apply for Residence Certificate", "description": "Domicile/residence proof certificate"},
            {"name": "Apply for Character Certificate", "description": "Police clearance character certificate"},
            {"name": "Apply for Non-Creamy Layer Certificate", "description": "OBC non-creamy layer certificate"},
            {"name": "Check Application Status", "description": "Track all RTPS application statuses"},
            {"name": "Download Certificates", "description": "Download issued certificates"},
        ],
        "interaction_classes": ["A", "B"],
    },

    # --- Delhi ---
    {
        "domain": "delhi.gov.in",
        "official_name": "Government of NCT of Delhi",
        "category": "State Government",
        "subcategory": "State Portal",
        "government_level": "state",
        "state": "Delhi",
        "url": "https://delhi.gov.in",
        "description": "Official portal for Delhi government services and departments",
        "tasks": [
            {"name": "Apply for Trade License", "description": "New/renewal of trade license from MCD"},
            {"name": "Property Tax Payment", "description": "Pay property tax to MCD/NDMC online"},
            {"name": "Apply for Birth/Death Certificate", "description": "Register and get birth/death certificates"},
            {"name": "Water Tax Payment", "description": "Pay Delhi Jal Board water bill"},
            {"name": "Apply for Subsidy", "description": "Apply for various Delhi government welfare schemes"},
            {"name": "Check Vehicle Registration", "description": "Delhi transport services"},
            {"name": "File Grievance", "description": "Register complaint with Delhi government"},
        ],
        "interaction_classes": ["A", "B", "G"],
    },

    # --- Gujarat ---
    {
        "domain": "gujarat.gov.in",
        "official_name": "Government of Gujarat",
        "category": "State Government",
        "subcategory": "State Portal",
        "government_level": "state",
        "state": "Gujarat",
        "url": "https://gujarat.gov.in",
        "description": "Official portal for Gujarat state government services",
        "tasks": [
            {"name": "Digital Seva Setu", "description": "Access 100+ services online — certificates, permissions, payments"},
            {"name": "Land Records (AnyROR)", "description": "Check property ownership and 7/12 extracts online"},
            {"name": "Apply for Certificates", "description": "Income, caste, birth, death, and other certificates"},
            {"name": "Pay Property Tax", "description": "Municipal corporation property tax payment"},
        ],
        "interaction_classes": ["A", "B"],
    },

    # --- Goa ---
    {
        "domain": "goa.gov.in",
        "official_name": "Government of Goa",
        "category": "State Government",
        "subcategory": "State Portal",
        "government_level": "state",
        "state": "Goa",
        "url": "https://goa.gov.in",
        "description": "Official portal for Goa state government services",
        "tasks": [
            {"name": "Apply for Income Certificate", "description": "Get income certificate from collectorate"},
            {"name": "Apply for Caste Certificate", "description": "Caste certificate for reservation benefits"},
            {"name": "Property Tax Payment", "description": "Municipal property tax payment online"},
            {"name": "Check Application Status", "description": "Track certificate and application status"},
        ],
        "interaction_classes": ["A", "B"],
    },

    # --- Haryana ---
    {
        "domain": "haryana.gov.in",
        "official_name": "Government of Haryana",
        "category": "State Government",
        "subcategory": "State Portal",
        "government_level": "state",
        "state": "Haryana",
        "url": "https://haryana.gov.in",
        "description": "Official portal for Haryana state government services",
        "tasks": [
            {"name": "Apply for Certificates", "description": "Income, caste, residence, birth, death certificates"},
            {"name": "Antyodaya Sewa Portal", "description": "Apply for welfare schemes for BPL families"},
            {"name": "Check Land Records", "description": "Access Jamabandi and land ownership records"},
            {"name": "Property Registration", "description": "Online property registration and stamp duty payment"},
        ],
        "interaction_classes": ["A", "B"],
    },

    # --- Jharkhand ---
    {
        "domain": "jharkhand.gov.in",
        "official_name": "Government of Jharkhand",
        "category": "State Government",
        "subcategory": "State Portal",
        "government_level": "state",
        "state": "Jharkhand",
        "url": "https://jharkhand.gov.in",
        "description": "Official portal for Jharkhand state government services",
        "tasks": [
            {"name": "Apply for Certificates", "description": "Income, caste, domicile certificates online"},
            {"name": "Land Records", "description": "Access land records and property details"},
            {"name": "File Grievance", "description": "Register complaint with Jharkhand government"},
            {"name": "Pay Utility Bills", "description": "Electricity and water bill payment"},
        ],
        "interaction_classes": ["A", "B"],
    },

    # --- Karnataka ---
    {
        "domain": "karnataka.gov.in",
        "official_name": "Government of Karnataka",
        "category": "State Government",
        "subcategory": "State Portal",
        "government_level": "state",
        "state": "Karnataka",
        "url": "https://karnataka.gov.in",
        "description": "Official portal for Karnataka state government services",
        "tasks": [
            {"name": "Seva Sindhu Services", "description": "Access 1000+ government services online"},
            {"name": "Land Records (Bhoomi)", "description": "View RTC (Record of Rights), mutation, and land details"},
            {"name": "Apply for Certificates", "description": "Income, caste, birth, death, and other certificates"},
            {"name": "Check Application Status", "description": "Track Seva Sindhu application progress"},
            {"name": "Pay Property Tax", "description": "BBMP/ULB property tax payment"},
        ],
        "interaction_classes": ["A", "B"],
    },

    # --- Kerala ---
    {
        "domain": "kerala.gov.in",
        "official_name": "Government of Kerala",
        "category": "State Government",
        "subcategory": "State Portal",
        "government_level": "state",
        "state": "Kerala",
        "url": "https://kerala.gov.in",
        "description": "Official portal for Kerala state government services",
        "tasks": [
            {"name": "e-District Services", "description": "Apply for income, caste, birth, death, and other certificates"},
            {"name": "Land Tax Payment", "description": "Pay land revenue tax online"},
            {"name": "Check Certificate Status", "description": "Track application and issuance status"},
            {"name": "Kerala PSC Portal", "description": "Apply for government jobs via Kerala Public Service Commission"},
            {"name": "View Budget Documents", "description": "Access state budget documents and allocations"},
        ],
        "interaction_classes": ["A", "B", "C"],
    },

    # --- Madhya Pradesh ---
    {
        "domain": "mp.gov.in",
        "official_name": "Government of Madhya Pradesh",
        "category": "State Government",
        "subcategory": "State Portal",
        "government_level": "state",
        "state": "Madhya Pradesh",
        "url": "https://mp.gov.in",
        "description": "Official portal for Madhya Pradesh state government services",
        "tasks": [
            {"name": "MP e-District Services", "description": "Apply for certificates and government services online"},
            {"name": "Land Records (MP Bhulekh)", "description": "Access digitized land records and maps"},
            {"name": "MP Employment Portal", "description": "Register for government job opportunities"},
            {"name": "Check Scholarship Status", "description": "Track MP scholarship application and disbursement"},
        ],
        "interaction_classes": ["A", "B"],
    },

    # --- Maharashtra ---
    {
        "domain": "maharashtra.gov.in",
        "official_name": "Government of Maharashtra",
        "category": "State Government",
        "subcategory": "State Portal",
        "government_level": "state",
        "state": "Maharashtra",
        "url": "https://maharashtra.gov.in",
        "description": "Official portal for Maharashtra state government services",
        "tasks": [
            {"name": "Apply for Certificates", "description": "Income, caste, residence, birth, death certificates"},
            {"name": "E-Return Filing", "description": "File property tax returns for municipal corporations"},
            {"name": "Land Records (Mahabhulekh)", "description": "View 7/12 extracts and property cards online"},
            {"name": "Check Application Status", "description": "Track certificate application status"},
            {"name": "Pay Utility Bills", "description": "Electricity (MSEB/Adani/BEST) and water bill payment"},
            {"name": "MCGM Services", "description": "Municipal Corporation of Greater Mumbai services"},
        ],
        "interaction_classes": ["A", "B", "G"],
    },

    # --- Odisha ---
    {
        "domain": "odisha.gov.in",
        "official_name": "Government of Odisha",
        "category": "State Government",
        "subcategory": "State Portal",
        "government_level": "state",
        "state": "Odisha",
        "url": "https://odisha.gov.in",
        "description": "Official portal for Odisha state government services",
        "tasks": [
            {"name": "Apply for Certificates", "description": "Income, caste, residence, and other certificates online"},
            {"name": "Land Records (Bhulekh)", "description": "Access digitized land records and plots"},
            {"name": "G2C Services", "description": "Government to citizen services portal"},
            {"name": "Check Scholarship Status", "description": "Track state scholarship application"},
        ],
        "interaction_classes": ["A", "B"],
    },

    # --- Punjab ---
    {
        "domain": "punjab.gov.in",
        "official_name": "Government of Punjab",
        "category": "State Government",
        "subcategory": "State Portal",
        "government_level": "state",
        "state": "Punjab",
        "url": "https://punjab.gov.in",
        "description": "Official portal for Punjab state government services",
        "tasks": [
            {"name": "Sewa Kendra Services", "description": "Access certificates, licenses, and welfare schemes"},
            {"name": "Land Records (Jamabandi)", "description": "View land ownership and mutation records"},
            {"name": "Pay Utility Bills", "description": "Electricity and water bill payments"},
            {"name": "Apply for Pension", "description": "Social security pension applications"},
        ],
        "interaction_classes": ["A", "B"],
    },

    # --- Rajasthan ---
    {
        "domain": "rajasthan.gov.in",
        "official_name": "Government of Rajasthan",
        "category": "State Government",
        "subcategory": "State Portal",
        "government_level": "state",
        "state": "Rajasthan",
        "url": "https://rajasthan.gov.in",
        "description": "Official portal for Rajasthan state government services",
        "tasks": [
            {"name": "Apply for Certificates", "description": "Income, caste, domicile, birth, death certificates"},
            {"name": "Land Records (Apna Khata)", "description": "View Khasra, Khatauni, and land records online"},
            {"name": "Rajasthan SSO Services", "description": "Single Sign-On access to 500+ government services"},
            {"name": "Check Scholarship Status", "description": "Track Rajasthan scholarship application"},
            {"name": "Job Portal Registration", "description": "Register for Rajasthan government jobs (REET, RPSC)"},
        ],
        "interaction_classes": ["A", "B", "C"],
    },

    # --- Tamil Nadu ---
    {
        "domain": "tn.gov.in",
        "official_name": "Government of Tamil Nadu",
        "category": "State Government",
        "subcategory": "State Portal",
        "government_level": "state",
        "state": "Tamil Nadu",
        "url": "https://tn.gov.in",
        "description": "Official portal for Tamil Nadu state government services",
        "tasks": [
            {"name": "Apply for Certificates", "description": "Income, caste, residence, community certificates online"},
            {"name": "TN e-Sevai Services", "description": "Access 200+ government services via e-Sevai centres"},
            {"name": "Land Records (Patta Chitta)", "description": "View land ownership (Patta) and property details (Chitta)"},
            {"name": "Check Application Status", "description": "Track certificate application progress"},
            {"name": "Pay Property Tax", "description": "Corporation/municipal property tax payment"},
        ],
        "interaction_classes": ["A", "B"],
    },

    # --- Telangana ---
    {
        "domain": "telangana.gov.in",
        "official_name": "Government of Telangana",
        "category": "State Government",
        "subcategory": "State Portal",
        "government_level": "state",
        "state": "Telangana",
        "url": "https://telangana.gov.in",
        "description": "Official portal for Telangana state government services",
        "tasks": [
            {"name": "MeeSeva Services", "description": "Access citizen services — certificates, licenses, payments"},
            {"name": "Land Records (Dharani)", "description": "Online land registration and mutation portal"},
            {"name": "Apply for Certificates", "description": "Income, caste, residence, birth, death certificates"},
            {"name": "Check Application Status", "description": "Track MeeSeva application status"},
            {"name": "TS-iPASS", "description": "Industrial project approvals and clearances"},
        ],
        "interaction_classes": ["A", "B", "C"],
    },

    # --- Uttar Pradesh ---
    {
        "domain": "up.gov.in",
        "official_name": "Government of Uttar Pradesh",
        "category": "State Government",
        "subcategory": "State Portal",
        "government_level": "state",
        "state": "Uttar Pradesh",
        "url": "https://up.gov.in",
        "description": "Official portal for Uttar Pradesh state government services",
        "tasks": [
            {"name": "Apply for Certificates", "description": "Income, caste, residence, birth, death certificates"},
            {"name": "Land Records (UP Bhulekh)", "description": "View Khasra, Khatauni, and land details online"},
            {"name": "e-District Services", "description": "Access 500+ government services online"},
            {"name": "Check Scholarship Status", "description": "Track UP scholarship application"},
            {"name": "UP Police Services", "description": "FIR registration, character certificate, and verification"},
            {"name": "RERA Registration", "description": "Real estate regulatory authority registration"},
        ],
        "interaction_classes": ["A", "B", "C"],
    },

    # --- West Bengal ---
    {
        "domain": "wb.gov.in",
        "official_name": "Government of West Bengal",
        "category": "State Government",
        "subcategory": "State Portal",
        "government_level": "state",
        "state": "West Bengal",
        "url": "https://wb.gov.in",
        "description": "Official portal for West Bengal state government services",
        "tasks": [
            {"name": "Apply for Certificates", "description": "Income, caste, residence, birth, death certificates"},
            {"name": "Land Records (Banglarbhumi)", "description": "View land records, plot information, and mutation status"},
            {"name": "Paras Portal", "description": "Access citizen services and welfare schemes"},
            {"name": "Check Scholarship Status", "description": "Track WB pre-matric/post-matric scholarship"},
            {"name": "Pay Property Tax", "description": "Municipal property tax payment"},
        ],
        "interaction_classes": ["A", "B"],
    },
]


# ============================================================
# TRUSTED DOMAIN REGISTRY
# ============================================================

class TrustedDomainRegistry:
    """Registry of trusted government domains with full metadata.

    Provides categorized access to Indian government portals
    with detailed task information for each site.
    """

    def __init__(self) -> None:
        self._domains: dict[str, DomainEntry] = {}
        self._load_defaults()

    def _load_defaults(self) -> None:
        """Load default trusted government domains."""
        all_portals = _CENTRAL_PORTALS + _STATE_PORTALS
        for entry_data in all_portals:
            try:
                domain_val = entry_data.get("domain", "")
                if not isinstance(domain_val, str) or not domain_val:
                    continue

                # Convert tasks from dicts to SiteTask objects
                raw_tasks = entry_data.pop("tasks", [])
                tasks = [SiteTask(**t) for t in raw_tasks]

                entry = DomainEntry(**entry_data, tasks=tasks)
                self._domains[entry.domain] = entry
            except Exception:
                continue

    def is_trusted(self, url: str) -> bool:
        """Check if a URL's domain is in the trusted registry."""
        domain = self._extract_domain(url)
        if not domain:
            return False
        entry = self._domains.get(domain)
        return entry is not None and entry.allowed and entry.verified

    def is_known(self, url: str) -> bool:
        """Check if a URL's domain is known (even if not trusted)."""
        domain = self._extract_domain(url)
        if not domain:
            return False
        return domain in self._domains

    def get_entry(self, url: str) -> DomainEntry | None:
        """Get the domain entry for a URL."""
        domain = self._extract_domain(url)
        if not domain:
            return None
        return self._domains.get(domain)

    def get_constraints(self, url: str) -> list[str]:
        """Get special constraints for a domain."""
        entry = self.get_entry(url)
        if entry:
            return entry.special_constraints
        return []

    def register(self, entry: DomainEntry) -> None:
        """Register a new trusted domain."""
        self._domains[entry.domain] = entry

    def _extract_domain(self, url: str) -> str | None:
        """Extract domain from URL or plain domain string."""
        try:
            # Handle plain domain strings (e.g. "uidai.gov.in")
            if "." in url and "/" not in url:
                domain = url.lower()
                if domain.startswith("www."):
                    domain = domain[4:]
                return domain
            # Handle full URLs (e.g. "https://uidai.gov.in")
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            if domain.startswith("www."):
                domain = domain[4:]
            return domain
        except Exception:
            return None

    def list_domains(self) -> list[str]:
        """List all registered domains."""
        return sorted(self._domains.keys())

    def list_categories(self) -> list[str]:
        """List all unique categories."""
        categories = set()
        for entry in self._domains.values():
            categories.add(entry.category)
        return sorted(categories)

    def list_by_category(self, category: str) -> list[DomainEntry]:
        """Get all entries in a specific category."""
        return [
            e for e in self._domains.values() if e.category == category
        ]

    def list_by_subcategory(self, subcategory: str) -> list[DomainEntry]:
        """Get all entries in a specific subcategory."""
        return [
            e for e in self._domains.values() if e.subcategory == subcategory
        ]

    def list_by_state(self, state: str) -> list[DomainEntry]:
        """Get all entries for a specific state."""
        return [
            e for e in self._domains.values()
            if e.state.lower() == state.lower()
        ]

    def search(self, query: str) -> list[DomainEntry]:
        """Search entries by name, description, or task names."""
        query_lower = query.lower()
        results = []
        for entry in self._domains.values():
            # Search in name, description, category
            if (
                query_lower in entry.official_name.lower()
                or query_lower in entry.description.lower()
                or query_lower in entry.category.lower()
                or query_lower in entry.subcategory.lower()
            ):
                results.append(entry)
                continue
            # Search in tasks
            for task in entry.tasks:
                if (
                    query_lower in task.name.lower()
                    or query_lower in task.description.lower()
                ):
                    results.append(entry)
                    break
        return results

    def get_all_tasks_for_domain(self, domain: str) -> list[SiteTask]:
        """Get all tasks for a specific domain."""
        entry = self._domains.get(domain)
        if entry:
            return entry.tasks
        return []

    def get_categorized_view(self) -> dict[str, dict[str, list[DomainEntry]]]:
        """Get a fully categorized view: category -> subcategory -> entries."""
        view: dict[str, dict[str, list[DomainEntry]]] = {}
        for entry in self._domains.values():
            if entry.category not in view:
                view[entry.category] = {}
            sub = entry.subcategory or "General"
            if sub not in view[entry.category]:
                view[entry.category][sub] = []
            view[entry.category][sub].append(entry)
        return view

    def get_stats(self) -> dict[str, int]:
        """Get statistics about the registry."""
        total_tasks = sum(len(e.tasks) for e in self._domains.values())
        auth_required = sum(
            1 for e in self._domains.values()
            if any(t.requires_auth for t in e.tasks)
        )
        return {
            "total_sites": len(self._domains),
            "total_tasks": total_tasks,
            "categories": len(self.list_categories()),
            "central_sites": sum(
                1 for e in self._domains.values()
                if e.government_level == "central"
            ),
            "state_sites": sum(
                1 for e in self._domains.values()
                if e.government_level == "state"
            ),
            "sites_requiring_auth": auth_required,
        }

    def __len__(self) -> int:
        return len(self._domains)

    def __contains__(self, domain: str) -> bool:
        return domain in self._domains
