"""Comprehensive Indian government site registry.

All major Indian government portals categorized by service domain,
with detailed task descriptions for each portal.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class SiteTask(BaseModel):
    """A specific task that can be performed on a government portal."""

    name: str = Field(description="Task name")
    description: str = Field(description="What this task does")
    instructions: str = Field(
        default="",
        description=(
            "Detailed step-by-step instructions for the LLM agent. "
            "Should describe the exact sequence of actions: what links to click, "
            "what fields to fill, what values to use, what buttons to press. "
            "The agent will follow these instructions on the live page."
        ),
    )
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
            {
                "name": "Download Aadhaar",
                "description": "Download e-Aadhaar PDF using Aadhaar number or enrollment ID",
                "instructions": "Navigate to uidai.gov.in. Click 'Download Aadhaar' under the 'Get Aadhaar' section. On the download page, select 'Aadhaar Number' radio button. Enter the 12-digit Aadhaar number in the input field. Solve the CAPTCHA by typing the characters shown. Click 'Send OTP' button. Wait for the OTP to arrive on the registered mobile number. Enter the 6-digit OTP in the OTP field. Click 'Verify And Download' button. The e-Aadhaar PDF will be downloaded.",
                "requires_auth": True,
                "difficulty": "easy",
            },
            {
                "name": "Verify Aadhaar",
                "description": "Check if an Aadhaar number is valid and active",
                "instructions": "Navigate to uidai.gov.in. Click 'Verify Aadhaar' under the 'Aadhaar Services' section. Enter the 12-digit Aadhaar number in the input field. Solve the CAPTCHA. Click 'Verify' button. The page will display whether the Aadhaar number exists and is active, along with the age, gender, state, and last3 digits of the registered mobile number.",
                "difficulty": "easy",
            },
            {
                "name": "Update Aadhaar Details",
                "description": "Name, address, DOB, gender, mobile, email updates online",
                "instructions": "Navigate to uidai.gov.in. Click 'Update Aadhaar' under 'Get Aadhaar'. Click 'Update Demographics Data Online' which opens the myAadhaar portal (myaadhaar.uidai.gov.in). Login with Aadhaar number and OTP. Select the field to update (Name, DOB, Gender, Address, Email, or Mobile). Upload supporting document if required. Enter the new value. Review changes and click 'Submit'. Note the URN (Update Request Number) for tracking.",
                "requires_auth": True,
                "difficulty": "medium",
            },
            {
                "name": "Book Aadhaar Appointment",
                "description": "Schedule visit to Aadhaar Enrolment/Update Centre",
                "instructions": "Navigate to uidai.gov.in. Click 'Book an Appointment' under 'Get Aadhaar'. Select your city/location from the dropdown or search by PIN code. Choose an available Aadhaar Enrolment Centre. Select an available date from the calendar. Choose a time slot. Enter the required details: name, mobile number, and the type of service needed (new enrollment or update). Click 'Submit' to confirm the appointment. Note the appointment reference number.",
                "requires_auth": True,
                "difficulty": "easy",
            },
            {
                "name": "Check Aadhaar Update Status",
                "description": "Track status of Aadhaar update/enrollment request",
                "instructions": "Navigate to uidai.gov.in. Click 'Check Aadhaar Status' under 'Get Aadhaar'. On the myAadhaar portal, enter the Enrolment ID (EID) or URN (Update Request Number). Enter the date and time from the acknowledgment slip. Solve the CAPTCHA. Click 'Check Status'. The page will show whether the update is pending, processed, or completed.",
                "difficulty": "easy",
            },
            {
                "name": "Generate Virtual ID",
                "description": "Create VID for Aadhaar authentication without sharing Aadhaar number",
                "instructions": "Navigate to uidai.gov.in. Click 'Generate Virtual ID' under 'Aadhaar Services'. Enter the 12-digit Aadhaar number. Solve the CAPTCHA. Click 'Send OTP'. Enter the OTP received on registered mobile. Click 'Generate'. A 16-digit Virtual ID (VID) will be displayed. Copy or note it down. VID can be used instead of Aadhaar number for authentication.",
                "requires_auth": True,
                "difficulty": "easy",
            },
            {
                "name": "Lock/Unlock Biometrics",
                "description": "Temporarily lock Aadhaar biometrics for security",
                "instructions": "Navigate to uidai.gov.in. Click 'Lock/Unlock Biometrics' under 'Aadhaar Services'. Login with Aadhaar number and OTP. Select 'Lock Biometrics' to lock or 'Unlock Biometrics' to unlock. When locked, biometric authentication (fingerprint, iris) will be disabled. This prevents unauthorized use of biometrics. Click 'Submit' to confirm.",
                "requires_auth": True,
                "difficulty": "easy",
            },
            {
                "name": "Aadhaar Paperless Offline eKYC",
                "description": "Download XML-based offline KYC for third-party verification",
                "instructions": "Navigate to uidai.gov.in. Click 'Offline eKYC' under 'Aadhaar Services'. Login with Aadhaar number and OTP. Create aShare Code (4-digit PIN) that will be used to open the XML file. Click 'Download' to get the zip file containing the signed XML. Share this XML file along with the Share Code with the requesting organization for verification.",
                "requires_auth": True,
                "difficulty": "easy",
            },
            {
                "name": "Retrieve Lost EID/Aadhaar",
                "description": "Find forgotten enrollment ID or Aadhaar number via mobile/email",
                "instructions": "Navigate to uidai.gov.in. Click 'Retrieve EID / Aadhaar number' under 'Get Aadhaar'. Enter your full name as on Aadhaar. Enter registered mobile number or email address. Solve the CAPTCHA. Click 'Send OTP'. Enter the OTP received. Click 'Verify'. The Aadhaar number or EID will be sent to your registered mobile/email.",
                "difficulty": "easy",
            },
        ],
        "interaction_classes": ["A", "C"],
    },
    {
        "domain": "meripehchaan.gov.in",
        "official_name": "MeriPehchaan",
        "category": "Identity & Documents",
        "subcategory": "Identity",
        "url": "https://meripehchaan.gov.in",
        "description": "India's national single sign-on portal — authenticate with Aadhaar, PAN, or Driving License",
        "tasks": [
            {
                "name": "View Digital Aadhaar",
                "description": "Access Aadhaar card on mobile device",
                "instructions": "Navigate to meripehchaan.gov.in. Click 'Login' button. Select 'Aadhaar' as the login method. Enter the 12-digit Aadhaar number. Click 'Get OTP'. Enter the OTP received on Aadhaar-linked mobile. Click 'Login'. Once logged in, navigate to 'My Documents' or 'DigiLocker' section. Click on 'Aadhaar Card' to view the digital version.",
                "requires_auth": True,
                "difficulty": "easy",
            },
            {
                "name": "Share OTP-based Verification",
                "description": "Share Aadhaar verification with service providers",
                "instructions": "Navigate to meripehchaan.gov.in. Login with Aadhaar number and OTP. Navigate to 'Share Document' section. Select 'Aadhaar Card' from the list of documents. Enter the organization name or code that needs verification. Click 'Share'. A sharing code will be generated. Share this code with the requesting organization for verification.",
                "requires_auth": True,
                "difficulty": "medium",
            },
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
            {
                "name": "Apply for New Passport",
                "description": "Fresh passport application with document upload and appointment",
                "instructions": "Navigate to passportindia.gov.in. Click 'New User? Register Now' to create an account or click 'Existing User? Login'. Login with Login ID and password. Click 'Apply for Fresh Ordinary Passport'. Fill the application form: enter personal details (name, DOB, place of birth, gender, marital status, address), parents' details, and previous passport details (if any). Upload required documents: proof of address (Aadhaar/Voter ID), proof of DOB (birth certificate), and identity proof. Review the form and click 'Submit'. Pay the fee online via net banking/UPI/card. Book appointment at the nearest Passport Seva Kendra (PSK). Print the application receipt.",
                "requires_auth": True,
                "requires_payment": True,
                "difficulty": "hard",
            },
            {
                "name": "Renew/Reissue Passport",
                "description": "Renew expired passport or reissue for name change, damage, etc.",
                "instructions": "Navigate to passportindia.gov.in. Login with existing credentials. Click 'Reissue of Passport'. Select the reason for reissue: expiry, exhaustion of pages, damage, lost, or change in personal details. Fill the form with current details. Upload supporting documents based on reissue reason. Pay the fee online. Book appointment at PSK. Print the application receipt.",
                "requires_auth": True,
                "requires_payment": True,
                "difficulty": "hard",
            },
            {
                "name": "Check Application Status",
                "description": "Track passport application by file number",
                "instructions": "Navigate to passportindia.gov.in. Click 'Track Your Application Status' on the home page. Enter the file number (format: XX000000000000). Enter date of birth. Click 'Track'. The status will show: Application Submitted, Police Verification Pending, Passport Printed, Passport Dispatched, or similar status.",
                "difficulty": "easy",
            },
            {
                "name": "Book Appointment at PSK",
                "description": "Schedule appointment at Passport Seva Kendra",
                "instructions": "Navigate to passportindia.gov.in. Login with credentials. Click 'View Submitted Applications'. Select the application for which appointment is needed. Click 'Pay and Schedule Appointment'. Choose the PSK location. Select an available date from the calendar. Choose a time slot. Confirm the appointment. Pay the fee if not already paid.",
                "requires_auth": True,
                "requires_payment": True,
                "difficulty": "medium",
            },
            {
                "name": "Pay Passport Fee Online",
                "description": "Online fee payment for passport services",
                "instructions": "Navigate to passportindia.gov.in. Login with credentials. Click 'View Submitted Applications'. Select the application needing payment. Click 'Pay Fee'. Choose payment method: net banking, credit/debit card, or UPI. Enter payment details. Confirm the payment. Note the payment reference number.",
                "requires_auth": True,
                "requires_payment": True,
                "difficulty": "easy",
            },
            {
                "name": "Download Passport Application Form",
                "description": "Print filled application form for PSK visit",
                "instructions": "Navigate to passportindia.gov.in. Login with credentials. Click 'View Submitted Applications'. Select the application. Click 'Print Application Form'. The PDF form will be downloaded. Print it and carry it to the PSK appointment along with original documents.",
                "requires_auth": True,
                "difficulty": "easy",
            },
            {
                "name": "View File Authentication Status",
                "description": "Check police verification and file status",
                "instructions": "Navigate to passportindia.gov.in. Login with credentials. Click 'View Status' for the submitted application. The page shows the complete timeline: Application Submitted, Police Verification Initiated, Police Verification Completed, File Clearance, Passport Printed, Dispatched.",
                "requires_auth": True,
                "difficulty": "easy",
            },
            {
                "name": "Track Police Verification Status",
                "description": "See if police verification is complete",
                "instructions": "Navigate to passportindia.gov.in. Click 'Track Your Application Status'. Enter the file number and date of birth. Click 'Track'. Look for the police verification status in the timeline. It will show whether verification is Pending, Initiated, Completed, or if there are any adverse remarks.",
                "difficulty": "easy",
            },
            {
                "name": "Get Police Clearance Certificate",
                "description": "Apply for PCC for immigration/employment",
                "instructions": "Navigate to passportindia.gov.in. Login with credentials. Click 'Apply for Police Clearance Certificate'. Fill the form with personal details and current address. Upload address proof and identity documents. Pay the fee online. Book appointment at the nearest PSK. Print the application receipt and attend the appointment with original documents.",
                "requires_auth": True,
                "requires_payment": True,
                "difficulty": "medium",
            },
            {
                "name": "Surrender Certificate",
                "description": "Apply for surrender certificate for renounced Indian passport",
                "instructions": "Navigate to passportindia.gov.in. Login with credentials. Click 'Apply for Surrender Certificate'. Enter details of the Indian passport being surrendered. Fill personal details and reason for surrender (acquired foreign nationality). Upload the foreign passport copy and Indian passport copy. Pay the fee. Book appointment at PSK. Attend the appointment with original documents.",
                "requires_auth": True,
                "requires_payment": True,
                "difficulty": "medium",
            },
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
            {
                "name": "Apply for Learner's License",
                "description": "Apply for new learner's driving license online",
                "instructions": "Navigate to parivahan.gov.in. Click 'Driving License Related Services' under 'License Related Services'. Select your state. Click 'Apply for New Learner's License'. Fill personal details (name, DOB, address, blood group). Upload photo, signature, and age proof (Aadhaar/birth certificate). Upload address proof. Pay the fee online. Book slot at the nearest RTO for the online test. Attend the test at the RTO. If passed, the learner's license is generated.",
                "requires_auth": True,
                "requires_payment": True,
                "difficulty": "medium",
            },
            {
                "name": "Apply for Permanent Driving License",
                "description": "Upgrade from learner's to permanent driving license",
                "instructions": "Navigate to parivahan.gov.in. Click 'Driving License Related Services'. Select your state. Click 'Apply for Permanent Driving License'. Enter learner's license number. Fill the form with vehicle class details. Upload required documents (learner's license copy, photos, medical certificate). Pay the fee. Book slot for driving test at RTO. Attend the test. If passed, permanent DL is dispatched.",
                "requires_auth": True,
                "requires_payment": True,
                "difficulty": "medium",
            },
            {
                "name": "Renew Driving License",
                "description": "Renew expired or expiring driving license",
                "instructions": "Navigate to parivahan.gov.in. Click 'Driving License Related Services'. Select your state. Click 'Renewal of Driving License'. Enter the DL number. Verify details. Upload recent passport-size photo and medical certificate (Form 1A). Pay the renewal fee online. The renewed DL will be dispatched to your address.",
                "requires_auth": True,
                "requires_payment": True,
                "difficulty": "easy",
            },
            {
                "name": "International Driving Permit",
                "description": "Apply for IDP for driving abroad",
                "instructions": "Navigate to parivahan.gov.in. Click 'Driving License Related Services'. Select your state. Click 'International Driving Permit'. Enter DL number. Fill personal details and travel details (destination country, passport number). Upload DL copy, passport copy, and visa copy. Pay the fee. The IDP will be generated and dispatched.",
                "requires_auth": True,
                "requires_payment": True,
                "difficulty": "medium",
            },
            {
                "name": "Vehicle Registration",
                "description": "New vehicle registration, transfer of ownership",
                "instructions": "Navigate to parivahan.gov.in. Click 'Vehicle Related Services'. Select your state and RTO. Click 'Apply for Registration of New Vehicle'. Enter vehicle details (chassis number, engine number, manufacturer, model). Upload invoice, insurance certificate, and pollution certificate. Pay the road tax and registration fee online. The RC will be generated after verification.",
                "requires_auth": True,
                "requires_payment": True,
                "difficulty": "hard",
            },
            {
                "name": "RC Renewal",
                "description": "Renew Registration Certificate",
                "instructions": "Navigate to parivahan.gov.in. Click 'Vehicle Related Services'. Select your state. Click 'Renewal of Registration'. Enter the vehicle registration number. Verify vehicle details. Upload fitness certificate and insurance. Pay the renewal fee and road tax. The renewed RC will be dispatched.",
                "requires_auth": True,
                "requires_payment": True,
                "difficulty": "medium",
            },
            {
                "name": "Address Change in DL/RC",
                "description": "Update address in driving license or RC",
                "instructions": "Navigate to parivahan.gov.in. Click 'Driving License Related Services' for DL or 'Vehicle Related Services' for RC. Select your state. Click 'Change of Address'. Enter DL or RC number. Upload new address proof (Aadhaar/utility bill). Pay the fee. The updated document will be dispatched.",
                "requires_auth": True,
                "requires_payment": True,
                "difficulty": "easy",
            },
            {
                "name": "Fancy Number Booking",
                "description": "Book premium vehicle registration numbers",
                "instructions": "Navigate to parivahan.gov.in. Click 'Vehicle Related Services'. Select your state and RTO. Click 'Fancy Number Booking'. Choose the vehicle category (two-wheeler/four-wheeler). Select the desired number from available options or enter a custom number. Pay the premium amount online. The number is reserved for 15 days for vehicle registration.",
                "requires_auth": True,
                "requires_payment": True,
                "difficulty": "medium",
            },
            {
                "name": "Pay Traffic Challan",
                "description": "View and pay pending traffic fines online",
                "instructions": "Navigate to parivahan.gov.in. Click 'Pay Traffic Challan' under 'Check Pending Vehicles'. Enter the challan number or vehicle registration number. View the challan details (violation, date, location, fine amount). Select the challan to pay. Choose payment method (net banking/card/UPI). Complete the payment. Download the payment receipt.",
                "requires_payment": True,
                "difficulty": "easy",
            },
            {
                "name": "Check Vehicle Tax Status",
                "description": "Verify road tax payment status",
                "instructions": "Navigate to parivahan.gov.in. Click 'Vehicle Related Services'. Select your state. Click 'Check Tax Status'. Enter the vehicle registration number. The page will display the road tax status: Paid, Pending, or Expired along with the amount and validity period.",
                "difficulty": "easy",
            },
            {
                "name": "NOC for Vehicle Transfer",
                "description": "Apply for No Objection Certificate for inter-state transfer",
                "instructions": "Navigate to parivahan.gov.in. Click 'Vehicle Related Services'. Select your state and current RTO. Click 'NOC for Vehicle Transfer'. Enter vehicle registration number. Verify vehicle details. Pay the fee. The NOC will be generated after RTO verification. This is needed when transferring a vehicle to another state.",
                "requires_auth": True,
                "requires_payment": True,
                "difficulty": "medium",
            },
            {
                "name": "Duplicate DL/RC",
                "description": "Apply for duplicate license or registration certificate",
                "instructions": "Navigate to parivahan.gov.in. Click 'Driving License Related Services' for DL or 'Vehicle Related Services' for RC. Select your state. Click 'Issue of Duplicate DL/RC'. Enter the DL or RC number. Upload FIR copy (if stolen) and identity proof. Pay the fee. The duplicate document will be dispatched.",
                "requires_auth": True,
                "requires_payment": True,
                "difficulty": "medium",
            },
            {
                "name": "Check DL/RC Status",
                "description": "Verify driving license or RC validity",
                "instructions": "Navigate to parivahan.gov.in. Click 'Know Your Vehicle' or 'Check DL Status'. Enter the DL number or vehicle registration number. The page will display the validity status, expiry date, vehicle class, and any pending violations or actions.",
                "difficulty": "easy",
            },
            {
                "name": "Book Slot for Test",
                "description": "Schedule driving test at RTO",
                "instructions": "Navigate to parivahan.gov.in. Click 'Driving License Related Services'. Select your state. Click 'LL Test Slot Booking' or 'DL Test Slot Booking'. Enter the application number or learner's license number. Select the RTO. Choose an available date from the calendar. Select a time slot. Confirm the booking. Print the appointment letter.",
                "requires_auth": True,
                "difficulty": "easy",
            },
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
            {"name": "Pay Road Tax Online", "description": "Pay motor vehicle tax for new/used vehicles",
                "instructions": "Navigate to the portal and perform: Pay motor vehicle tax for new/used vehicles. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Vehicle Fitness Certificate", "description": "Apply for vehicle fitness certificate renewal",
                "instructions": "Navigate to the portal and perform: Apply for vehicle fitness certificate renewal. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Ownership Transfer", "description": "Transfer vehicle ownership to new buyer",
                "instructions": "Navigate to the portal and perform: Transfer vehicle ownership to new buyer. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Hypothecation Addition/Removal", "description": "Add or remove bank lien on vehicle RC",
                "instructions": "Navigate to the portal and perform: Add or remove bank lien on vehicle RC. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check Vehicle Details", "description": "View vehicle registration details, owner, tax status",
                "instructions": "Navigate to the portal and perform: View vehicle registration details, owner, tax status. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Apply for BH Series", "description": "Bharat Series registration for seamless inter-state transfer",
                "instructions": "Navigate to the portal and perform: Bharat Series registration for seamless inter-state transfer. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {
                "name": "File Income Tax Return (ITR)",
                "description": "File annual income tax return online with pre-filled data",
                "instructions": "Navigate to incometax.gov.in. Click 'Login' and enter PAN number as username, enter password. After login, click 'e-File' menu, then 'Income Tax Returns', then 'File Income Tax Return'. Select the Assessment Year. Select the appropriate ITR form (ITR-1 for salaried, ITR-3 for business). The form will be pre-filled with data from Form 16 and AIS. Verify all pre-filled data. Fill in remaining details: income, deductions under Section 80C/80D/etc., tax paid. Review the tax computation. Click 'Preview and Submit'. Verify the return. e-Verify using Aadhaar OTP, net banking, or bank account. Note the acknowledgement number.",
                "requires_auth": True,
                "difficulty": "hard",
            },
            {
                "name": "Check ITR Status",
                "description": "Track processing status of filed returns",
                "instructions": "Navigate to incometax.gov.in. Login with PAN and password. Click 'e-File' menu, then 'Income Tax Returns', then 'View Filed Returns'. Select the assessment year. The status will show: Return Filed, Successfully e-Verified, Processing Completed, Refund Issued, or Demand Raised.",
                "requires_auth": True,
                "difficulty": "easy",
            },
            {
                "name": "Link Aadhaar with PAN",
                "description": "Mandatory linking of Aadhaar and PAN",
                "instructions": "Navigate to incometax.gov.in. Click 'Link Aadhaar' on the home page or under 'Quick Links'. Enter PAN number and Aadhaar number. Click 'Validate'. If already linked, it will show confirmation. If not linked, enter name as per Aadhaar and mobile number. Click 'Link Aadhaar'. Enter OTP received on Aadhaar-linked mobile. Click 'Validate'. The linking request will be submitted.",
                "difficulty": "easy",
            },
            {
                "name": "View Form 26AS",
                "description": "Download annual tax statement (TDS/TCS credits)",
                "instructions": "Navigate to incometax.gov.in. Login with PAN and password. Click 'e-File' menu, then 'View Form 26AS' under 'Tax Credit'. This redirects to TRACES portal (tdscpc.gov.in). Select the Assessment Year. Choose the format (HTML/PDF). Click 'View/Download'. Form 26AS shows TDS deducted by employers, TCS credits, self-assessment tax paid, and advance tax details.",
                "requires_auth": True,
                "difficulty": "easy",
            },
            {
                "name": "View AIS (Annual Information Statement)",
                "description": "Comprehensive view of financial transactions reported to IT dept",
                "instructions": "Navigate to incometax.gov.in. Login with PAN and password. Click 'Services' menu, then 'Annual Information Statement (AIS)'. Select the Financial Year. The AIS shows all financial transactions: salary, interest, dividends, securities transactions, mutual fund purchases, foreign remittances, etc. You can download it as PDF.",
                "requires_auth": True,
                "difficulty": "easy",
            },
            {
                "name": "Download PAN Card",
                "description": "Get e-PAN using Aadhaar (instant/electronic PAN)",
                "instructions": "Navigate to incometax.gov.in. Click 'Instant E-PAN' under 'Quick Links'. Enter 12-digit Aadhaar number. Click 'Generate Aadhaar OTP'. Enter the OTP received. Submit the request. The e-PAN PDF will be sent to the Aadhaar-linked email. You can also download it from the same page using the acknowledgement number.",
                "difficulty": "easy",
            },
            {
                "name": "Apply for New PAN",
                "description": "Apply for new PAN card via Aadhaar-based e-KYC",
                "instructions": "Navigate to incometax.gov.in. Click 'Instant E-PAN' under 'Quick Links'. Click 'Get New e-PAN'. Enter Aadhaar number. Authenticate with Aadhaar OTP. Verify the pre-filled details from Aadhaar. Submit the application. The PAN will be generated instantly and sent to Aadhaar-linked email.",
                "difficulty": "easy",
            },
            {
                "name": "Correct PAN Details",
                "description": "Update/correct name, DOB, address on PAN",
                "instructions": "Navigate to incometax.gov.in. Click 'Settings' or 'Profile' after login. Click 'Update Details in PAN'. Select the field to correct: Name, DOB, or Address. Upload supporting documents (Aadhaar for name/DOB, utility bill for address). Submit the correction request. Track status under 'View Filed Requests'.",
                "requires_auth": True,
                "difficulty": "medium",
            },
            {
                "name": "Pay Advance Tax",
                "description": "Pay quarterly advance tax online",
                "instructions": "Navigate to incometax.gov.in. Click 'Pay Tax' under 'Quick Links'. Select 'Advance Tax' as the payment type. Enter PAN, assessment year, and state. Calculate the advance tax amount based on estimated income. Choose payment method: net banking, debit card, or UPI. Complete the payment. Download the challan (receipt) for records.",
                "requires_auth": True,
                "requires_payment": True,
                "difficulty": "medium",
            },
            {
                "name": "Check Refund Status",
                "description": "Track income tax refund status",
                "instructions": "Navigate to incometax.gov.in. Login with PAN and password. Click 'View Filed Returns' under 'e-File'. Select the assessment year. The refund status will show: Refund Issued, Refund Failed, Refund Adjusted Against Demand, or Refund Pending. If issued, note the ECS reference number.",
                "requires_auth": True,
                "difficulty": "easy",
            },
            {
                "name": "View e-Proceedings",
                "description": "Access tax assessment and scrutiny notices",
                "instructions": "Navigate to incometax.gov.in. Login with PAN and password. Click 'e-File' menu, then 'Proceedings'. View all pending and completed proceedings: scrutiny notices, assessment orders, demand notices. Click on any notice to view details and respond.",
                "requires_auth": True,
                "difficulty": "easy",
            },
            {
                "name": "Submit Response to Notice",
                "description": "Respond to IT department notices online",
                "instructions": "Navigate to incometax.gov.in. Login with PAN and password. Click 'e-File' > 'Proceedings'. Select the notice requiring response. Click 'Submit Response'. Fill in the response form with supporting details. Upload relevant documents. Submit the response before the due date.",
                "requires_auth": True,
                "difficulty": "medium",
            },
            {
                "name": "Verify PAN",
                "description": "Check PAN validity and details",
                "instructions": "Navigate to incometax.gov.in. Click 'Verify Your PAN' under 'Quick Links'. Enter PAN number, full name, and date of birth. Click 'Continue'. The page will show whether the PAN is active, the name on PAN, and whether it's linked to Aadhaar.",
                "difficulty": "easy",
            },
            {
                "name": "Check TDS Deduction",
                "description": "View TDS deducted by employers/payers",
                "instructions": "Navigate to incometax.gov.in. Login with PAN and password. Click 'e-File' > 'View Form 26AS'. This opens the TRACES portal. Select Assessment Year. View TDS Part A (salary TDS) and Part C (non-salary TDS). The form shows deductor name, TDS amount, and date of deposit.",
                "requires_auth": True,
                "difficulty": "easy",
            },
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
            {
                "name": "GST Registration",
                "description": "Register new business for GST with PAN/Aadhaar verification",
                "instructions": "Navigate to gst.gov.in. Click 'Services' > 'Registration' > 'New Registration'. Select 'Taxpayer' as the registration type. Enter PAN, mobile number, and email. Verify OTPs received. Fill Part B of the form: business name, trade name, constitution, principal place of business, additional places, HSN codes for goods/services, bank details. Upload documents: PAN, Aadhaar, business registration proof, address proof, bank statement. Submit the application. ARN will be generated for tracking.",
                "requires_auth": True,
                "difficulty": "hard",
            },
            {
                "name": "File GST Returns (GSTR-1, GSTR-3B)",
                "description": "Monthly/quarterly GST return filing",
                "instructions": "Navigate to gst.gov.in. Login with GSTIN and password. For GSTR-1: Click 'Services' > 'Returns' > 'Returns Dashboard'. Select the return period. Click 'Details of outward supplies of goods or services'. Add invoice details: recipient GSTIN, invoice number, invoice date, taxable value, tax rate, tax amount. Submit GSTR-1. For GSTR-3B: Click 'Monthly Return GSTR-3B'. Auto-populated summary appears. Verify details. Enter final tax liability and input tax credit. Pay tax via challan if needed. Submit GSTR-3B.",
                "requires_auth": True,
                "requires_payment": True,
                "difficulty": "hard",
            },
            {
                "name": "Pay GST Online",
                "description": "Make GST payment via challan",
                "instructions": "Navigate to gst.gov.in. Login with GSTIN. Click 'Services' > 'Payments' > 'Create Challan'. Enter the tax amount under CGST, SGST, IGST as applicable. Select the payment mode: E-Payment, NEFT/RTGS, or Over the Counter. For E-Payment, choose net banking or card. Complete the payment. Download the challan receipt.",
                "requires_auth": True,
                "requires_payment": True,
                "difficulty": "medium",
            },
            {
                "name": "Check GST Returns Status",
                "description": "Track filed returns and their processing",
                "instructions": "Navigate to gst.gov.in. Login with GSTIN. Click 'Services' > 'Returns' > 'Returns Dashboard'. Select the financial year and period. The status will show: Filed, Pending, or Not Filed for each return type (GSTR-1, GSTR-3B, GSTR-9). Click on the return to view details.",
                "requires_auth": True,
                "difficulty": "easy",
            },
            {
                "name": "Apply for GST Refund",
                "description": "Claim refund of excess GST paid",
                "instructions": "Navigate to gst.gov.in. Login with GSTIN. Click 'Services' > 'Refunds' > 'Application for Refund'. Select the refund type: excess balance, ITC accumulation, export refund, etc. Fill the application with supporting details. Upload invoices and supporting documents. Submit the application. Track status under 'Track Application Status'.",
                "requires_auth": True,
                "difficulty": "medium",
            },
            {
                "name": "View E-Way Bill",
                "description": "Generate and track e-way bills for goods movement",
                "instructions": "Navigate to ewaybillgst.gov.in. Login with GSTIN. Click 'Generate New' under 'e-Way Bill'. Enter supplier and recipient GSTIN, place of delivery, item details (description, HSN, quantity, value), and transporter details. Generate the e-way bill. The system will assign a unique EWB number. Track existing e-way bills under 'List of e-Way Bills'.",
                "requires_auth": True,
                "difficulty": "medium",
            },
            {
                "name": "Check GST Registration Status",
                "description": "Verify GSTIN and registration details",
                "instructions": "Navigate to gst.gov.in. Click 'Search Taxpayer' > 'Search by GSTIN'. Enter the 15-digit GSTIN. Click 'Search'. The results show: legal name, trade name, registration date, constitution, business activities, and registration status (Active/Suspended/Cancelled).",
                "difficulty": "easy",
            },
            {
                "name": "Amend GST Registration",
                "description": "Update business details in GST registration",
                "instructions": "Navigate to gst.gov.in. Login with GSTIN. Click 'Services' > 'Registration' > 'Amendment of Registration Non-Core Fields'. Select the field to change: trade name, address, email, mobile, bank account, etc. Upload supporting documents if required. Submit the amendment request. Core field changes require approval.",
                "requires_auth": True,
                "difficulty": "medium",
            },
            {
                "name": "Surrender GST Registration",
                "description": "Cancel GST registration for closed businesses",
                "instructions": "Navigate to gst.gov.in. Login with GSTIN. Click 'Services' > 'Registration' > 'Application for Cancellation'. Verify that all returns are filed and tax dues are paid. Enter the reason for cancellation. Confirm the application. The cancellation request will be processed after verification.",
                "requires_auth": True,
                "difficulty": "medium",
            },
            {
                "name": "Download GST Certificates",
                "description": "Get GST registration certificate",
                "instructions": "Navigate to gst.gov.in. Login with GSTIN. Click 'Services' > 'User Services' > 'View/Download Certificates'. Select 'GST Registration Certificate'. The certificate will be downloaded as PDF. It contains GSTIN, legal name, trade name, registration date, and business activity details.",
                "requires_auth": True,
                "difficulty": "easy",
            },
            {
                "name": "Input Tax Credit (ITC) Reconciliation",
                "description": "Match ITC claims with supplier returns",
                "instructions": "Navigate to gst.gov.in. Login with GSTIN. Click 'Services' > 'Returns' > 'Auto-Generated Details (GSTR-2A/2B)'. View the auto-populated ITC from supplier GSTR-1 filings. Compare with your GSTR-3B ITC claims. Identify mismatches. Reconcile by contacting suppliers for corrections or amending your returns.",
                "requires_auth": True,
                "difficulty": "hard",
            },
            {
                "name": "Check GST Demand/Order",
                "description": "View orders and demands from GST department",
                "instructions": "Navigate to gst.gov.in. Login with GSTIN. Click 'Services' > 'User Services' > 'View Orders and Notices'. View all orders: assessment orders, demand orders, refund orders. Click on any order to view details and download the PDF.",
                "requires_auth": True,
                "difficulty": "easy",
            },
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
            {
                "name": "UAN Activation",
                "description": "Activate Universal Account Number for EPF services",
                "instructions": "Navigate to epfindia.gov.in. Click 'UAN Member e-SEWA' or go to unifiedportal-mem.epfindia.gov.in. Click 'Activate UAN'. Enter UAN (from salary slip or employer), Aadhaar, name, date of birth, mobile number, and email. Click 'Get Authorization Pin'. Enter the OTP received on mobile. Click 'Validate OTP and Activate UAN'. Set a password for future logins.",
                "difficulty": "easy",
            },
            {
                "name": "Check EPF Balance",
                "description": "View EPF passbook and balance via UAN",
                "instructions": "Navigate to passbook.epfindia.gov.in. Login with UAN and password. Select the Member ID (PF account). The passbook shows employer contribution, employee contribution, pension contribution, and total balance. Download the passbook as PDF.",
                "requires_auth": True,
                "difficulty": "easy",
            },
            {
                "name": "Online EPF Withdrawal (Claim)",
                "description": "Withdraw EPF amount online (Form 19, 10C, 31)",
                "instructions": "Navigate to unifiedportal-mem.epfindia.gov.in. Login with UAN and password. Click 'Manage' > 'KYC' to verify Aadhaar, PAN, and bank details are linked. Click 'Online Services' > 'Claim (FORM-31, 19, 10C & 10D)'. Verify bank account number. Select the claim form: Form 19 (full withdrawal), Form 10C (pension), or Form 31 (advance). Enter amount and purpose. Submit the claim. Track under 'Track Claim Status'.",
                "requires_auth": True,
                "difficulty": "hard",
            },
            {
                "name": "Transfer EPF Account",
                "description": "Transfer EPF balance from old to new employer",
                "instructions": "Navigate to unifiedportal-mem.epfindia.gov.in. Login with UAN and password. Click 'Online Services' > 'One Member - One EPF Account (Transfer Request)'. Click 'Step 1: Get details of previous account'. Enter previous PF account number and employer. Verify details and submit the transfer request. The previous employer must approve it.",
                "requires_auth": True,
                "difficulty": "medium",
            },
            {
                "name": "Link Aadhaar with UAN",
                "description": "Seed Aadhaar for direct benefit transfer",
                "instructions": "Navigate to unifiedportal-mem.epfindia.gov.in. Login with UAN and password. Click 'Manage' > 'KYC'. Click 'Add KYC'. Select 'Aadhaar'. Enter the Aadhaar number. The system verifies with UIDAI. Once verified, Aadhaar is linked. This is mandatory for PF withdrawal.",
                "requires_auth": True,
                "difficulty": "easy",
            },
            {
                "name": "Update KYC in UAN",
                "description": "Update bank, PAN, Aadhaar details linked to UAN",
                "instructions": "Navigate to unifiedportal-mem.epfindia.gov.in. Login with UAN and password. Click 'Manage' > 'KYC'. Click 'Add KYC' to add new details: Aadhaar, PAN, bank account. Enter details and submit. KYC is verified by employer and then EPFO. Check status under 'Currently Active KYC'.",
                "requires_auth": True,
                "difficulty": "medium",
            },
            {
                "name": "Download EPF Passbook",
                "description": "Get monthly contribution statement",
                "instructions": "Navigate to passbook.epfindia.gov.in. Login with UAN and password. Select the Member ID. Click 'Download Passbook'. The passbook shows monthly breakdown of employee contribution (12% of basic), employer contribution (3.67% PF + 8.33% pension), and total balance. Download as PDF.",
                "requires_auth": True,
                "difficulty": "easy",
            },
            {
                "name": "Check Claim Status",
                "description": "Track EPF withdrawal/transfer claim status",
                "instructions": "Navigate to unifiedportal-mem.epfindia.gov.in. Login with UAN and password. Click 'Online Services' > 'Track Claim Status'. View all claims. The status shows: Pending at Employer, Pending at EPFO, Settled, or Rejected. If settled, note the payment date.",
                "requires_auth": True,
                "difficulty": "easy",
            },
            {
                "name": "Generate UAN",
                "description": "Get new UAN if not provided by employer",
                "instructions": "Navigate to epfindia.gov.in. Click 'UAN Allotment for Employees'. Enter Aadhaar number, name, DOB, gender, and mobile number. Verify OTP. The system checks if a UAN already exists. If not, a new UAN is generated and sent to the registered mobile. Note: Usually UAN is provided by the employer.",
                "difficulty": "easy",
            },
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
            {
                "name": "Open NPS Account",
                "description": "Register for National Pension System online",
                "instructions": "Navigate to nps.nsdl.com. Click 'Open NPS Account'. Select subscriber type: Individual. Enter Aadhaar number and verify with OTP. Fill personal details: name, DOB, gender, address, mobile, email. Enter bank details: account number, IFSC. Choose pension fund manager. Select investment choice: Active (choose allocation) or Auto (lifecycle-based). Nominate beneficiaries. Pay initial contribution (minimum Rs 500). The PRAN will be generated.",
                "requires_auth": True,
                "requires_payment": True,
                "difficulty": "hard",
            },
            {
                "name": "Contribute to NPS",
                "description": "Add voluntary or regular contributions",
                "instructions": "Navigate to nps.nsdl.com. Login with PRAN and password. Click 'Contribution'. Select account type: Tier I or Tier II. Enter the contribution amount. Choose payment mode: net banking, UPI, or debit card. Complete the payment. Download the contribution receipt.",
                "requires_auth": True,
                "requires_payment": True,
                "difficulty": "medium",
            },
            {
                "name": "Check NPS Balance",
                "description": "View pension wealth and holdings",
                "instructions": "Navigate to nps.nsdl.com. Login with PRAN and password. Click 'Account Statement' or 'View Holdings'. The page shows total pension wealth, unit balance across fund managers, asset allocation (equity, corporate bonds, government securities), and recent transactions.",
                "requires_auth": True,
                "difficulty": "easy",
            },
            {
                "name": "Request NPS Withdrawal",
                "description": "Partial or full withdrawal from NPS corpus",
                "instructions": "Navigate to nps.nsdl.com. Login with PRAN and password. Click 'Withdrawal' under 'Transaction'. Select withdrawal type: partial (after 3 years), premature (before 60), or normal (at 60). For normal withdrawal: minimum 40% must be used for annuity, maximum 60% as lump sum. Enter the amount. Upload bank proof. Submit the request.",
                "requires_auth": True,
                "difficulty": "hard",
            },
            {
                "name": "Change NPS Fund Manager",
                "description": "Switch between Pension Fund Managers",
                "instructions": "Navigate to nps.nsdl.com. Login with PRAN and password. Click 'Fund Manager' under 'Settings'. View current fund manager and holdings. Select a new fund manager from available options. The switch takes effect from the next contribution.",
                "requires_auth": True,
                "difficulty": "easy",
            },
            {
                "name": "Update Nominee Details",
                "description": "Add or modify NPS nominee information",
                "instructions": "Navigate to nps.nsdl.com. Login with PRAN and password. Click 'Nominee Details' under 'Update Details'. Add nominee: name, relationship, DOB, percentage share. You can add up to 3 nominees. Verify and submit.",
                "requires_auth": True,
                "difficulty": "easy",
            },
            {
                "name": "Print NPS Statement",
                "description": "Download transaction history and balance statement",
                "instructions": "Navigate to nps.nsdl.com. Login with PRAN and password. Click 'Account Statement'. Select the statement period: monthly, quarterly, or annual. Click 'Download'. The statement shows all transactions, contributions, withdrawals, and current balance. Download as PDF.",
                "requires_auth": True,
                "difficulty": "easy",
            },
            {
                "name": "Tier II Account Operations",
                "description": "Manage voluntary savings account under NPS",
                "instructions": "Navigate to nps.nsdl.com. Login with PRAN and password. Click 'Tier II' under 'Account'. Tier II is voluntary with no lock-in. Click 'Contribute' to add funds or 'Withdraw' to redeem. View the Tier II account statement and holdings.",
                "requires_auth": True,
                "difficulty": "easy",
            },
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
            {"name": "Register for Scholarship", "description": "Create student account and apply for eligible scholarships",
                "instructions": "Navigate to the portal and perform: Create student account and apply for eligible scholarships. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check Scholarship Status", "description": "Track application processing and disbursement status",
                "instructions": "Navigate to the portal and perform: Track application processing and disbursement status. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Renew Scholarship", "description": "Renew existing scholarship for next academic year",
                "instructions": "Navigate to the portal and perform: Renew existing scholarship for next academic year. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Download Scholarship Certificate", "description": "Get award certificate after disbursement",
                "instructions": "Navigate to the portal and perform: Get award certificate after disbursement. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check Disbursement Status", "description": "Verify if scholarship amount has been credited",
                "instructions": "Navigate to the portal and perform: Verify if scholarship amount has been credited. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Update Bank Details", "description": "Change bank account for scholarship credit",
                "instructions": "Navigate to the portal and perform: Change bank account for scholarship credit. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "View School Profiles", "description": "Access detailed school information and infrastructure data",
                "instructions": "Navigate to the portal and perform: Access detailed school information and infrastructure data. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check Enrollment Statistics", "description": "View student enrollment data by district/state",
                "instructions": "Navigate to the portal and perform: View student enrollment data by district/state. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Report Card Generation", "description": "Download school performance report",
                "instructions": "Navigate to the portal and perform: Download school performance report. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Update School Data", "description": "School administrators update institutional information",
                "instructions": "Navigate to the portal and perform: School administrators update institutional information. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "Access Digital Documents", "description": "View Aadhaar, PAN, driving license, marksheets, etc. digitally",
                "instructions": "Navigate to the portal and perform: View Aadhaar, PAN, driving license, marksheets, etc. digitally. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Upload Documents", "description": "Store personal documents in cloud locker",
                "instructions": "Navigate to the portal and perform: Store personal documents in cloud locker. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Share Verified Documents", "description": "Share government-verified documents with organizations",
                "instructions": "Navigate to the portal and perform: Share government-verified documents with organizations. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Verify Document Authenticity", "description": "Verify if a document is genuine via DigiLocker",
                "instructions": "Navigate to the portal and perform: Verify if a document is genuine via DigiLocker. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Download Documents", "description": "Get PDF copies of issued documents",
                "instructions": "Navigate to the portal and perform: Get PDF copies of issued documents. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Link Aadhaar to DigiLocker", "description": "Connect Aadhaar for accessing government-issued documents",
                "instructions": "Navigate to the portal and perform: Connect Aadhaar for accessing government-issued documents. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "Register as Farmer", "description": "Register for PM-KISAN direct benefit transfer",
                "instructions": "Navigate to the portal and perform: Register for PM-KISAN direct benefit transfer. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check PM-KISAN Status", "description": "Track installment status and beneficiary details",
                "instructions": "Navigate to the portal and perform: Track installment status and beneficiary details. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Update Bank Account", "description": "Change bank account for direct credit",
                "instructions": "Navigate to the portal and perform: Change bank account for direct credit. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Update Aadhaar Details", "description": "Correct Aadhaar linkage for PM-KISAN",
                "instructions": "Navigate to the portal and perform: Correct Aadhaar linkage for PM-KISAN. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check Beneficiary List", "description": "View village/block/state-wise beneficiary list",
                "instructions": "Navigate to the portal and perform: View village/block/state-wise beneficiary list. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Self-Registration", "description": "New farmer self-registration via Aadhaar eKYC",
                "instructions": "Navigate to the portal and perform: New farmer self-registration via Aadhaar eKYC. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "eKYC for PM-KISAN", "description": "Complete Aadhaar-based OTP eKYC for continued benefits",
                "instructions": "Navigate to the portal and perform: Complete Aadhaar-based OTP eKYC for continued benefits. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "Register for Crop Insurance", "description": "Enroll in PMFBY for Kharif/Rabi season",
                "instructions": "Navigate to the portal and perform: Enroll in PMFBY for Kharif/Rabi season. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check Insurance Status", "description": "Track crop insurance application and coverage",
                "instructions": "Navigate to the portal and perform: Track crop insurance application and coverage. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "File Crop Loss Claim", "description": "Report crop damage and file insurance claim",
                "instructions": "Navigate to the portal and perform: Report crop damage and file insurance claim. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check Claim Settlement Status", "description": "Track insurance claim processing and payout",
                "instructions": "Navigate to the portal and perform: Track insurance claim processing and payout. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "View Policy Details", "description": "Download policy document and coverage details",
                "instructions": "Navigate to the portal and perform: Download policy document and coverage details. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check Premium Subsidy", "description": "View government subsidy on insurance premium",
                "instructions": "Navigate to the portal and perform: View government subsidy on insurance premium. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "Download Soil Health Card", "description": "Get soil analysis report and fertilizer recommendations",
                "instructions": "Navigate to the portal and perform: Get soil analysis report and fertilizer recommendations. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check Soil Test Status", "description": "Track soil sample testing progress",
                "instructions": "Navigate to the portal and perform: Track soil sample testing progress. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "View Soil Health Dashboard", "description": "Access district/state-wise soil health data",
                "instructions": "Navigate to the portal and perform: Access district/state-wise soil health data. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "Create ABHA Number", "description": "Generate 14-digit health ID using Aadhaar or DL",
                "instructions": "Navigate to the portal and perform: Generate 14-digit health ID using Aadhaar or DL. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Link Health Records", "description": "Connect prescriptions, lab reports, and records to ABHA",
                "instructions": "Navigate to the portal and perform: Connect prescriptions, lab reports, and records to ABHA. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "View Health Records", "description": "Access digital health history from linked facilities",
                "instructions": "Navigate to the portal and perform: Access digital health history from linked facilities. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Share Health Records", "description": "Share verified health data with doctors/hospitals",
                "instructions": "Navigate to the portal and perform: Share verified health data with doctors/hospitals. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Download ABHA Card", "description": "Get digital ABHA health ID card",
                "instructions": "Navigate to the portal and perform: Get digital ABHA health ID card. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "Check PM-JAY Eligibility", "description": "Verify if family is eligible for Ayushman Bharat coverage",
                "instructions": "Navigate to the portal and perform: Verify if family is eligible for Ayushman Bharat coverage. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Download Ayushman Card", "description": "Get digital Ayushman Bharat health insurance card",
                "instructions": "Navigate to the portal and perform: Get digital Ayushman Bharat health insurance card. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Find Empanelled Hospital", "description": "Search hospitals covered under PM-JAY in your area",
                "instructions": "Navigate to the portal and perform: Search hospitals covered under PM-JAY in your area. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check Claim Status", "description": "Track insurance claim processing at empanelled hospitals",
                "instructions": "Navigate to the portal and perform: Track insurance claim processing at empanelled hospitals. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Search Beneficiary by Aadhaar", "description": "Find PM-JAY beneficiary details via Aadhaar number",
                "instructions": "Navigate to the portal and perform: Find PM-JAY beneficiary details via Aadhaar number. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "View Disease Surveillance Data", "description": "Access outbreak and disease reporting data",
                "instructions": "Navigate to the portal and perform: Access outbreak and disease reporting data. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check Vaccination Schedule", "description": "View national immunization schedule",
                "instructions": "Navigate to the portal and perform: View national immunization schedule. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Report Disease Outbreak", "description": "Healthcare workers report disease incidents",
                "instructions": "Navigate to the portal and perform: Healthcare workers report disease incidents. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "Register as Job Seeker", "description": "Create profile and upload resume for government/private jobs",
                "instructions": "Navigate to the portal and perform: Create profile and upload resume for government/private jobs. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Search Jobs", "description": "Browse job listings by skill, location, and qualification",
                "instructions": "Navigate to the portal and perform: Browse job listings by skill, location, and qualification. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Apply for Jobs", "description": "Submit applications directly through NCS platform",
                "instructions": "Navigate to the portal and perform: Submit applications directly through NCS platform. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Register as Employer", "description": "Companies register to post job openings",
                "instructions": "Navigate to the portal and perform: Companies register to post job openings. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Post Job Opening", "description": "Employers publish job vacancies",
                "instructions": "Navigate to the portal and perform: Employers publish job vacancies. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Book Career Counselor", "description": "Schedule session with government career counselor",
                "instructions": "Navigate to the portal and perform: Schedule session with government career counselor. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Register for Skill Training", "description": "Enroll in skill development programs listed on NCS",
                "instructions": "Navigate to the portal and perform: Enroll in skill development programs listed on NCS. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "Register as Unorganized Worker", "description": "Get e-Shram card using Aadhaar and bank details",
                "instructions": "Navigate to the portal and perform: Get e-Shram card using Aadhaar and bank details. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Download e-Shram Card", "description": "Get digital UAN card for unorganized sector workers",
                "instructions": "Navigate to the portal and perform: Get digital UAN card for unorganized sector workers. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Update Profile", "description": "Modify personal, skill, or occupation details",
                "instructions": "Navigate to the portal and perform: Modify personal, skill, or occupation details. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check Social Security Benefits", "description": "View eligible welfare schemes linked to e-Shram",
                "instructions": "Navigate to the portal and perform: View eligible welfare schemes linked to e-Shram. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check Accident Insurance Status", "description": "Verify Pradhan Mantri Suraksha Bima Yojana enrollment",
                "instructions": "Navigate to the portal and perform: Verify Pradhan Mantri Suraksha Bima Yojana enrollment. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "Register as MSME", "description": "Get Udyam registration certificate via Aadhaar-based process",
                "instructions": "Navigate to the portal and perform: Get Udyam registration certificate via Aadhaar-based process. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check Udyam Status", "description": "Track MSME registration application status",
                "instructions": "Navigate to the portal and perform: Track MSME registration application status. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Update Udyam Details", "description": "Modify enterprise information post-registration",
                "instructions": "Navigate to the portal and perform: Modify enterprise information post-registration. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Print Udyam Certificate", "description": "Download MSME registration certificate",
                "instructions": "Navigate to the portal and perform: Download MSME registration certificate. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Verify Udyam Number", "description": "Check validity of existing Udyam registration",
                "instructions": "Navigate to the portal and perform: Check validity of existing Udyam registration. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "Incorporate Company", "description": "Register new company (Private/Public/LLP/OPC) via MCA21",
                "instructions": "Navigate to the portal and perform: Register new company (Private/Public/LLP/OPC) via MCA21. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "File Annual Returns", "description": "Submit annual return and financial statements",
                "instructions": "Navigate to the portal and perform: Submit annual return and financial statements. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check Company Name Availability", "description": "Verify if proposed company name is available",
                "instructions": "Navigate to the portal and perform: Verify if proposed company name is available. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "View Company Details", "description": "Access company registration info, directors, charges",
                "instructions": "Navigate to the portal and perform: Access company registration info, directors, charges. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "File Director Change", "description": "Appoint or resign company directors",
                "instructions": "Navigate to the portal and perform: Appoint or resign company directors. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check DIN Status", "description": "Verify Director Identification Number",
                "instructions": "Navigate to the portal and perform: Verify Director Identification Number. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Download Certificates", "description": "Get incorporation and other MCA certificates",
                "instructions": "Navigate to the portal and perform: Get incorporation and other MCA certificates. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "File Charge Documents", "description": "Register or modify company charges/mortgages",
                "instructions": "Navigate to the portal and perform: Register or modify company charges/mortgages. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "Get Startup Recognition", "description": "Register DPIIT-recognized startup for tax benefits",
                "instructions": "Navigate to the portal and perform: Register DPIIT-recognized startup for tax benefits. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Apply for Tax Exemption", "description": "Claim Section 80IAC tax holiday for eligible startups",
                "instructions": "Navigate to the portal and perform: Claim Section 80IAC tax holiday for eligible startups. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Register for Fund of Funds", "description": "Apply for government-backed startup funding",
                "instructions": "Navigate to the portal and perform: Apply for government-backed startup funding. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "View Startup Benefits", "description": "Check self-certification, IPR, and other benefits",
                "instructions": "Navigate to the portal and perform: Check self-certification, IPR, and other benefits. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Connect with Incubators", "description": "Find government-approved incubators and accelerators",
                "instructions": "Navigate to the portal and perform: Find government-approved incubators and accelerators. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "Search Government Services", "description": "Find services by ministry, state, or category",
                "instructions": "Navigate to the portal and perform: Find services by ministry, state, or category. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Access Government Directory", "description": "Find contact details of government officials and departments",
                "instructions": "Navigate to the portal and perform: Find contact details of government officials and departments. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "View Government Schemes", "description": "Browse all central and state government schemes",
                "instructions": "Navigate to the portal and perform: Browse all central and state government schemes. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "File RTI Application", "description": "Initiate Right to Information application",
                "instructions": "Navigate to the portal and perform: Initiate Right to Information application. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "Explore Digital Services", "description": "Browse all digital government services",
                "instructions": "Navigate to the portal and perform: Browse all digital government services. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check Digital Literacy Programs", "description": "Find digital skill development initiatives",
                "instructions": "Navigate to the portal and perform: Find digital skill development initiatives. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Access MyGov Portal", "description": "Participate in government campaigns and discussions",
                "instructions": "Navigate to the portal and perform: Participate in government campaigns and discussions. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "Access EPF Services", "description": "Check EPF balance, download passbook via UMANG",
                "instructions": "Navigate to the portal and perform: Check EPF balance, download passbook via UMANG. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Access Pension Services", "description": "View NPS/CGHS pension details",
                "instructions": "Navigate to the portal and perform: View NPS/CGHS pension details. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Pay Gas/Electricity Bills", "description": "Pay utility bills through integrated services",
                "instructions": "Navigate to the portal and perform: Pay utility bills through integrated services. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check Soil Health Card", "description": "Access soil health data via UMANG",
                "instructions": "Navigate to the portal and perform: Access soil health data via UMANG. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Access Ayushman Bharat", "description": "View Ayushman card and find empanelled hospitals",
                "instructions": "Navigate to the portal and perform: View Ayushman card and find empanelled hospitals. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Apply for Government Schemes", "description": "Search and apply for eligible schemes",
                "instructions": "Navigate to the portal and perform: Search and apply for eligible schemes. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "Search Government Schemes", "description": "Find schemes by category, eligibility, or keyword",
                "instructions": "Navigate to the portal and perform: Find schemes by category, eligibility, or keyword. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check Eligibility", "description": "Answer questions to find schemes you qualify for",
                "instructions": "Navigate to the portal and perform: Answer questions to find schemes you qualify for. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "View Scheme Details", "description": "Read benefits, documents required, and how to apply",
                "instructions": "Navigate to the portal and perform: Read benefits, documents required, and how to apply. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Apply for Scheme", "description": "Navigate to the official portal to apply",
                "instructions": "Navigate to the portal and perform: Navigate to the official portal to apply. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "Track Speed Post / Registered Mail", "description": "Track consignment by tracking number",
                "instructions": "Navigate to the portal and perform: Track consignment by tracking number. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Open Post Office Savings Account", "description": "Open POSB account online",
                "instructions": "Navigate to the portal and perform: Open POSB account online. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check Post Office Interest Rates", "description": "View current RD, TD, NSC, KVP rates",
                "instructions": "Navigate to the portal and perform: View current RD, TD, NSC, KVP rates. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Calculate postage", "description": "Estimate mailing cost by weight and destination",
                "instructions": "Navigate to the portal and perform: Estimate mailing cost by weight and destination. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Find Post Office", "description": "Locate nearest post office by pincode or address",
                "instructions": "Navigate to the portal and perform: Locate nearest post office by pincode or address. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Apply for Passport (via Post Office)", "description": "Use post office as Passport Seva Kendra",
                "instructions": "Navigate to the portal and perform: Use post office as Passport Seva Kendra. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "File Grievance", "description": "Submit complaint against government department/service",
                "instructions": "Navigate to the portal and perform: Submit complaint against government department/service. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Track Grievance Status", "description": "Monitor grievance registration, transfer, and resolution",
                "instructions": "Navigate to the portal and perform: Monitor grievance registration, transfer, and resolution. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "View Grievance History", "description": "Access all previously filed grievances",
                "instructions": "Navigate to the portal and perform: Access all previously filed grievances. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "File Appeal", "description": "Appeal against unresolved grievance at higher level",
                "instructions": "Navigate to the portal and perform: Appeal against unresolved grievance at higher level. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Close Grievance", "description": "Mark grievance as resolved after satisfactory action",
                "instructions": "Navigate to the portal and perform: Mark grievance as resolved after satisfactory action. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "File RTI Application", "description": "Submit RTI request to central public authority with ₹10 fee",
                "instructions": "Navigate to the portal and perform: Submit RTI request to central public authority with ₹10 fee. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "File First Appeal", "description": "Appeal against unsatisfactory RTI response",
                "instructions": "Navigate to the portal and perform: Appeal against unsatisfactory RTI response. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Track RTI Status", "description": "Check application status and response date",
                "instructions": "Navigate to the portal and perform: Check application status and response date. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Pay RTI Fee Online", "description": "Pay ₹10 application fee via net banking/UPI",
                "instructions": "Navigate to the portal and perform: Pay ₹10 application fee via net banking/UPI. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "View RTI Response", "description": "Download information provided by public authority",
                "instructions": "Navigate to the portal and perform: Download information provided by public authority. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "Check Case Status", "description": "Search by case number, party name, or advocate name",
                "instructions": "Navigate to the portal and perform: Search by case number, party name, or advocate name. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "View Cause List", "description": "See daily court hearing schedule",
                "instructions": "Navigate to the portal and perform: See daily court hearing schedule. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Download Court Orders", "description": "Get PDF copies of judgments and orders",
                "instructions": "Navigate to the portal and perform: Get PDF copies of judgments and orders. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "View Case History", "description": "See complete hearing and order history",
                "instructions": "Navigate to the portal and perform: See complete hearing and order history. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check Court Fee Payment", "description": "Pay court fees online for filing cases",
                "instructions": "Navigate to the portal and perform: Pay court fees online for filing cases. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Find Court Complex", "description": "Locate district court complexes with contact details",
                "instructions": "Navigate to the portal and perform: Locate district court complexes with contact details. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "File Second Appeal", "description": "Appeal to CIC when first appeal is unsatisfactory",
                "instructions": "Navigate to the portal and perform: Appeal to CIC when first appeal is unsatisfactory. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "File Complaint to CIC", "description": "Complain about non-compliance with RTI Act",
                "instructions": "Navigate to the portal and perform: Complain about non-compliance with RTI Act. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Track Case Status", "description": "Check status of second appeal/complaint",
                "instructions": "Navigate to the portal and perform: Check status of second appeal/complaint. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "View CIC Orders", "description": "Download CIC decisions and orders",
                "instructions": "Navigate to the portal and perform: Download CIC decisions and orders. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "Participate in Discussions", "description": "Give suggestions on government policy topics",
                "instructions": "Navigate to the portal and perform: Give suggestions on government policy topics. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Join Competitions", "description": "Participate in quizzes, poster design, essay contests",
                "instructions": "Navigate to the portal and perform: Participate in quizzes, poster design, essay contests. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Submit Ideas", "description": "Propose ideas for government initiatives",
                "instructions": "Navigate to the portal and perform: Propose ideas for government initiatives. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Volunteer for Causes", "description": "Register for Swachh Bharat, tree plantation, etc.",
                "instructions": "Navigate to the portal and perform: Register for Swachh Bharat, tree plantation, etc.. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "Apply for PMAY(U) Benefits", "description": "Register for affordable housing subsidy under CLSS",
                "instructions": "Navigate to the portal and perform: Register for affordable housing subsidy under CLSS. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check Application Status", "description": "Track PMAY housing application",
                "instructions": "Navigate to the portal and perform: Track PMAY housing application. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Verify Beneficiary Status", "description": "Check if approved as PMAY beneficiary",
                "instructions": "Navigate to the portal and perform: Check if approved as PMAY beneficiary. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "View Subsidy Details", "description": "Check credit-linked subsidy amount",
                "instructions": "Navigate to the portal and perform: Check credit-linked subsidy amount. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "Check Eligibility", "description": "Verify family eligibility via SECC database",
                "instructions": "Navigate to the portal and perform: Verify family eligibility via SECC database. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Download Ayushman Card", "description": "Get digital Ayushman Bharat card",
                "instructions": "Navigate to the portal and perform: Get digital Ayushman Bharat card. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Find Hospital", "description": "Search empanelled hospitals by location",
                "instructions": "Navigate to the portal and perform: Search empanelled hospitals by location. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Track Treatment Claim", "description": "Check hospitalization claim status",
                "instructions": "Navigate to the portal and perform: Check hospitalization claim status. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "Register for Job Card", "description": "Apply for MGNREGA job card as rural worker",
                "instructions": "Navigate to the portal and perform: Apply for MGNREGA job card as rural worker. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Request Employment", "description": "Demand guaranteed 100 days of work under MGNREGA",
                "instructions": "Navigate to the portal and perform: Demand guaranteed 100 days of work under MGNREGA. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check Job Card Status", "description": "View job card details and work history",
                "instructions": "Navigate to the portal and perform: View job card details and work history. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "View Muster Roll", "description": "Check attendance and wage payment records",
                "instructions": "Navigate to the portal and perform: Check attendance and wage payment records. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Track Wage Payment", "description": "Verify if wages have been credited to bank account",
                "instructions": "Navigate to the portal and perform: Verify if wages have been credited to bank account. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "File Grievance", "description": "Complain about delayed wages or denied work",
                "instructions": "Navigate to the portal and perform: Complain about delayed wages or denied work. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "View Social Audit", "description": "Access gram sabha social audit reports",
                "instructions": "Navigate to the portal and perform: Access gram sabha social audit reports. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "Apply for Ujjwala Connection", "description": "Register for free LPG connection under PMUY",
                "instructions": "Navigate to the portal and perform: Register for free LPG connection under PMUY. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check Ujjwala Status", "description": "Track LPG connection application status",
                "instructions": "Navigate to the portal and perform: Track LPG connection application status. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Link Aadhaar with LPG", "description": "Seed Aadhaar for subsidy transfer",
                "instructions": "Navigate to the portal and perform: Seed Aadhaar for subsidy transfer. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check Subsidy Credit", "description": "View DBT subsidy credited to bank account",
                "instructions": "Navigate to the portal and perform: View DBT subsidy credited to bank account. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "Register Property Document", "description": "Online property sale deed/gift deed registration",
                "instructions": "Navigate to the portal and perform: Online property sale deed/gift deed registration. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Pay Stamp Duty", "description": "Calculate and pay stamp duty and registration fees online",
                "instructions": "Navigate to the portal and perform: Calculate and pay stamp duty and registration fees online. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check Registration Status", "description": "Track document registration application",
                "instructions": "Navigate to the portal and perform: Track document registration application. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "View Registration Details", "description": "Access registered document details by registration number",
                "instructions": "Navigate to the portal and perform: Access registered document details by registration number. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Book Appointment at Sub-Registrar", "description": "Schedule visit for document execution",
                "instructions": "Navigate to the portal and perform: Schedule visit for document execution. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "View Land Records (Khasra/Khata)", "description": "Access digitized land records by survey number",
                "instructions": "Navigate to the portal and perform: Access digitized land records by survey number. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check Mutation Status", "description": "Track land ownership transfer status",
                "instructions": "Navigate to the portal and perform: Track land ownership transfer status. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "View Cadastral Maps", "description": "Access digitized land maps and boundaries",
                "instructions": "Navigate to the portal and perform: Access digitized land maps and boundaries. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Download Land Extract", "description": "Get official land record extract",
                "instructions": "Navigate to the portal and perform: Get official land record extract. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Verify Land Title", "description": "Check ownership and encumbrance status",
                "instructions": "Navigate to the portal and perform: Check ownership and encumbrance status. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "Apply for Visa Extension", "description": "Foreign nationals extend Indian visa online",
                "instructions": "Navigate to the portal and perform: Foreign nationals extend Indian visa online. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "FRRO Registration", "description": "Mandatory registration for foreign nationals staying 180+ days",
                "instructions": "Navigate to the portal and perform: Mandatory registration for foreign nationals staying 180+ days. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Apply for Exit Permit", "description": "Get exit permit for visa overstayers or lost passport cases",
                "instructions": "Navigate to the portal and perform: Get exit permit for visa overstayers or lost passport cases. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check FRRO Appointment", "description": "Book appointment at FRRO/FRO office",
                "instructions": "Navigate to the portal and perform: Book appointment at FRRO/FRO office. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "Apply for Caste Certificate", "description": "Apply for SC/ST/OBC caste certificate online",
                "instructions": "Navigate to the portal and perform: Apply for SC/ST/OBC caste certificate online. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Apply for Income Certificate", "description": "Get income certificate for scholarship/government scheme eligibility",
                "instructions": "Navigate to the portal and perform: Get income certificate for scholarship/government scheme eligibility. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Apply for Residence Certificate", "description": "Proof of residence certificate online",
                "instructions": "Navigate to the portal and perform: Proof of residence certificate online. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check Certificate Status", "description": "Track application status for various certificates",
                "instructions": "Navigate to the portal and perform: Track application status for various certificates. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Pay Government Fees", "description": "Pay fees for various government services",
                "instructions": "Navigate to the portal and perform: Pay fees for various government services. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "File Grievance", "description": "Submit grievance to AP government",
                "instructions": "Navigate to the portal and perform: Submit grievance to AP government. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "Apply for Certificates", "description": "Birth, death, caste, income, and other certificates",
                "instructions": "Navigate to the portal and perform: Birth, death, caste, income, and other certificates. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Pay Utility Bills", "description": "Electricity and water bill payments",
                "instructions": "Navigate to the portal and perform: Electricity and water bill payments. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Apply for Licenses", "description": "Trade license, driving license applications",
                "instructions": "Navigate to the portal and perform: Trade license, driving license applications. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "Apply for Caste Certificate", "description": "Online caste certificate application for SC/ST/OBC",
                "instructions": "Navigate to the portal and perform: Online caste certificate application for SC/ST/OBC. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Land Records (Bhumijankari)", "description": "Check land records, khasra, khatauni online",
                "instructions": "Navigate to the portal and perform: Check land records, khasra, khatauni online. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Apply for Income Certificate", "description": "Get income certificate from Revenue Department",
                "instructions": "Navigate to the portal and perform: Get income certificate from Revenue Department. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check Application Status", "description": "Track certificate application progress",
                "instructions": "Navigate to the portal and perform: Track certificate application progress. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "Apply for Caste Certificate", "description": "SC/ST/OBC certificate application",
                "instructions": "Navigate to the portal and perform: SC/ST/OBC certificate application. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Apply for Income Certificate", "description": "Get income certificate online",
                "instructions": "Navigate to the portal and perform: Get income certificate online. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Apply for Residence Certificate", "description": "Domicile/residence proof certificate",
                "instructions": "Navigate to the portal and perform: Domicile/residence proof certificate. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Apply for Character Certificate", "description": "Police clearance character certificate",
                "instructions": "Navigate to the portal and perform: Police clearance character certificate. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Apply for Non-Creamy Layer Certificate", "description": "OBC non-creamy layer certificate",
                "instructions": "Navigate to the portal and perform: OBC non-creamy layer certificate. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check Application Status", "description": "Track all RTPS application statuses",
                "instructions": "Navigate to the portal and perform: Track all RTPS application statuses. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Download Certificates", "description": "Download issued certificates",
                "instructions": "Navigate to the portal and perform: Download issued certificates. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "Apply for Trade License", "description": "New/renewal of trade license from MCD",
                "instructions": "Navigate to the portal and perform: New/renewal of trade license from MCD. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Property Tax Payment", "description": "Pay property tax to MCD/NDMC online",
                "instructions": "Navigate to the portal and perform: Pay property tax to MCD/NDMC online. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Apply for Birth/Death Certificate", "description": "Register and get birth/death certificates",
                "instructions": "Navigate to the portal and perform: Register and get birth/death certificates. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Water Tax Payment", "description": "Pay Delhi Jal Board water bill",
                "instructions": "Navigate to the portal and perform: Pay Delhi Jal Board water bill. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Apply for Subsidy", "description": "Apply for various Delhi government welfare schemes",
                "instructions": "Navigate to the portal and perform: Apply for various Delhi government welfare schemes. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check Vehicle Registration", "description": "Delhi transport services",
                "instructions": "Navigate to the portal and perform: Delhi transport services. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "File Grievance", "description": "Register complaint with Delhi government",
                "instructions": "Navigate to the portal and perform: Register complaint with Delhi government. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "Digital Seva Setu", "description": "Access 100+ services online — certificates, permissions, payments",
                "instructions": "Navigate to the portal and perform: Access 100+ services online — certificates, permissions, payments. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Land Records (AnyROR)", "description": "Check property ownership and 7/12 extracts online",
                "instructions": "Navigate to the portal and perform: Check property ownership and 7/12 extracts online. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Apply for Certificates", "description": "Income, caste, birth, death, and other certificates",
                "instructions": "Navigate to the portal and perform: Income, caste, birth, death, and other certificates. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Pay Property Tax", "description": "Municipal corporation property tax payment",
                "instructions": "Navigate to the portal and perform: Municipal corporation property tax payment. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "Apply for Income Certificate", "description": "Get income certificate from collectorate",
                "instructions": "Navigate to the portal and perform: Get income certificate from collectorate. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Apply for Caste Certificate", "description": "Caste certificate for reservation benefits",
                "instructions": "Navigate to the portal and perform: Caste certificate for reservation benefits. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Property Tax Payment", "description": "Municipal property tax payment online",
                "instructions": "Navigate to the portal and perform: Municipal property tax payment online. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check Application Status", "description": "Track certificate and application status",
                "instructions": "Navigate to the portal and perform: Track certificate and application status. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "Apply for Certificates", "description": "Income, caste, residence, birth, death certificates",
                "instructions": "Navigate to the portal and perform: Income, caste, residence, birth, death certificates. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Antyodaya Sewa Portal", "description": "Apply for welfare schemes for BPL families",
                "instructions": "Navigate to the portal and perform: Apply for welfare schemes for BPL families. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check Land Records", "description": "Access Jamabandi and land ownership records",
                "instructions": "Navigate to the portal and perform: Access Jamabandi and land ownership records. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Property Registration", "description": "Online property registration and stamp duty payment",
                "instructions": "Navigate to the portal and perform: Online property registration and stamp duty payment. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "Apply for Certificates", "description": "Income, caste, domicile certificates online",
                "instructions": "Navigate to the portal and perform: Income, caste, domicile certificates online. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Land Records", "description": "Access land records and property details",
                "instructions": "Navigate to the portal and perform: Access land records and property details. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "File Grievance", "description": "Register complaint with Jharkhand government",
                "instructions": "Navigate to the portal and perform: Register complaint with Jharkhand government. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Pay Utility Bills", "description": "Electricity and water bill payment",
                "instructions": "Navigate to the portal and perform: Electricity and water bill payment. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "Seva Sindhu Services", "description": "Access 1000+ government services online",
                "instructions": "Navigate to the portal and perform: Access 1000+ government services online. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Land Records (Bhoomi)", "description": "View RTC (Record of Rights), mutation, and land details",
                "instructions": "Navigate to the portal and perform: View RTC (Record of Rights), mutation, and land details. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Apply for Certificates", "description": "Income, caste, birth, death, and other certificates",
                "instructions": "Navigate to the portal and perform: Income, caste, birth, death, and other certificates. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check Application Status", "description": "Track Seva Sindhu application progress",
                "instructions": "Navigate to the portal and perform: Track Seva Sindhu application progress. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Pay Property Tax", "description": "BBMP/ULB property tax payment",
                "instructions": "Navigate to the portal and perform: BBMP/ULB property tax payment. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "e-District Services", "description": "Apply for income, caste, birth, death, and other certificates",
                "instructions": "Navigate to the portal and perform: Apply for income, caste, birth, death, and other certificates. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Land Tax Payment", "description": "Pay land revenue tax online",
                "instructions": "Navigate to the portal and perform: Pay land revenue tax online. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check Certificate Status", "description": "Track application and issuance status",
                "instructions": "Navigate to the portal and perform: Track application and issuance status. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Kerala PSC Portal", "description": "Apply for government jobs via Kerala Public Service Commission",
                "instructions": "Navigate to the portal and perform: Apply for government jobs via Kerala Public Service Commission. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "View Budget Documents", "description": "Access state budget documents and allocations",
                "instructions": "Navigate to the portal and perform: Access state budget documents and allocations. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "MP e-District Services", "description": "Apply for certificates and government services online",
                "instructions": "Navigate to the portal and perform: Apply for certificates and government services online. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Land Records (MP Bhulekh)", "description": "Access digitized land records and maps",
                "instructions": "Navigate to the portal and perform: Access digitized land records and maps. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "MP Employment Portal", "description": "Register for government job opportunities",
                "instructions": "Navigate to the portal and perform: Register for government job opportunities. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check Scholarship Status", "description": "Track MP scholarship application and disbursement",
                "instructions": "Navigate to the portal and perform: Track MP scholarship application and disbursement. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "Apply for Certificates", "description": "Income, caste, residence, birth, death certificates",
                "instructions": "Navigate to the portal and perform: Income, caste, residence, birth, death certificates. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "E-Return Filing", "description": "File property tax returns for municipal corporations",
                "instructions": "Navigate to the portal and perform: File property tax returns for municipal corporations. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Land Records (Mahabhulekh)", "description": "View 7/12 extracts and property cards online",
                "instructions": "Navigate to the portal and perform: View 7/12 extracts and property cards online. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check Application Status", "description": "Track certificate application status",
                "instructions": "Navigate to the portal and perform: Track certificate application status. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Pay Utility Bills", "description": "Electricity (MSEB/Adani/BEST) and water bill payment",
                "instructions": "Navigate to the portal and perform: Electricity (MSEB/Adani/BEST) and water bill payment. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "MCGM Services", "description": "Municipal Corporation of Greater Mumbai services",
                "instructions": "Navigate to the portal and perform: Municipal Corporation of Greater Mumbai services. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "Apply for Certificates", "description": "Income, caste, residence, and other certificates online",
                "instructions": "Navigate to the portal and perform: Income, caste, residence, and other certificates online. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Land Records (Bhulekh)", "description": "Access digitized land records and plots",
                "instructions": "Navigate to the portal and perform: Access digitized land records and plots. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "G2C Services", "description": "Government to citizen services portal",
                "instructions": "Navigate to the portal and perform: Government to citizen services portal. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check Scholarship Status", "description": "Track state scholarship application",
                "instructions": "Navigate to the portal and perform: Track state scholarship application. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "Sewa Kendra Services", "description": "Access certificates, licenses, and welfare schemes",
                "instructions": "Navigate to the portal and perform: Access certificates, licenses, and welfare schemes. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Land Records (Jamabandi)", "description": "View land ownership and mutation records",
                "instructions": "Navigate to the portal and perform: View land ownership and mutation records. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Pay Utility Bills", "description": "Electricity and water bill payments",
                "instructions": "Navigate to the portal and perform: Electricity and water bill payments. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Apply for Pension", "description": "Social security pension applications",
                "instructions": "Navigate to the portal and perform: Social security pension applications. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "Apply for Certificates", "description": "Income, caste, domicile, birth, death certificates",
                "instructions": "Navigate to the portal and perform: Income, caste, domicile, birth, death certificates. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Land Records (Apna Khata)", "description": "View Khasra, Khatauni, and land records online",
                "instructions": "Navigate to the portal and perform: View Khasra, Khatauni, and land records online. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Rajasthan SSO Services", "description": "Single Sign-On access to 500+ government services",
                "instructions": "Navigate to the portal and perform: Single Sign-On access to 500+ government services. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check Scholarship Status", "description": "Track Rajasthan scholarship application",
                "instructions": "Navigate to the portal and perform: Track Rajasthan scholarship application. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Job Portal Registration", "description": "Register for Rajasthan government jobs (REET, RPSC)",
                "instructions": "Navigate to the portal and perform: Register for Rajasthan government jobs (REET, RPSC). Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "Apply for Certificates", "description": "Income, caste, residence, community certificates online",
                "instructions": "Navigate to the portal and perform: Income, caste, residence, community certificates online. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "TN e-Sevai Services", "description": "Access 200+ government services via e-Sevai centres",
                "instructions": "Navigate to the portal and perform: Access 200+ government services via e-Sevai centres. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Land Records (Patta Chitta)", "description": "View land ownership (Patta) and property details (Chitta)",
                "instructions": "Navigate to the portal and perform: View land ownership (Patta) and property details (Chitta). Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check Application Status", "description": "Track certificate application progress",
                "instructions": "Navigate to the portal and perform: Track certificate application progress. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Pay Property Tax", "description": "Corporation/municipal property tax payment",
                "instructions": "Navigate to the portal and perform: Corporation/municipal property tax payment. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "MeeSeva Services", "description": "Access citizen services — certificates, licenses, payments",
                "instructions": "Navigate to the portal and perform: Access citizen services — certificates, licenses, payments. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Land Records (Dharani)", "description": "Online land registration and mutation portal",
                "instructions": "Navigate to the portal and perform: Online land registration and mutation portal. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Apply for Certificates", "description": "Income, caste, residence, birth, death certificates",
                "instructions": "Navigate to the portal and perform: Income, caste, residence, birth, death certificates. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check Application Status", "description": "Track MeeSeva application status",
                "instructions": "Navigate to the portal and perform: Track MeeSeva application status. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "TS-iPASS", "description": "Industrial project approvals and clearances",
                "instructions": "Navigate to the portal and perform: Industrial project approvals and clearances. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "Apply for Certificates", "description": "Income, caste, residence, birth, death certificates",
                "instructions": "Navigate to the portal and perform: Income, caste, residence, birth, death certificates. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Land Records (UP Bhulekh)", "description": "View Khasra, Khatauni, and land details online",
                "instructions": "Navigate to the portal and perform: View Khasra, Khatauni, and land details online. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "e-District Services", "description": "Access 500+ government services online",
                "instructions": "Navigate to the portal and perform: Access 500+ government services online. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check Scholarship Status", "description": "Track UP scholarship application",
                "instructions": "Navigate to the portal and perform: Track UP scholarship application. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "UP Police Services", "description": "FIR registration, character certificate, and verification",
                "instructions": "Navigate to the portal and perform: FIR registration, character certificate, and verification. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "RERA Registration", "description": "Real estate regulatory authority registration",
                "instructions": "Navigate to the portal and perform: Real estate regulatory authority registration. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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
            {"name": "Apply for Certificates", "description": "Income, caste, residence, birth, death certificates",
                "instructions": "Navigate to the portal and perform: Income, caste, residence, birth, death certificates. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Land Records (Banglarbhumi)", "description": "View land records, plot information, and mutation status",
                "instructions": "Navigate to the portal and perform: View land records, plot information, and mutation status. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Paras Portal", "description": "Access citizen services and welfare schemes",
                "instructions": "Navigate to the portal and perform: Access citizen services and welfare schemes. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Check Scholarship Status", "description": "Track WB pre-matric/post-matric scholarship",
                "instructions": "Navigate to the portal and perform: Track WB pre-matric/post-matric scholarship. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
            {"name": "Pay Property Tax", "description": "Municipal property tax payment",
                "instructions": "Navigate to the portal and perform: Municipal property tax payment. Look for relevant links or buttons on the page that match this task. Follow the on-screen instructions to complete the process."},
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

    def list_states(self) -> list[str]:
        """List all states that have registered portals (sorted)."""
        return sorted({e.state for e in self._domains.values() if e.state})

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


# ============================================================
# Task instruction sanitization (audit C6)
# ============================================================

# Sentence-level patterns for steps the safety policy forbids automating.
# The PolicyEngine pauses for CAPTCHA/OTP/payment regardless, but letting
# the planner read "Solve the CAPTCHA..." instructions wastes iterations
# and invites creative circumvention attempts.
_MANUAL_STEP_PATTERN = re.compile(
    r"(?:captcha|recaptcha|\botp\b|one[- ]time (?:password|code)|"
    r"security code|verification code|enter the otp|solve the captcha)",
    re.IGNORECASE,
)

_MANUAL_STEP_NOTE = (
    "Note: CAPTCHA/OTP/verification steps are completed manually by the "
    "user — skip them and wait at that point."
)


def sanitize_task_instructions(instructions: str) -> str:
    """Remove CAPTCHA/OTP automation steps from task instructions.

    Splits the instructions into sentences and drops any sentence that
    instructs solving a CAPTCHA or entering an OTP, then appends an
    explicit note that those steps belong to the user. Sentences that
    merely mention a later OTP step contextually are also dropped —
    over-filtering here is safe because policy pauses anyway.
    """
    if not instructions:
        return instructions

    parts = re.split(r"(?<=[.!?])\s+|\s*\n+\s*", instructions)
    kept = [p.strip() for p in parts if p.strip() and not _MANUAL_STEP_PATTERN.search(p)]

    cleaned = " ".join(kept)
    if cleaned != instructions.strip():
        cleaned = (cleaned + " " + _MANUAL_STEP_NOTE).strip()
    return cleaned
