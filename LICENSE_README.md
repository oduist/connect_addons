# Connect OPL-1 Licensing System

This document describes the OPL-1 licensing system implemented for Connect modules.

## Overview

Connect modules now use the **Odoo Proprietary License v1.0 (OPL-1)** with a 30-day trial period and JWT-based license tokens.

## How It Works

### Trial Period
- Upon first installation, a 30-day trial period begins automatically
- The trial start date is tracked in the `connect.module` model
- No license token required during trial
- A banner appears in the navbar showing days remaining

### License Token
- After trial expiration, a valid license token is required
- Tokens are JWT (JSON Web Tokens) signed with RS256 algorithm
- Tokens are module-specific and instance-specific
- Tokens can be obtained from [oduist.com](https://oduist.com/my)

### Banner Behavior
- **Trial Active (>7 days)**: Blue info banner showing days left
- **Trial Active (≤7 days)**: Yellow warning banner with pulse animation
- **Trial Expired**: Red danger banner with pulse animation
- **Licensed**: No banner shown
- Click banner to open Settings page

## Token Structure

JWT payload contains:
```json
{
  "issuer": "oduist.com",
  "instance_uid": "database_uuid",
  "type": "production",
  "expire": 1735689600,
  "modules": ["connect", "connect_crm"],
  "partner_id": "1",
  "partner_name": "Partner Name"
}
```

## Generating Tokens

### Using the Script

Run the token generation script:
```bash
python3 generate_license_token.py
```

Follow the interactive prompts to:
1. Enter instance UID (get from Settings or database.uuid)
2. Select license type (production/trial/development)
3. Choose modules to license
4. Enter partner information
5. Set expiration date

### Manual Token Generation

```python
import jwt
from datetime import datetime, timedelta

# Use the PRIVATE_KEY from generate_license_token.py

payload = {
    "issuer": "oduist.com",
    "instance_uid": "your-database-uuid",
    "type": "production",
    "expire": int((datetime.now() + timedelta(days=365)).timestamp()),
    "modules": ["connect"],
    "partner_id": "1",
    "partner_name": "Customer Name"
}

token = jwt.encode(payload, PRIVATE_KEY, algorithm='RS256')
print(token)
```

## Installing a License

1. Go to **Connect → Settings → API Keys**
2. Scroll to **License (OPL-1)** section
3. Paste the JWT token
4. Save settings
5. Refresh the page

## Using the License Decorator

Protect module functionality with the `@_license` decorator:

```python
from odoo.addons.connect.models.license import _license

class CRMLead(models.Model):
    _inherit = 'crm.lead'

    @_license(module='connect_crm')
    def action_call(self):
        # This method requires connect_crm license
        pass
```

The decorator:
- Checks if the trial is active or a valid license exists
- Raises `UserError` if trial expired and no valid license
- Shows helpful error message directing user to obtain license

## Module Installation Tracking

Each Connect module should:
1. Add entry to `connect.module` in `post_init_hook`
2. Remove entry in `uninstall_hook`

Example (in module's `hooks.py`):
```python
def post_init_hook(env):
    env['connect.module'].sudo().create({
        'name': 'connect_crm',
        'description': 'Connect CRM Integration'
    })

def uninstall_hook(env):
    module = env['connect.module'].sudo().search([('name', '=', 'connect_crm')])
    if module:
        module.unlink()
```

## Files Changed

### New Files
- `connect/models/module.py` - Installation tracking
- `connect/models/license.py` - License validation and decorator
- `connect/hooks.py` - Installation hooks
- `connect/static/src/components/license_banner/` - JS banner component
- `generate_license_token.py` - Token generation script

### Modified Files
- `connect/__manifest__.py` - License, hooks, dependencies, assets
- `connect/__init__.py` - Import hooks
- `connect/models/__init__.py` - Import new models
- `connect/models/settings.py` - Add license_token field
- `connect/views/settings.xml` - Add license_token UI
- `connect/security/admin.xml` - Add connect.module security

## Security

### Public Key
The public key for token verification is embedded in `connect/models/license.py`

### Private Key
**IMPORTANT**: Keep the private key secure!
- Used only for signing tokens
- Store in secure location (password manager, encrypted file)
- Do not commit to public repositories
- Included in `generate_license_token.py` for convenience (should be moved to secure location in production)

## API

### Python
```python
# Check license status
self.env['connect.license'].get_license_status('connect')

# Returns:
# {
#     'status': 'trial_active' | 'trial_expired' | 'licensed',
#     'days_left': 15,  # for trial
#     'message': 'Trial: 15 days remaining'
# }
```

### JavaScript
The banner component automatically checks license status on load via RPC:
```javascript
await this.orm.call("connect.license", "get_license_status", ["connect"])
```

## Troubleshooting

### Token Invalid
- Check instance_uid matches database UUID
- Verify token hasn't expired
- Ensure token includes required module

### Banner Not Showing
- Clear browser cache
- Check browser console for JS errors
- Verify assets were properly loaded

### Trial Not Starting
- Check `connect.module` record exists
- Verify `create_date` is set correctly
- Check hooks executed during installation

## Support

For license-related issues:
- Email: support@oduist.com
- Website: https://oduist.com/support
