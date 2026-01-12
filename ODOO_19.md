# Odoo 19.0 Porting Guide

This document describes the changes required when porting Odoo modules from version 18.0 to 19.0.

## 1. Security Groups Changes

### 1.1 Field `groups_id` → `group_ids` (res.users)
The field for assigning groups to users has been renamed.

**Before (18.0):**
```xml
<field name="groups_id" eval="[(6, 0, [ref('base.group_portal')])]"/>
```

**After (19.0):**
```xml
<field name="group_ids" eval="[Command.link(ref('base.group_portal'))]"/>
```

> **Note:** `Command.link()` is equivalent to `(4, id)` tuple operation.

### 1.2 Field `users` → `user_ids` (res.groups)
The field for assigning users to groups has been renamed.

**Before (18.0):**
```xml
<field name="users" eval="[(4, ref('base.user_admin'))]"/>
```

**After (19.0):**
```xml
<field name="user_ids" eval="[(4, ref('base.user_admin'))]"/>
```

### 1.3 New Privilege System (res.groups.privilege)
Odoo 19.0 introduces a new privilege system. Groups now use `privilege_id` instead of `category_id`.

**Before (18.0):**
```xml
<record model="res.groups" id="group_connect_user">
    <field name="name">User</field>
    <field name="category_id" ref="connect.module_connect_category"/>
</record>

<record model="res.groups" id="group_connect_admin">
    <field name="name">Admin</field>
    <field name="category_id" ref="connect.module_connect_category"/>
    <field name="users" eval="[(4, ref('base.user_admin'))]"/>
    <field name="implied_ids" eval="[(4, ref('group_connect_user'))]"/>
</record>
```

**After (19.0):**
```xml
<!-- First, create a privilege record -->
<record id="module_connect_privilege" model="res.groups.privilege">
    <field name="name">Connect</field>
    <field name="sequence">9</field>
    <field name="category_id" ref="connect.module_connect_category"/>
</record>

<!-- Then reference it in groups -->
<record model="res.groups" id="group_connect_admin">
    <field name="name">Admin</field>
    <field name="privilege_id" ref="module_connect_privilege"/>
    <field name="user_ids" eval="[(4, ref('base.user_admin'))]"/>
</record>

<record model="res.groups" id="group_connect_user">
    <field name="name">User</field>
    <field name="privilege_id" ref="module_connect_privilege"/>
</record>
```

> **Note:** The `implied_ids` field is no longer used in the same way with the new privilege system.

## 2. View Changes

### 2.1 Search View Group By
The `<group>` element in search views no longer supports `expand` and `string` attributes.

**Before (18.0):**
```xml
<group expand="0" string="Group By">
    <filter string="Direction" name="group_direction" context="{'group_by': 'direction'}"/>
</group>
```

**After (19.0):**
```xml
<group>
    <filter string="Direction" name="group_direction" context="{'group_by': 'direction'}"/>
</group>
```

### 2.2 Settings View Layout
For settings views, use `colspan="2"` for proper layout of div elements.

**Before (18.0):**
```xml
<div string="Technical Support" invisible="not is_registered">
```

**After (19.0):**
```xml
<div colspan="2" string="Technical Support" invisible="not is_registered">
```

## 3. Migration Checklist

When porting a module from 18.0 to 19.0, check the following:

- [ ] Replace `groups_id` with `group_ids` in res.users XML data
- [ ] Replace `users` with `user_ids` in res.groups XML data  
- [ ] Replace `category_id` with `privilege_id` in res.groups and create corresponding `res.groups.privilege` records
- [ ] Use `Command.link()` instead of tuple `(6, 0, [...])` for group assignments
- [ ] Remove `expand` and `string` attributes from `<group>` elements in search views
- [ ] Review form/settings views for layout issues and add `colspan` where needed
- [ ] Ensure all XML files end with a newline (code style)

## 4. Command Reference

| 18.0 Tuple | 19.0 Command | Description |
|------------|--------------|-------------|
| `(4, id)` | `Command.link(ref('...'))` | Link existing record |
| `(6, 0, [ids])` | `Command.set([...])` | Replace all with list |
| `(3, id)` | `Command.unlink(ref('...'))` | Unlink record |
| `(5,)` | `Command.clear()` | Clear all |

