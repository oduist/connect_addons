# Porting Oduist Proprietary License (OPL) to Odoo 19.0

**Status**: 📋 PLANNING PHASE - Ready for Implementation  
**Date**: Jan 22, 2026  
**Source**: 18.0-opl branch  
**Target**: 19.0 version  

---

## 📚 Documentation Files

### 1. **PORTING_STATUS.md** (Start Here! ⭐)
- Current progress and checklist
- What's ready vs what needs work
- Pre-implementation verification
- Risk assessment
- Effort estimation

**Read this first to understand current state.**

---

### 2. **MIGRATE_19.0_OPL.md** (Implementation Plan)
- Step-by-step porting instructions
- Phase-by-phase breakdown (5 phases)
- Odoo 19-specific adjustments needed
- Git workflow for each phase
- Known issues and questions
- Timeline for each phase

**Use this during implementation.**

---

### 3. **DIFF_18.0_vs_18.0-opl.md** (Technical Reference)
- Complete diff analysis: what changed between 18.0 and 18.0-opl
- 11 new files added (~1,050 lines)
- 2 modified files
- Detailed explanation of each component
- Integration points and dependencies
- API endpoint documentation

**Reference this for understanding system architecture.**

---

### 4. **QUICK_REFERENCE.md** (Cheat Sheet)
- Visual system overview
- File structure at a glance
- Key classes and methods
- API endpoints summary
- JWT token structure
- Trial system logic
- Testing checklist

**Use this as a quick lookup during development.**

---

## 🎯 Quick Start

### For Planning/Understanding
1. Read **PORTING_STATUS.md** (5 min)
2. Scan **QUICK_REFERENCE.md** (5 min)
3. Review **DIFF_18.0_vs_18.0-opl.md** (15 min)

### For Implementation
1. Review **MIGRATE_19.0_OPL.md** Phase 1
2. Follow step-by-step instructions
3. Test after each phase
4. Document any issues
5. Repeat for all 7 phases

### For Debugging
1. Check **QUICK_REFERENCE.md** for architecture
2. Look up method signatures in **DIFF_18.0_vs_18.0-opl.md**
3. Verify against **MIGRATE_19.0_OPL.md** expectations

---

## 📊 Project Overview

**What's Being Added**:
- ✅ License token management (JWT RS256)
- ✅ 30-day trial tracking system
- ✅ License server integration (check + buy)
- ✅ Purchase flow with payment gateway
- ✅ License status banner in navbar
- ✅ License configuration form
- ✅ Subscription preferences (email, alerts, etc)

**Current Status**:
- ✅ Complete diff analysis done
- ✅ Migration plan documented
- ✅ Risk assessment completed
- ✅ Dependencies identified
- ⏳ Python models: ready for checkout
- ⏳ XML/JS files: ready for porting
- ⏳ Testing: pending implementation

**Estimated Effort**: 3-4 hours total (planning + implementation + testing)

---

## 🔄 Workflow Summary

```
18.0-opl Branch
    │
    ├─ models/license.py ────┐
    ├─ security/license.xml  ├──► 19.0 (with adjustments)
    ├─ data/license.xml      ├──► Testing
    ├─ views/license.xml     ├──► Verification
    ├─ static/.../*.js       ├──► Integration
    └─ COPYRIGHT/LICENSE ────┘
```

### Git Strategy (for you)
1. **Don't** use `git checkout 18.0-opl` directly in 19.0
2. **Instead**: Use git worktrees approach described in MIGRATE_19.0_OPL.md
3. Verify file compatibility before each copy
4. Test incrementally after each component

---

## ✅ Verification Checklist

### Pre-Implementation
- [ ] Read all 4 documentation files
- [ ] Verify PyJWT in requirements.txt
- [ ] Check ir.module.module for license fields
- [ ] Review Odoo 19 release notes for OWL/service changes

### During Implementation
- [ ] Phase 1: Python model (automated, no test needed)
- [ ] Phase 2: Security/Data files (copy + verify XML syntax)
- [ ] Phase 3: Views (test form layout)
- [ ] Phase 4: JavaScript (test systray rendering)
- [ ] Phase 5: Static files (copy as-is)
- [ ] Phase 6: Manifest (careful merge)
- [ ] Phase 7: Full integration test

### Post-Implementation
- [ ] Module installs without errors
- [ ] License banner visible in systray
- [ ] License form opens from Settings menu
- [ ] All buttons work (Update, Buy)
- [ ] No console errors
- [ ] Trial calculation correct
- [ ] Server connectivity verified

---

## 🚨 Known Issues/Risks

1. **ir.module.module fields** (CRITICAL)
   - Need to verify license-related computed fields exist
   - If missing, must add before testing license form

2. **Odoo 19 Form Layout** (MEDIUM)
   - Bootstrap class names may have changed
   - May need fallback to standard `col` attributes
   - Test responsive layout after porting

3. **OWL Service API** (MEDIUM)
   - Service names might differ (orm, action)
   - Check Odoo 19 release notes

4. **Font Awesome Icons** (LOW)
   - Icon class names might differ
   - Easy to fix if they don't render

---

## 📞 Support References

**Porting Docs Location**:
```
/srv/oduist/connect_addons/19.0/
├── README_OPL_PORTING.md (this file)
├── PORTING_STATUS.md
├── MIGRATE_19.0_OPL.md
├── DIFF_18.0_vs_18.0-opl.md
└── QUICK_REFERENCE.md
```

**Git Branches**:
- Source: `/srv/oduist/connect_addons/18.0` (branch: 18.0-opl)
- Target: `/srv/oduist/connect_addons/19.0` (current)

**License Server API**:
- Base URL: https://license.oduist.com
- Endpoints:
  - POST /license/v2/check (verify license status)
  - POST /license/v2/buy (initiate purchase)

---

## 🎓 Learning Path

**New to this project?**
1. Start with QUICK_REFERENCE.md (5 min) - understand system
2. Read DIFF_18.0_vs_18.0-opl.md (30 min) - learn what's being added
3. Review PORTING_STATUS.md (10 min) - understand current state
4. Follow MIGRATE_19.0_OPL.md (during implementation)

**Already familiar?**
1. Check PORTING_STATUS.md for checklist
2. Jump to relevant phase in MIGRATE_19.0_OPL.md
3. Use QUICK_REFERENCE.md for lookups

---

## 📝 Notes

- ✅ **Python models** are 100% identical across Odoo versions
- ✅ **XML/JS files** need minor Odoo 19 adjustments
- ✅ **No code changes needed** - just porting and testing
- ⚠️  **PyJWT dependency** must be added
- ⚠️  **Manifest merge** requires careful attention

---

**Ready to proceed?** → Start with **PORTING_STATUS.md** ✨

