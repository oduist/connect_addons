# Quick Reference: OPL License System Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                      ODUIST LICENSE SYSTEM                      │
└─────────────────────────────────────────────────────────────────┘

┌──────────────────────┐         ┌──────────────────────┐
│   Odoo Instance      │         │  License Server      │
│  (19.0 Connect)      │◄───────►│  (oduist.com)        │
│                      │  JWT    │                      │
│ ┌────────────────┐   │ Token   │ ┌────────────────┐   │
│ │ oduist.license │   │ Verify  │ │ License DB     │   │
│ │    (Model)     │   │ Reg #   │ │ - Tokens       │   │
│ │                │   │ Prices  │ │ - Purchases    │   │
│ │ - Token        │   │         │ │ - Pricing      │   │
│ │ - Trial Track  │   │         │ │ - Subscriptions│   │
│ │ - Status Check │   │         │ │                │   │
│ └────────────────┘   │         │ └────────────────┘   │
│ ┌────────────────┐   │         │ ┌────────────────┐   │
│ │ License Banner │   │ API Calls│ │ Payment Link   │   │
│ │  (JS Systray)  │   │         │ │ (Stripe/etc)   │   │
│ └────────────────┘   │         │ └────────────────┘   │
└──────────────────────┘         └──────────────────────┘

User Flow:
1. Install module → 30-day trial starts
2. Check license → Query oduist.license model
3. Show banner → Trial status in navbar
4. Buy → Call /license/v2/buy → Payment link
5. Verify → Call /license/v2/check → Get JWT token
```

---

## File Structure

```
connect/
├── models/
│   └── license.py ................... Main license model (500 lines)
│       Class: OduistLicense(models.Model)
│       - Single-record model (one per instance)
│       - Stores JWT token, trial tracking, subscriptions
│       - Validates license, manages purchases
│
├── security/
│   └── license.xml .................. ACL rules (14 lines)
│       - Access: base.group_system only
│
├── data/
│   └── license.xml .................. Default config (20 lines)
│       - License server URL: https://license.oduist.com
│
├── views/
│   └── license.xml .................. UI form (68 lines)
│       - License configuration form
│       - Module purchase list
│       - Menu: Settings → License
│
├── static/src/components/license_banner/
│   ├── license_banner.js ............ OWL component (63 lines)
│   │   - Systray item (top navbar)
│   │   - Shows trial/demo status
│   │   - Click to open license form
│   │
│   ├── license_banner.scss .......... Styling (63 lines)
│   │   - Colors: info, warning, danger
│   │   - Animations: pulse effects
│   │
│   └── license_banner.xml .......... Template (13 lines)
│       - Dynamic icon + message
│
├── COPYRIGHT ....................... License header (19 lines)
├── LICENSE ......................... Proprietary terms (101 lines)
└── __manifest__.py ................ Updated manifest
    - Added: PyJWT dependency
    - Added: license.xml, security/license.xml, views/license.xml
```

---

## Key Classes & Methods

### OduistLicense Model

```python
# Getters
get_license_status(module_name) → dict
  Returns: {status, order_id/days_left}
  Status: "trial_active" | "trial_expired" | "demo" | "<license_type>"

get_oduist_license_banner() → dict
  Returns: {module_name, status, message, type}
  For navbar banner display

is_trial_valid(module_name) → (bool, int)
  Returns: (is_valid, days_left)

validate_token(token) → dict
  Returns: Decoded JWT payload or None

# Setters
set_param(param, value) → None
write(vals) → None

# Actions
update_license_status() → None
  Calls: /license/v2/check
  Updates: license_token, registration_number, module metadata

buy_licenses(module_list) → ir.actions.act_url
  Calls: /license/v2/buy
  Returns: {type, url (payment link), target}

buy_all_licenses() → ir.actions.act_url
  Helper: buys all non-purchased modules

# Checks
check_license(module_name, silent=False) → bool
  Returns: True if valid, False if expired
  Raises: ValidationError if silent=False and expired
```

### LicenseBanner Component (JS)

```javascript
loadLicenseStatus()
  Calls Python: orm.call("oduist.license", "get_oduist_license_banner", [])
  Updates state: visible, status, message, type

openSettings()
  Calls Python: orm.call("oduist.license", "open_license_form", [])
  Opens: License configuration form

bannerClass (computed)
  Returns: "oduist-license-banner oduist-license-banner-{type}"
  Where type: "info" | "warning" | "danger"
```

---

## License Server API

### Endpoint 1: Check License Status
```
POST /license/v2/check

Input:
{
  "instance_uid": "uuid-here",
  "odoo_version": 19,
  "country_code": "US" (optional),
  "subscribe_to_security_alerts": true (optional),
  "subscribe_to_onboarding": true (optional),
  "subscribe_to_updates": true (optional),
  "subscribe_email": "admin@company.com" (if any subscribe enabled)
}

Output (success):
{
  "token": "eyJhbGc...", // JWT with RS256
  "public_key": "-----BEGIN PUBLIC KEY-----...",
  "registration_number": "REG-2025-001",
  "modules": {
    "connect": {
      "license_type": "perpetual",
      "order_id": "ORD-12345",
      "latest_version": "2.0.5",
      "price": 999.00
    },
    "connect_crm": {...}
  }
}

Output (error):
{
  "error": "Instance UID mismatch" // or other error
}
```

### Endpoint 2: Initiate Purchase
```
POST /license/v2/buy

Input:
{
  "instance_uid": "uuid-here",
  "modules": ["connect", "connect_crm"],
  "vat_number": "IE1234567X" (optional),
  "vat_company_name": "Acme Inc",
  "vat_street": "123 Main St",
  "vat_city": "Dublin",
  "vat_state": "County Dublin",
  "vat_country": "IE",
  "vat_postcode": "D01 AB12"
}

Output (success):
{
  "payment_link": "https://pay.oduist.com/order/xyz..."
}

Output (error):
{
  "error": "Module not found or invalid instance"
}
```

---

## JWT Token Structure

```json
{
  "iss": "oduist.com",
  "instance_uid": "uuid-here",
  "instance_type": "production" or "demo",
  "registration_number": "REG-2025-001",
  "exp": 1735689600,
  "purchased_modules": {
    "connect": {
      "license_type": "perpetual" | "monthly" | "yearly",
      "order_id": "ORD-12345",
      "expires_at": "2026-12-31"
    },
    "connect_crm": {...}
  }
}
```

**Validation**:
- Algorithm: RS256 (RSA public key)
- Signature verified against public key from license server
- Instance UID must match configured instance_uid
- Expiry checked via `exp` claim

---

## Trial System

```
Timeline:
┌─────────────────────────────────────────┐
│ Module Installation (create_date)       │
│ ↓                                       │
│ Trial Valid: Days 0-30                  │
│ ├─ 0-7 days: GREEN (info banner)        │
│ ├─ 8-22 days: GREEN (info banner)       │
│ ├─ 23-30 days: YELLOW (warning banner)  │
│ └─ 30+ days: RED (danger banner)        │
│                                         │
└─────────────────────────────────────────┘

Calculation:
- days_passed = now - module.create_date
- days_left = 30 - days_passed
- is_valid = days_left > 0
```

---

## Constants & Configuration

```python
# In license.py
PUBLIC_KEY_PARAM = "oduist_license.public_key"
  Storage: ir.config_parameter
  Purpose: Verify JWT signatures

ODUIST_MODULES = []  
  ⚠️ MUST BE POPULATED!
  Example: ['connect', 'connect_crm', 'connect_elevenlabs']
  Purpose: List of modules that have licensing

# In data/license.xml
oduist_license_server = "https://license.oduist.com"
  Storage: ir.config_parameter
  Purpose: Base URL for license server
```

---

## Computed Fields (ir.module.module extension)

These fields must exist on ir.module.module model:

```python
oduist_module_purchased (Boolean, computed)
  # True if module is in current license token's purchased_modules

oduist_license_status (Char, computed)
  # Display value: "Licensed" | "Trial (15 days)" | "Trial Expired"

oduist_module_show_price (Char, computed)
  # Display: "€999" or "Request Quote"

oduist_module_price (Float, stored)
  # Actual price from license server

latest_version (Char, stored)
  # Latest available version from server
```

---

## Banner Display Logic

```python
Priority:
1. trial_expired
   └─ RED banner: "Connect: Buy a license to continue"
   
2. trial_active
   └─ Color: YELLOW if ≤7 days, GREEN if >7 days
   └─ Message: "Connect Trial: X days remaining"
   
3. demo
   └─ YELLOW banner: "Connect: Demo License"
   
4. purchased
   └─ NO banner (all_modules_purchased = True)
```

---

## Dependencies

### Python
```
PyJWT >= 2.0
  Purpose: JWT token decoding (RS256)
  File: requirements.txt + __manifest__.py

requests >= 2.28
  Purpose: HTTP calls to license server
  Already: Present in connect (for Twilio)
```

### Odoo
```
External Models:
- ir.module.module (read/write custom fields)
- ir.config_parameter (read/write license config)
- res.company (read for VAT/country info)
- ir.model.access (security rules)

Built-in Models Used:
- base.group_system (ACL)
- base.group_erp_manager (field access)
```

---

## Testing Checklist (One-liner)

```
✓ Module installs | ✓ Banner shows | ✓ Form opens | 
✓ Token validates | ✓ Trial counts | ✓ Server connects | 
✓ Buy initiates | ✓ Prefs save | ✓ No errors
```

---

## Rollback Plan (If Issues)

```bash
# Remove all OPL files and revert to base 18.0
git checkout 18.0 -- connect/
# Then update manifest to remove OPL references

# Or: Completely disable banner
# Edit: license_banner.js → change registry.category to non-rendering
```

---

## Contact Points

**License Server**: https://license.oduist.com  
**API Version**: v2  
**Default Timeout**: 30 seconds (requests)  
**Retry Logic**: None (single attempt, server handles)  

