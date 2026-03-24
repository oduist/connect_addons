# Porting Status: Odoo 19.0 OPL Integration

**Date**: Jan 22, 2026  
**Status**: ✅ PLANNING COMPLETE - READY FOR IMPLEMENTATION  
**Branch**: 18.0-opl → 19.0  

---

## Files Created for Planning

✅ **MIGRATE_19.0_OPL.md** - Detailed step-by-step migration plan  
✅ **DIFF_18.0_vs_18.0-opl.md** - Complete technical diff analysis  
✅ **PORTING_STATUS.md** - This file (progress tracking)  

---

## What's Ready to Port

### From 18.0-opl Branch (Total: 11 new files)

#### Python Models (100% ready)
```
✓ connect/models/license.py (500 lines)
  Status: ZERO CHANGES NEEDED
  Action: git checkout 18.0-opl -- 19.0/connect/models/license.py
```

#### Security & Data (95% ready)
```
✓ connect/security/license.xml (14 lines)
  Status: COMPATIBLE with Odoo 19
  Action: Copy from 18.0-opl
  
✓ connect/data/license.xml (20 lines)
  Status: COMPATIBLE with Odoo 19
  Action: Copy from 18.0-opl
```

#### Views (80% ready - needs testing)
```
⚠ connect/views/license.xml (68 lines)
  Status: Likely compatible, needs form layout validation
  Action: Copy from 18.0-opl, test responsive classes
  Risk: Form layout classes (w-75, w-sm-50) may need updates
  Owner: Manual testing required
```

#### JavaScript Components (70% ready - needs testing)
```
⚠ connect/static/src/components/license_banner/
  ├─ license_banner.js (63 lines)
  │  Status: Check service names and imports
  │  Risk: OWL API may have changed in Odoo 19
  │  Owner: Test and adjust imports
  │
  ├─ license_banner.scss (63 lines)
  │  Status: Likely compatible
  │  Risk: Bootstrap colors may differ
  │  Owner: Visual testing
  │
  └─ license_banner.xml (13 lines)
     Status: Likely compatible
     Risk: Font Awesome classes may differ
     Owner: Icon testing
```

#### Static Files (100% ready)
```
✓ connect/COPYRIGHT (19 lines)
  Status: STATIC - copy as-is
  
✓ connect/LICENSE (101 lines)
  Status: STATIC - copy as-is
```

#### Manifest Changes (90% ready)
```
⚠ connect/__manifest__.py
  Status: Needs merge with existing 19.0 manifest
  Changes needed:
  - Add "PyJWT" to external_dependencies.python
  - Add data/license.xml to data list
  - Add security/license.xml to security files list
  - Add views/license.xml to views list
  - Consider: "sequences": True flag
  Owner: Careful merge required
```

---

## Dependencies to Check/Add

### Python
```
✓ PyJWT - JWT token validation (RS256)
  Status: Must add to requirements.txt and __manifest__.py
  Version: 2.x (any recent version)
  
✓ requests - Already present (used in license.py)
  Status: Verify compatible version
```

### Odoo Models
```
? ir.module.module - Custom fields?
  Fields needed:
  - oduist_module_purchased (computed)
  - oduist_module_price (float)
  - oduist_license_status (computed)
  - oduist_module_show_price (computed)
  - latest_version (char)
  
  Status: MUST VERIFY if these exist in ir_module_module.py
  Action: Check 19.0/connect/models/ for these fields
```

---

## Pre-Implementation Checklist

- [ ] Verify PyJWT is in requirements.txt
- [ ] Check if ir_module_module.py has license-related fields
- [ ] Review form layout class compatibility in Odoo 19 docs
- [ ] Verify OWL/service API in Odoo 19 release notes
- [ ] Check Font Awesome version in Odoo 19

---

## Implementation Roadmap

### Phase 1: Python Models (5 min)
```bash
cd /srv/oduist/connect_addons/18.0
git checkout 18.0-opl -- models/license.py
# Then copy to 19.0
```

### Phase 2: Security & Data Files (10 min)
```bash
# Copy files directly
cp 18.0/connect/security/license.xml 19.0/connect/security/
cp 18.0/connect/data/license.xml 19.0/connect/data/
```

### Phase 3: XML Views (20 min)
```bash
# Copy and test form layout
cp 18.0/connect/views/license.xml 19.0/connect/views/
# Run manual tests in Odoo instance
```

### Phase 4: JavaScript Components (30 min)
```bash
# Copy JS component files
mkdir -p 19.0/connect/static/src/components/license_banner
cp -r 18.0/connect/static/src/components/license_banner/* \
  19.0/connect/static/src/components/license_banner/
# Test in browser, adjust imports if needed
```

### Phase 5: Static Files (5 min)
```bash
# Copy license files
cp 18.0/connect/COPYRIGHT 19.0/connect/
cp 18.0/connect/LICENSE 19.0/connect/
```

### Phase 6: Manifest Update (15 min)
```bash
# Edit 19.0/connect/__manifest__.py
# Merge changes carefully with existing structure
```

### Phase 7: Testing (30 min)
```bash
cd /srv/oduist/connect_addons/19.0
# Install module
# Test all features
# Verify integrations
```

---

## Known Issues & Questions

### ❓ ir.module.module Extensions
**Status**: UNRESOLVED  
**Question**: Do license-related computed fields exist in 19.0?  
**Action**: Check `19.0/connect/models/ir_module_module.py`  
**Impact**: If missing, must add these fields before testing license form  

### ❓ Odoo 19 Form Layout Classes  
**Status**: NEEDS VERIFICATION  
**Question**: Are Bootstrap classes `w-75`, `w-sm-50` valid in Odoo 19?  
**Action**: Check Odoo 19 CSS class documentation  
**Impact**: Form may break if classes renamed  
**Fallback**: Use standard `col` attributes  

### ❓ OWL Component API  
**Status**: LIKELY COMPATIBLE  
**Question**: Have service names changed in Odoo 19?  
**Action**: Check release notes for OWL API changes  
**Impact**: Systray component may not load  
**Fallback**: Update service/import paths if needed  

### ❓ Font Awesome Icons  
**Status**: NEEDS TESTING  
**Question**: Are `fa fa-*` classes available in Odoo 19?  
**Action**: Test in browser, check available icons  
**Impact**: Icons may not display  
**Fallback**: Use FontAwesome 6 syntax if needed  

---

## Git Workflow (Final)

```bash
# 1. Ensure we're on main branch
cd /srv/oduist/connect_addons

# 2. Switch to 18.0 worktree to get OPL files
cd 18.0
git checkout 18.0-opl

# 3. Get files
git show 18.0-opl:connect/models/license.py > /tmp/license.py
git show 18.0-opl:connect/data/license.xml > /tmp/data_license.xml
# ... repeat for other files

# 4. Return to 19.0
cd ../19.0
# Paste files
cp /tmp/license.py connect/models/license.py
# ... etc

# 5. Update manifest manually
vim connect/__manifest__.py

# 6. Test
# Install in Odoo instance
# Run tests
# Visual inspection

# 7. Commit
git add connect/
git commit -m "feat: port OPL license system from 18.0-opl"
git push
```

---

## Success Criteria

✅ Module installs without errors  
✅ License banner visible in systray  
✅ License form opens from menu  
✅ Trial period calculation works  
✅ License server connectivity verified  
✅ Purchase flow initiates correctly  
✅ All subscription preferences save  
✅ No console errors or warnings  

---

## Estimated Effort

- Planning: ✅ DONE (2 hours)
- Implementation: 2-3 hours (depends on Odoo 19 compatibility issues)
- Testing: 1 hour
- **Total**: 3-4 hours

---

## Next Steps

👉 **Proceed to implementation when ready**

1. Review MIGRATE_19.0_OPL.md for detailed steps
2. Verify all pre-implementation checklist items
3. Start with Phase 1 (Python models)
4. Work through phases sequentially
5. Test after each major component
6. Document any Odoo 19 compatibility issues found

---

## Contact & Notes

All planning documents complete and ready for review:
- Technical differences documented
- Migration steps detailed
- Risk areas identified
- Testing criteria defined

Ready to proceed on your signal! 🚀
