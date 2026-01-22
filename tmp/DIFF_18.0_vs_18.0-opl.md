# Complete Diff: 18.0 vs 18.0-opl (OPL License Integration)

## Summary

18.0-opl branch adds complete **Oduist Proprietary License (OPL)** system for managing software licensing, trial periods, and module purchases. This is a major feature addition (NOT just code refactoring).

**Statistics**:
- **New Files**: 11
- **Modified Files**: 2
- **Total Lines Added**: ~1,050
- **Total Lines Removed**: ~30

---

## 1. NEW FILES ADDED

### 1.1 LICENSE & COPYRIGHT (Static/Legal)

#### `connect/COPYRIGHT` (NEW - 19 lines)
```
ODUIST PROPRIETARY LICENSE
Copyright (c) 2025 Oduist
(Legal header text)
```

**Purpose**: Proprietary license notice for the module

---

#### `connect/LICENSE` (MODIFIED - 101 lines)
Changed from simple free license to detailed proprietary license terms.

---

### 1.2 PYTHON MODEL (500 lines)

#### `connect/models/license.py` (NEW)

**Class**: `OduistLicense(models.Model)`

**Primary Functionality**:

1. **License Token Management**
   - Stores JWT license tokens from oduist.com license server
   - Validates tokens with RS256 algorithm
   - Tracks instance UID (unique identifier for Odoo instance)

2. **Trial Period System**
   - 30-day trial on module installation
   - Checks trial expiry automatically
   - Returns days remaining

3. **License Status Checking**
   - `get_license_status(module_name)`: Returns status (trial_active, trial_expired, demo, purchased)
   - `check_license(module_name)`: Validates license (can raise exception)
   - `is_trial_valid(module_name)`: Checks 30-day trial

4. **License Server Integration**
   - `update_license_status()`: Calls license server to fetch license info
   - Handles JWT response with purchased modules list
   - Updates module metadata (latest_version, price)

5. **Purchase Flow**
   - `buy_licenses(module_list)`: Initiates purchase, returns payment link
   - `buy_all_licenses()`: Buy all non-purchased modules
   - Integrates with license server payment gateway

6. **Subscription Preferences** (opt-in services)
   - Security alerts subscription
   - Onboarding support subscription
   - Product news/AI tips subscription
   - Email address for notifications

7. **License Banner** (systray notification)
   - `get_oduist_license_banner()`: Returns banner info for active notifications
   - Priority: trial_expired > trial_active > demo
   - Used by JavaScript component to show in navbar

**Database Fields**:
```python
instance_uid             # UUID for this Odoo instance
license_token           # JWT token (text field, groups-based access)
registration_number     # Registration ID from server
subscribe_email         # Email for notifications
subscribe_to_security_alerts   # Boolean
subscribe_to_onboarding        # Boolean
subscribe_to_updates           # Boolean
oduist_modules          # Computed many2many of installed Oduist modules
all_modules_purchased   # Computed boolean
```

**Key Methods**:
```python
get_license_status(module_name) → dict
validate_token(token) → dict | None
is_trial_valid(module_name) → (bool, int)  # (is_valid, days_left)
get_oduist_license_banner() → dict
check_license(module_name, silent=True) → bool
update_license_status(raise_exc=True) → None
buy_licenses(module_list) → ir.actions.act_url
buy_all_licenses() → ir.actions.act_url
```

**External Dependencies**:
- `PyJWT`: JWT token decoding (RS256)
- `requests`: HTTP calls to license server
- `urllib.parse.urljoin`: URL building

---

### 1.3 SECURITY & DATA

#### `connect/security/license.xml` (NEW - 14 lines)

```xml
<record id="oduist_license_admin" model="ir.model.access">
  <!-- Only system admins (base.group_system) can access license model -->
  <!-- Full permissions: read, write, create, delete -->
</record>
```

**Access Control**: Only `base.group_system` group can manage licenses

---

#### `connect/data/license.xml` (NEW - 20 lines)

```xml
<record id="oduist_license_server" model="ir.config_parameter">
  <field name="key">oduist_license_server</field>
  <field name="value">https://license.oduist.com</field>
</record>
```

**Default Configuration**: License server URL hardcoded to `https://license.oduist.com`

---

### 1.4 VIEWS & UI

#### `connect/views/license.xml` (NEW - 68 lines)

**Form View**: License configuration form (`oduist_license_form`)

**Components**:
1. **Registration Number** (read-only header field)
2. **Subscription Preferences** (3 checkboxes):
   - Subscribe to Critical Security Alerts
   - Subscribe to Personalized Onboarding Support
   - Subscribe to Product News & AI Tips
3. **Email Field** (conditional - appears if any subscription is enabled)
4. **Buttons**:
   - "UPDATE LICENSE / PRICING" (green) - calls `update_license_status()`
   - "BUY ALL MODULES" (yellow, hidden if all purchased) - calls `buy_all_licenses()`
5. **Module List** (nested):
   - Shows all Oduist modules
   - Columns: Name, Installed Version, Latest Version, License Status, Info, Buy Button
   - Red row decoration if trial expired
   - Buy button hidden for purchased modules

**Menu Integration**: 
- Menu path: Settings → License
- Appears under `connect.connect_settings_menu`
- Groups: `connect.group_connect_admin`
- Sequence: 80

**Action**: `oduist_license_action` (server action that calls `open_license_form()`)

---

### 1.5 JAVASCRIPT COMPONENTS (139 lines total)

#### `connect/static/src/components/license_banner/license_banner.js` (NEW - 63 lines)

**Purpose**: Display license status in systray (top navbar)

**Features**:
1. **Component Type**: OWL component for Odoo web interface
2. **Template**: `oduist.LicenseBanner` 
3. **Services Used**:
   - `orm`: Odoo ORM for calling Python methods
   - `action`: Open dialogs/forms

4. **State Management**:
   - `visible`: Show/hide banner
   - `status`: License status (trial_active, trial_expired, demo)
   - `message`: Display message
   - `type`: Banner color (info, warning, danger)

5. **Initialization**: `onWillStart` hooks - loads license status before rendering

6. **Methods**:
   - `loadLicenseStatus()`: Calls Python `get_oduist_license_banner()`
   - `openSettings()`: Opens license form via `open_license_form()`
   - `bannerClass`: Computed property for CSS classes

7. **Registry**: Registered as systray item (`registry.category("systray")`)
   - Sequence: 1 (appears first in navbar)
   - Appears in top-right corner next to user menu

---

#### `connect/static/src/components/license_banner/license_banner.scss` (NEW - 63 lines)

**Styling**:
1. **Base Styles**:
   - Inline flex layout
   - 4px 12px padding
   - 4px border-radius
   - Hover effects (opacity, translation, shadow)

2. **States** (3 colored variants):
   - **info** (light blue): `#d1ecf1` background, `#0c5460` text
   - **warning** (light yellow): `#fff3cd` background, `#856404` text, pulse animation
   - **danger** (light red): `#f8d7da` background, `#721c24` text, pulse animation

3. **Animations**:
   - `pulse-warning`: 2s loop, subtle box-shadow pulse (yellow)
   - `pulse-danger`: 1.5s loop, stronger box-shadow pulse (red)

---

#### `connect/static/src/components/license_banner/license_banner.xml` (NEW - 13 lines)

**Template**:
```xml
<t t-name="oduist.LicenseBanner">
  <div visible when active, clickable, dynamic class>
    <icon based on type (info/warning/danger)>
    <span with message text>
  </div>
</t>
```

**Attributes**:
- `t-if="state.visible"`: Only render if license banner needed
- `t-att-class="bannerClass"`: Dynamic CSS class based on type
- `t-on-click="openSettings"`: Opens license form on click
- Icons: fa-info-circle, fa-exclamation-triangle, fa-exclamation-circle

---

## 2. MODIFIED FILES

### 2.1 `connect/__manifest__.py`

**Key Changes**:

1. **Version Bump**:
   ```
   1.0.13 → 2.0.1
   ```

2. **Python Dependencies Added**:
   ```python
   'external_dependencies': {
       'python': ['twilio', 'openai', 'PyJWT'],  # ← Added PyJWT
   }
   ```

3. **Data Files Added**:
   ```python
   'data': [
       'data/res_users.xml',
       'data/license.xml',              # ← NEW
       'data/ir_cron.xml',
       # ... rest unchanged ...
   ]
   ```

4. **Security Files Added**:
   ```python
   # Security
   'security/groups.xml',
   'security/license.xml',              # ← NEW
   'security/admin.xml',
   # ... rest unchanged ...
   ```

5. **Views Added**:
   ```python
   'views/menu.xml',
   'views/license.xml',                 # ← NEW
   'views/settings.xml',
   # ... rest unchanged ...
   ```

6. **Features Flag Added**:
   ```python
   'sequences': True,                   # ← NEW
   ```

**Note**: In 18.0-opl, some files are removed from data loading:
- `data/data.xml` (was referenced, now removed)
- `data/functions.xml` (was referenced, now removed)

---

### 2.2 `connect/LICENSE`

**Changes**: Updated license text from permissive open-source to **Oduist Proprietary License**.

**What Changed**:
- Full license terms (~101 lines)
- Restrictions on modification, distribution, reverse engineering
- Reference to COPYRIGHT file
- License server URL and registration requirements

---

## 3. INTEGRATION POINTS

### 3.1 ir.module.module Extension

The license system assumes these custom fields exist on `ir.module.module`:

```python
# Need to verify/create in ir_module_module.py
oduist_module_purchased         # Computed: Is module purchased?
oduist_module_price             # Float: Price of module
oduist_license_status           # Computed: Current license status
oduist_module_show_price        # Computed: Formatted price display
latest_version                  # Char: Latest available version
```

**Note**: These fields must be added to `connect/models/ir_module_module.py` (if not exist)

---

### 3.2 License Server API

**Endpoints Used**:

1. **License Check** (POST to `{base_url}/license/v2/check`)
   ```
   Input:
   - instance_uid: UUID
   - odoo_version: Major version (18, 19, etc.)
   - country_code: (optional)
   - subscribe_to_*: Subscription flags
   - subscribe_email: Email address
   
   Output:
   - token: JWT token
   - public_key: RS256 public key for validation
   - registration_number: Registration ID
   - modules: Dict of module info
     - latest_version: str
     - price: float
   - error: str (if error)
   ```

2. **License Buy** (POST to `{base_url}/license/v2/buy`)
   ```
   Input:
   - instance_uid: UUID
   - modules: List of module names
   - vat_number, vat_company_name, etc.: Company info
   
   Output:
   - payment_link: URL to payment gateway
   - error: str (if error)
   ```

---

## 4. CONSTANTS & CONFIGURATION

### 4.1 License Model

```python
PUBLIC_KEY_PARAM = "oduist_license.public_key"
ODUIST_MODULES = []  # ← Must be populated! (e.g., ['connect', 'connect_crm', ...])
```

**Critical**: `ODUIST_MODULES` list must be defined with actual Oduist module names!

### 4.2 Trial System

```
Trial Period: 30 days from module installation
Trial Valid: days_left > 0
Trial Expired: Raise error or warning (depending on silent flag)
```

---

## 5. WORKFLOW DIAGRAMS

### License Status Flow
```
Check License for Module
    ↓
Has License Token?
    ├─ YES → Validate JWT Token
    │         ├─ Valid? → Check if module in purchased_modules
    │         │           ├─ YES → LICENSED (return license_type)
    │         │           └─ NO → Check trial
    │         └─ Invalid? → Check trial
    └─ NO → Check trial
           ├─ Valid? → TRIAL_ACTIVE (return days_left)
           └─ Invalid? → TRIAL_EXPIRED
```

### License Update Flow
```
update_license_status()
    ↓
Call /license/v2/check with:
- instance_uid
- odoo_version
- subscription prefs
- company info
    ↓
Receive JWT token + public key
    ↓
Decode token, extract:
- purchased_modules
- registration_number
- module metadata
    ↓
Save to database
- license_token
- registration_number
- module prices/versions
```

### Purchase Flow
```
User clicks "BUY LICENSES"
    ↓
Call /license/v2/buy with:
- instance_uid
- modules list
- company VAT info
    ↓
Receive payment_link
    ↓
Open in new browser tab
    ↓
User pays on license server
```

---

## 6. SUMMARY OF CHANGES FOR PORTING

| Component | Files | Status | Odoo 19 Changes |
|-----------|-------|--------|-----------------|
| **Model** | `models/license.py` | New 500 lines | None (Python syntax universal) |
| **Security** | `security/license.xml` | New 14 lines | None |
| **Data** | `data/license.xml` | New 20 lines | None |
| **Views** | `views/license.xml` | New 68 lines | Check form layout classes |
| **JS** | `license_banner.js` | New 63 lines | Check imports/service names |
| **CSS** | `license_banner.scss` | New 63 lines | Check Bootstrap colors |
| **XML Template** | `license_banner.xml` | New 13 lines | Check icon classes |
| **Manifest** | `__manifest__.py` | Modified | Add PyJWT, data files |
| **License** | `LICENSE` | Modified | Copy as-is |
| **Copyright** | `COPYRIGHT` | New 19 lines | Copy as-is |

---

## 7. TESTING REQUIREMENTS

- [ ] License token validation (valid/invalid/expired)
- [ ] Trial period calculation
- [ ] License banner appears in systray
- [ ] License form loads without errors
- [ ] Update license status calls server
- [ ] Buy licenses initiates payment flow
- [ ] Module purchase status reflects in list view
- [ ] Subscription preferences save correctly

---

## Questions for 19.0 Integration

1. ✓ Does `ir.module.module` have license-related fields?
2. ? Are form layout classes (`w-75`, `w-sm-50`) valid in Odoo 19?
3. ? Are Bootstrap color values (`#d1ecf1`) correct for Odoo 19 theme?
4. ? Is `registry.category("systray")` API unchanged in Odoo 19?
5. ? Are Font Awesome class names (`fa fa-info-circle`) available in Odoo 19?

