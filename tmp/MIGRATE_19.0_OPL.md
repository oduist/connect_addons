# Migration Plan: Odoo 19.0 OPL (Oduist Proprietary License) Integration

## Overview
Porting license management system from 18.0-opl branch to 19.0 version. 

**Status**: Planning phase - NO CODE CHANGES MADE YET

**Strategy**: 
1. Checkout Python models from 18.0-opl (identical across versions)
2. Manually port XML/JS files with Odoo 19-specific adjustments
3. Update field definitions for Odoo 19 compatibility

---

## Difference Map: 18.0 vs 18.0-opl

### Files Added in 18.0-opl:
```
connect/
├── COPYRIGHT (19 lines) - License header
├── LICENSE (modified - 101 lines)
├── models/license.py (NEW - 500 lines) - Main license model
├── security/license.xml (NEW - 14 lines) - ACL rules
├── data/license.xml (NEW - 20 lines) - License server config
├── views/license.xml (NEW - 68 lines) - License form UI
└── static/src/components/license_banner/ (NEW)
    ├── license_banner.js (63 lines) - Systray component
    ├── license_banner.scss (63 lines) - Styling
    └── license_banner.xml (13 lines) - Template
```

### Modified Files in 18.0-opl:
```
connect/__manifest__.py
- Version: 1.0.13 → 2.0.1
- Dependencies: Added "PyJWT"
- Data files: Added data/license.xml, security/license.xml, views/license.xml
- Added sequences: True
- Removed: data/data.xml, data/functions.xml
```

### Dependencies Added:
- **Python**: PyJWT (for JWT token validation)
- **Odoo models**: 
  - Reads: ir.module.module, ir.config_parameter, res.company, base.group_erp_manager
  - Writes: ir.module.module (oduist_module_price, latest_version)

---

## Porting Checklist for 19.0

### Phase 1: Python Models (AUTO)
- [ ] `git checkout 18.0-opl -- 19.0/connect/models/license.py`
- [ ] Verify: No changes needed (Python syntax identical)

### Phase 2: Security/Data Files (MANUAL)

#### 2.1 `security/license.xml` → `security/license.xml`
**Changes for Odoo 19**:
- No Odoo 19-specific changes needed (ir.model.access unchanged)
- File is identical to 18.0-opl

**Action**: Copy from 18.0-opl

---

#### 2.2 `data/license.xml` → `data/license.xml`
**Changes for Odoo 19**:
- No changes needed (ir.config_parameter unchanged)
- File is identical to 18.0-opl

**Action**: Copy from 18.0-opl

---

### Phase 3: Views (MANUAL - XML Adjustments)

#### 3.1 `views/license.xml` → `views/license.xml`
**Required Changes for Odoo 19**:

1. **Form Field Layout**: Odoo 19 simplified form attributes
   - Check if `w-75`, `w-sm-50` etc. classes are still valid in Odoo 19
   - May need adjustment to standard `col` attributes

2. **Button Classes**: Verify Bootstrap class names
   - `btn-success`, `btn-warning` should be compatible
   - Check if `me-2` (margin-end) is still standard

3. **Invisible Condition**: May need parentheses adjustment
   ```xml
   <!-- 18.0-opl -->
   invisible="not subscribe_to_security_alerts and not subscribe_to_onboarding and not subscribe_to_updates"
   
   <!-- 19.0 - should work unchanged, but verify -->
   invisible="not subscribe_to_security_alerts and not subscribe_to_onboarding and not subscribe_to_updates"
   ```

4. **List Decorations**: Check if `decoration-danger` behavior unchanged
   - Likely compatible but verify with test

**Key Fields to Check**:
- `ir.module.module` fields:
  - `oduist_license_status` - compute field?
  - `oduist_module_show_price` - compute field?
  - `oduist_module_purchased` - compute field?
  - `installed_version` - standard field
  - `latest_version` - custom field

**Action**: Need to verify these computed fields exist in ir.module.module or define them

---

### Phase 4: JavaScript Components (MANUAL - Minor Changes)

#### 4.1 `static/src/components/license_banner/license_banner.js`

**Required Changes for Odoo 19**:

1. **Import/Registry changes**:
   - Owl version might differ
   - Check if `@odoo/owl` import path is correct for Odoo 19
   - `registry` API should be compatible

2. **Service names**: 
   - `orm` service → might be `orm` in 19 (verify)
   - `action` service → might be `action` in 19 (verify)

3. **Template registration**:
   - `registry.category("systray")` should be compatible
   - Check if sequence `1` is valid (may conflict with other items)

**Action**: Test with Odoo 19, adjust imports if needed

---

#### 4.2 `static/src/components/license_banner/license_banner.scss`

**Changes for Odoo 19**:

1. Verify Sass/CSS is processed correctly (likely no changes)
2. Check Bootstrap version compatibility:
   - Color values like `#d1ecf1`, `#0c5460` should be fine
   - Animation syntax is standard CSS

**Action**: Copy as-is, test if animations work

---

#### 4.3 `static/src/components/license_banner/license_banner.xml`

**Changes for Odoo 19**:

- Verify `t-on-click` directive works (should be fine)
- Check if `t-att-class` works (should be fine)
- Verify icon classes `fa fa-*` are available (Font Awesome might change)

**Action**: May need to update Font Awesome class names depending on Odoo 19 version

---

### Phase 5: Manifest Updates

#### 5.1 `__manifest__.py`

**Required Changes for Odoo 19**:

1. **Add PyJWT dependency**:
   ```python
   "external_dependencies": {
       "python": ["twilio", "openai", "PyJWT"],
   }
   ```

2. **Update data files list**:
   ```python
   "data": [
       ...existing files...
       "data/license.xml",
       "security/license.xml", 
       "views/license.xml",
   ]
   ```

3. **Note**: Remove references to deleted files (data/data.xml, data/functions.xml) if they don't exist in 19.0

4. **Sequences flag**: May not be needed in Odoo 19
   - Check if `"sequences": True,` is still required

**Action**: Carefully merge with existing 19.0 manifest

---

## Extended Model Fields: ir.module.module

The `views/license.xml` references these fields on ir.module.module which may be custom:

```python
# Need to verify these exist or create them:
- oduist_license_status       # compute field - status string
- oduist_module_show_price    # compute field - display price
- oduist_module_purchased     # compute field - boolean
- oduist_module_price         # stored field - price value
```

**Task**: Check if ir_module_module.py model has these fields defined, or add them

---

## COPYRIGHT & LICENSE Files

Two static files that were added:

1. **COPYRIGHT** (19 lines): Legal header for proprietary license
2. **LICENSE** (modified): Updated terms for OPL

**Action**: Copy from 18.0-opl as-is

---

## Testing Checklist for Odoo 19

- [ ] Module installs without errors
- [ ] License banner appears in systray (top navigation)
- [ ] License form opens from menu: Settings → License
- [ ] License server URL is set in data/license.xml
- [ ] JWT token validation works (test with valid/invalid tokens)
- [ ] Trial period calculation works
- [ ] All subscription preference fields appear and save
- [ ] "Update License Status" button calls server correctly
- [ ] "Buy Licenses" flow initiates payment link
- [ ] License status displays correctly in module list view
- [ ] Banner colors change based on trial status

---

## Git Workflow

```bash
# 1. Checkout Python model (identical across versions)
git checkout 18.0-opl -- 19.0/connect/models/license.py

# 2. Manual porting of XML/JS files (one by one)
# - Review diffs
# - Apply Odoo 19 adjustments
# - Test each file

# 3. Update manifest
# - Add license-related data files
# - Add PyJWT dependency
# - Verify all paths correct

# 4. Final test
# - Install module
# - Verify all functionality works
```

---

## Known Issues / Questions

1. **ir.module.module extension**: Need to verify if custom fields exist
2. **Odoo 19 form layout**: Need to test responsive class compatibility
3. **Systray sequence**: Check if sequence=1 conflicts with other items
4. **Font Awesome**: May need icon class updates for Odoo 19

---

## Timeline

- Phase 1 (Python): 5 min (git checkout)
- Phase 2 (Security/Data): 10 min (copy + test)
- Phase 3 (Views XML): 30 min (testing + adjustment)
- Phase 4 (JS components): 30 min (testing + adjustment)
- Phase 5 (Manifest): 15 min (merge)
- Testing: 30 min

**Total**: ~2 hours (with testing)

