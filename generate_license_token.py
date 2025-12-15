#!/usr/bin/env python3
"""
License Token Generator for Connect OPL-1

This script generates JWT license tokens for Connect module instances.
The tokens are signed with RS256 algorithm using the private key.

Usage:
    python3 generate_license_token.py

Author: Oduist
"""

import jwt
import json
from datetime import datetime, timedelta

# Private key for signing tokens (keep this secure!)
PRIVATE_KEY = """-----BEGIN PRIVATE KEY-----
MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQCmCFuUGRYdziwb
FNwpG9uxKzvRn1MxwY1lUmFls8Hr9YpEQGt804mPPTql9p7yIyTwtKdiUYtwrDqV
W62kFx4UgyJ+ZhAlGaAVs2pnYz4TDyZ7yjqAXaTaDCE1PrKjxq+raIV31wL8ttv6
nszcuSe9XP9FccnhBG9L7FvN9KzIT0TUKli6zwxxxqm4TcmriDp1ZZTk+TtsLmMk
3dyltx9zavb1aOHd0bDjm3HnghDuTPnrPi4c9BnpQpplkMuEXFirn2sTeutiLWbh
hkizfoQ9eyPR2KPf3Uo20yZRn+pI2pggjp6msqIeNk1WkA1vZ57fbElOrZ8g9K/D
iogs6f+fAgMBAAECggEAEWUyGxZ0b75TIVSSgH1vtg8+iYbffjNg2hXDKJb9y/gC
JYZ4/IS5QS2mwGP8tofMw1SvbiihqwtlvpJIDgzHVQTW5Kv9fbWX784daXmcs6h/
CAc3ETiTy1iWqMUfOEjad4364IRsHAgYjMMohD5N6z7GwVgw+4dYayRMtguwMp2Y
DrHb+Z9M6SunUjY6Pxd0dEqJAEBgdwkjRhP09fAewAf5AAnELiTRBjwCHsAPdAoV
OGqJsQJ8DKFyCRoC86vPGIUJHFP27U/UPEG30gOvqQGmAHx0rktBxdbRzXL6/6Oy
MBtM7RxzoLdqwXkU+I8wdZljBKv6P1EpP2Y+VeCG8QKBgQDlU75uViNyShre6wmB
HJC7W96DnZB7WdxuJBFYY4MF5lT2I1UIG6MyZgfQL5P5dOgzjwSJu+/EQOb6hGDI
vpqxz+zrgj9wB5q6PlsigU92k9L/ASEX+TP1cUAurcEBN9uLnpSSUv71FLu4p7ib
sZ/X9ppPgRu1u3fPX5o3HAMhJwKBgQC5WAJtrMQdX/XX7jrIsIISIUIR6IV4Ew5G
tTEq+AgOD+xxik2oE1j9qYUnDYN0JP0t9uxAEPm05mEEqTk0lRxPCyqgbN2nrGTo
Q0Cr143NcocvXImR41ukfhE/PTAiWQoEQCdFiqS4/H14pmWQeegAZVcHjvJN/QeJ
gv1puw5IyQKBgQDQ1tya2nLZR8cEroIvQ/ZByT3wGfNTgdgNrWbmWWkeXE2PAUoU
YibSZLxEyK83A1HacimtzKpizMAL77W72mhB+ZpGNozS1vn/FX4lBCF7WM9TTpH2
pQi+Qe4zFCSpmVaj5TxjrJVmVwVE+ehSUQXBxF9ue6LicuB+xw9HlIj9DQKBgH7r
3OXcDISNJR5UXl72OGxP6B25XEToz7rt85iYN3PhxanO6vTxIty6TJt8rotHlTT3
xbrtpQITTVbSx4DRp4wdenhXdMaQ0J0ZCN1khA+voRF2ziJgTm5rgkYLEb5DuQ9G
G16M3dZr2URYtm5kfNJgk2NyqU1su8+YKw9PcC25AoGBAM9cKUb9FnpKRZaK5e6G
Y3ZSKYQOkXGaGX+lkPivUodrWJOBW+Sjk2moQVR4Le3csdbrYxokG4w8rUCjXl2r
Nnef0FGy9k6m7kWXJGIhznROoCw14SWy9fUb+zFuYNA2C5zJnMIzZXNh79BzaJ5G
LMxcrbPKXV/ZXwyQQXoYE5Rp
-----END PRIVATE KEY-----"""


def print_banner():
    """Print script banner."""
    print("=" * 60)
    print("Connect OPL-1 License Token Generator")
    print("=" * 60)
    print()


def get_input(prompt, default=None):
    """Get user input with optional default value."""
    if default:
        prompt = f"{prompt} [{default}]"
    value = input(f"{prompt}: ").strip()
    return value if value else default


def get_modules():
    """Get list of modules from user."""
    print("\nEnter modules (comma-separated):")
    print("Available: connect, connect_crm, connect_byoc, connect_elevenlabs, connect_helpdesk")
    modules_str = input("Modules: ").strip()
    return [m.strip() for m in modules_str.split(',') if m.strip()]


def get_expiration_date():
    """Get expiration date from user."""
    print("\nExpiration date:")
    print("1. 1 year from now")
    print("2. 2 years from now")
    print("3. Custom date (YYYY-MM-DD)")
    print("4. Never (no expiration)")

    choice = input("Choose option [1]: ").strip() or "1"

    if choice == "1":
        return int((datetime.now() + timedelta(days=365)).timestamp())
    elif choice == "2":
        return int((datetime.now() + timedelta(days=730)).timestamp())
    elif choice == "3":
        date_str = input("Enter date (YYYY-MM-DD): ").strip()
        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
            return int(date_obj.timestamp())
        except ValueError:
            print("Invalid date format. Using 1 year from now.")
            return int((datetime.now() + timedelta(days=365)).timestamp())
    elif choice == "4":
        # Set expiration to year 2100
        return int(datetime(2100, 1, 1).timestamp())
    else:
        print("Invalid choice. Using 1 year from now.")
        return int((datetime.now() + timedelta(days=365)).timestamp())


def generate_token():
    """Generate license token interactively."""
    print_banner()

    # Collect license information
    instance_uid = get_input("Instance UID (database UUID)", "")
    if not instance_uid:
        print("Error: Instance UID is required!")
        return None

    license_type = get_input("License type (production/trial/development)", "production")
    modules = get_modules()

    if not modules:
        print("Error: At least one module is required!")
        return None

    partner_id = get_input("Partner ID", "1")
    partner_name = get_input("Partner Name", "Customer")
    expire_timestamp = get_expiration_date()

    # Create payload
    payload = {
        "issuer": "oduist.com",
        "instance_uid": instance_uid,
        "type": license_type,
        "expire": expire_timestamp,
        "modules": modules,
        "partner_id": partner_id,
        "partner_name": partner_name
    }

    # Display payload
    print("\n" + "=" * 60)
    print("License Token Payload:")
    print("=" * 60)
    print(json.dumps(payload, indent=2))
    print()

    # Confirm
    confirm = input("Generate token with this payload? (y/n) [y]: ").strip().lower()
    if confirm and confirm != 'y':
        print("Token generation cancelled.")
        return None

    # Generate token
    try:
        token = jwt.encode(payload, PRIVATE_KEY, algorithm='RS256')
        return token
    except Exception as e:
        print(f"Error generating token: {e}")
        return None


def main():
    """Main function."""
    token = generate_token()

    if token:
        print("\n" + "=" * 60)
        print("SUCCESS! Your license token:")
        print("=" * 60)
        print(token)
        print("=" * 60)
        print("\nCopy this token and paste it into Connect Settings -> API Keys -> License Token")
        print()

        # Save to file
        save = input("Save token to file? (y/n) [y]: ").strip().lower()
        if not save or save == 'y':
            filename = input("Filename [license_token.txt]: ").strip() or "license_token.txt"
            try:
                with open(filename, 'w') as f:
                    f.write(token)
                print(f"Token saved to {filename}")
            except Exception as e:
                print(f"Error saving file: {e}")


if __name__ == "__main__":
    main()
