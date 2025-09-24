#!/usr/bin/env python3
"""
MyCliApp - A simple CLI application similar to Azure CLI -
"""

import click
import sys
import os
import json
import base64
import platform
from pathlib import Path
from colorama import init, Fore, Style

# Initialize colorama for Windows terminal color support
init()

# Azure authentication imports
try:
    from azure.identity import (
        InteractiveBrowserCredential,
        AzureCliCredential,
        DefaultAzureCredential,
        SharedTokenCacheCredential,
        DeviceCodeCredential,
    )
    from azure.core.exceptions import ClientAuthenticationError
    import msal

    AZURE_AVAILABLE = True
except ImportError:
    AZURE_AVAILABLE = False

__version__ = "1.0.0"

# Configuration file path
CONFIG_DIR = Path.home() / ".mycli"
CONFIG_FILE = CONFIG_DIR / "config.json"

# Authentication state
_auth_state = {
    "is_authenticated": False,
    "user_info": None,
    "tenant_id": None,
    "credential": None,
    "auth_method": None,  # "browser", "device_code", "broker", "cli"
    "broker_info": None,
}


def ensure_config_dir():
    """Ensure the config directory exists."""
    CONFIG_DIR.mkdir(exist_ok=True)


def load_auth_state():
    """Load authentication state from config file."""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
                _auth_state.update(data.get("auth", {}))
        except (json.JSONDecodeError, IOError):
            pass


def save_auth_state():
    """Save authentication state to config file."""
    ensure_config_dir()
    try:
        config_data = {}
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, "r") as f:
                config_data = json.load(f)

        # Only save serializable data
        config_data["auth"] = {
            "is_authenticated": _auth_state["is_authenticated"],
            "user_info": _auth_state["user_info"],
            "tenant_id": _auth_state["tenant_id"],
            "auth_method": _auth_state.get("auth_method"),
            "broker_info": _auth_state.get("broker_info"),
        }

        with open(CONFIG_FILE, "w") as f:
            json.dump(config_data, f, indent=2)
    except IOError:
        pass


def clear_broker_cache():
    """Clear broker-specific cache."""
    try:
        # Create app instance to access broker cache based on platform
        if os.name == "nt":  # Windows
            app = msal.PublicClientApplication(
                client_id="04b07795-8ddb-461a-bbee-02f9e1bf7b46",  # Azure CLI client ID
                authority="https://login.microsoftonline.com/common",
                enable_broker_on_windows=True,
            )
        elif platform.system() == "Darwin":  # macOS
            app = msal.PublicClientApplication(
                client_id="04b07795-8ddb-461a-bbee-02f9e1bf7b46",  # Azure CLI client ID
                authority="https://login.microsoftonline.com/common",
                enable_broker_on_mac=True,
            )
        else:
            # For other platforms, create without broker support
            app = msal.PublicClientApplication(
                client_id="04b07795-8ddb-461a-bbee-02f9e1bf7b46",  # Azure CLI client ID
                authority="https://login.microsoftonline.com/common",
            )

        # Get all accounts and remove them
        accounts = app.get_accounts()
        for account in accounts:
            app.remove_account(account)
            click.echo(f"Removed broker account: {account.get('username', 'unknown')}")

        # Also clear the token cache
        if hasattr(app.token_cache, "serialize"):
            app.token_cache.serialize()

        return len(accounts)
    except Exception as e:
        click.echo(f"Error clearing broker cache: {e}")
        return 0


def get_native_broker_credential(tenant_id=None):
    """Get a native broker credential using MSAL directly."""
    try:
        import msal

        # Use MSAL directly for better broker control
        tenant_id = tenant_id or "common"
        authority = f"https://login.microsoftonline.com/{tenant_id}"

        # Create a public client application with broker support
        app = msal.PublicClientApplication(
            client_id="04b07795-8ddb-461a-bbee-02f9e1bf7b46",  # Azure CLI client ID
            authority=authority,
            enable_broker_on_windows=True,
        )

        # First try to get accounts from cache
        accounts = app.get_accounts()

        if accounts:
            click.echo(
                f"{Fore.YELLOW}⚠️  Found {len(accounts)} cached account(s) - this might skip the popup{Style.RESET_ALL}"
            )
            # Try silent authentication first
            result = app.acquire_token_silent(scopes=["https://management.azure.com/.default"], account=accounts[0])
            if result and "access_token" in result:
                click.echo(f"{Fore.YELLOW}✓ Used cached broker credentials - no popup needed{Style.RESET_ALL}")
                return result, "broker_cached"

        # Try interactive broker authentication
        click.echo(f"{Fore.BLUE}🚨 Starting INTERACTIVE broker authentication - popup should appear{Style.RESET_ALL}")
        result = app.acquire_token_interactive(
            scopes=["https://management.azure.com/.default"],
            parent_window_handle=app.CONSOLE_WINDOW_HANDLE,  # Use console window handle for CLI apps
            enable_broker=True,
            prompt="select_account",  # Force account selection
            login_hint=None,  # Don't hint any specific account
        )

        if result and "access_token" in result:
            click.echo(f"{Fore.GREEN}✓ Interactive broker authentication completed{Style.RESET_ALL}")
            return result, "broker_interactive"
        else:
            error = result.get("error_description", "Unknown error")
            click.echo(f"{Fore.RED}Broker authentication failed: {error}{Style.RESET_ALL}")
            return None, None

    except Exception as e:
        error_msg = str(e)
        if "msal[broker]" in error_msg:
            click.echo(
                f'{Fore.YELLOW}💡 For native broker support, install: pip install "msal[broker]>=1.20,<2"{Style.RESET_ALL}'
            )
        else:
            click.echo(f"{Fore.RED}Native broker authentication error: {error_msg}{Style.RESET_ALL}")
        return None, None


def get_macos_broker_credential(tenant_id=None):
    """Get a native broker credential for macOS using MSAL directly."""
    try:
        import msal

        # Use MSAL directly for better broker control on macOS
        tenant_id = tenant_id or "common"
        authority = f"https://login.microsoftonline.com/{tenant_id}"

        # Create a public client application with broker support for macOS
        app = msal.PublicClientApplication(
            client_id="04b07795-8ddb-461a-bbee-02f9e1bf7b46",  # Azure CLI client ID
            authority=authority,
            enable_broker_on_mac=True,  # Enable broker support on macOS
        )

        # First try to get accounts from cache
        accounts = app.get_accounts()

        if accounts:
            click.echo(
                f"{Fore.YELLOW}⚠️  Found {len(accounts)} cached account(s) - this might skip the popup{Style.RESET_ALL}"
            )
            # Try silent authentication first
            result = app.acquire_token_silent(scopes=["https://management.azure.com/.default"], account=accounts[0])
            if result and "access_token" in result:
                click.echo(f"{Fore.YELLOW}✓ Used cached broker credentials - no popup needed{Style.RESET_ALL}")
                return result, "broker_cached"

        # Try interactive broker authentication for macOS
        click.echo(f"{Fore.BLUE}🚨 Starting INTERACTIVE broker authentication - popup should appear{Style.RESET_ALL}")
        click.echo(f"{Fore.BLUE}💡 Look for authentication prompt in macOS or Authenticator app{Style.RESET_ALL}")

        # Try different approaches for macOS broker authentication
        try:
            # First try with console window handle
            result = app.acquire_token_interactive(
                scopes=["https://management.azure.com/.default"],
                parent_window_handle=app.CONSOLE_WINDOW_HANDLE,  # Use console window handle for CLI apps
                enable_broker=True,
                prompt="select_account",  # Force account selection
                login_hint=None,  # Don't hint any specific account
            )
        except Exception as console_error:
            # If console window handle fails, try without it
            click.echo(
                f"{Fore.YELLOW}⚠️  Console window handle not supported, trying alternative method...{Style.RESET_ALL}"
            )
            try:
                result = app.acquire_token_interactive(
                    scopes=["https://management.azure.com/.default"],
                    enable_broker=True,
                    prompt="select_account",  # Force account selection
                    login_hint=None,  # Don't hint any specific account
                )
            except Exception as broker_error:
                # If broker fails, try without broker for this specific case
                click.echo(
                    f"{Fore.YELLOW}⚠️  Native broker failed, trying interactive without broker...{Style.RESET_ALL}"
                )
                result = app.acquire_token_interactive(
                    scopes=["https://management.azure.com/.default"],
                    prompt="select_account",  # Force account selection
                    login_hint=None,  # Don't hint any specific account
                )
                # If this works, update the auth method to indicate it's not true broker
                if result and "access_token" in result:
                    click.echo(
                        f"{Fore.YELLOW}✓ Interactive authentication completed (browser fallback){Style.RESET_ALL}"
                    )
                    return result, "browser_interactive"

        if result and "access_token" in result:
            click.echo(f"{Fore.GREEN}✓ Interactive broker authentication completed{Style.RESET_ALL}")
            return result, "broker_interactive"
        else:
            error = result.get("error_description", "Unknown error")
            click.echo(f"{Fore.RED}Broker authentication failed: {error}{Style.RESET_ALL}")
            return None, None

    except Exception as e:
        error_msg = str(e)
        if "msal[broker]" in error_msg:
            click.echo(
                f'{Fore.YELLOW}💡 For native broker support on macOS, install: pip install "msal[broker]>=1.20,<2"{Style.RESET_ALL}'
            )
        elif "Company Portal" in error_msg:
            click.echo(
                f"{Fore.YELLOW}💡 For full broker features, install Microsoft Company Portal from the App Store{Style.RESET_ALL}"
            )
        elif "parent_window_handle is required" in error_msg:
            click.echo(f"{Fore.RED}Console window handle error: {error_msg}{Style.RESET_ALL}")
            click.echo(
                f"{Fore.YELLOW}💡 This is a known issue with MSAL broker on some macOS versions{Style.RESET_ALL}"
            )
            click.echo(f"{Fore.YELLOW}💡 Try using: mycli login --use-device-code{Style.RESET_ALL}")
        elif "broker" in error_msg.lower():
            click.echo(f"{Fore.RED}Broker authentication error: {error_msg}{Style.RESET_ALL}")
            click.echo(
                f"{Fore.YELLOW}💡 Ensure Microsoft Company Portal is installed from the App Store{Style.RESET_ALL}"
            )
            click.echo(f"{Fore.YELLOW}💡 Ensure Touch ID is enabled in System Preferences{Style.RESET_ALL}")
        else:
            click.echo(f"{Fore.RED}Native broker authentication error: {error_msg}{Style.RESET_ALL}")
        return None, None


def get_azure_credential(tenant_id=None, use_broker=False, use_device_code=False):
    """Get Azure credential for authentication."""
    if not AZURE_AVAILABLE:
        return None, None

    auth_method = "unknown"
    try:
        if use_device_code:
            # Use device code flow
            auth_method = "device_code"
            credential = DeviceCodeCredential(tenant_id=tenant_id)
        elif use_broker:
            # Use broker-based authentication (Windows Hello, Authenticator app, etc.)
            auth_method = "broker"

            # Try native MSAL broker authentication on Windows
            if os.name == "nt":  # Windows
                broker_result, broker_method = get_native_broker_credential(tenant_id)
                if broker_result:
                    # Create a custom credential wrapper for MSAL result
                    from azure.core.credentials import AccessToken
                    import time

                    class MSALBrokerCredential:
                        def __init__(self, msal_result):
                            self.msal_result = msal_result

                        def get_token(self, *scopes, **kwargs):
                            expires_on = self.msal_result.get("expires_in", 3600)
                            expires_on = int(time.time()) + expires_on
                            return AccessToken(self.msal_result["access_token"], expires_on)

                    return MSALBrokerCredential(broker_result), broker_method

            # Try native MSAL broker authentication on macOS
            elif platform.system() == "Darwin":  # macOS
                broker_result, broker_method = get_macos_broker_credential(tenant_id)
                if broker_result:
                    # Create a custom credential wrapper for MSAL result
                    from azure.core.credentials import AccessToken
                    import time

                    class MSALBrokerCredential:
                        def __init__(self, msal_result):
                            self.msal_result = msal_result

                        def get_token(self, *scopes, **kwargs):
                            expires_on = self.msal_result.get("expires_in", 3600)
                            expires_on = int(time.time()) + expires_on
                            return AccessToken(self.msal_result["access_token"], expires_on)

                    return MSALBrokerCredential(broker_result), broker_method

            # Fallback: Try SharedTokenCacheCredential first for cached broker tokens
            try:
                credential = SharedTokenCacheCredential(tenant_id=tenant_id)
                # Test the credential
                token = credential.get_token("https://management.azure.com/.default")
                return credential, "broker_cache"
            except ClientAuthenticationError:
                # Fallback to interactive browser with broker support
                if os.name == "nt":  # Windows
                    credential = InteractiveBrowserCredential(tenant_id=tenant_id, enable_broker_on_windows=True)
                elif platform.system() == "Darwin":  # macOS
                    credential = InteractiveBrowserCredential(tenant_id=tenant_id, enable_broker_on_mac=True)
                else:
                    credential = InteractiveBrowserCredential(tenant_id=tenant_id)
                auth_method = "browser_with_broker"
        elif tenant_id:
            # Use interactive browser credential with specific tenant
            auth_method = "browser"
            credential = InteractiveBrowserCredential(tenant_id=tenant_id)
        else:
            # Try Azure CLI credential first, then fallback to interactive browser
            try:
                credential = AzureCliCredential()
                # Test the credential
                token = credential.get_token("https://management.azure.com/.default")
                auth_method = "cli"
                return credential, auth_method
            except ClientAuthenticationError:
                # Fallback to interactive browser credential
                auth_method = "browser"
                credential = InteractiveBrowserCredential()

        return credential, auth_method
    except Exception:
        return None, None


def get_broker_info():
    """Get information about available broker authentication methods."""
    broker_info = {
        "windows_hello_available": False,
        "authenticator_app_available": False,
        "keychain_available": False,
        "touch_id_available": False,
        "platform_support": False,
        "recommendations": [],
    }

    # Check if we're on Windows (primary platform for broker support)
    if os.name == "nt":
        broker_info["platform_support"] = True
        broker_info["recommendations"].append("Windows Hello for Business")
        broker_info["recommendations"].append("Microsoft Authenticator app")
        broker_info["windows_hello_available"] = True  # Assume available on Windows
        broker_info["authenticator_app_available"] = True  # Assume available
    elif platform.system() == "Darwin":  # macOS
        broker_info["platform_support"] = True
        broker_info["recommendations"].append("macOS Keychain")
        broker_info["recommendations"].append("Touch ID / Face ID")
        broker_info["recommendations"].append("Microsoft Authenticator app")
        broker_info["keychain_available"] = True  # Assume available on macOS
        broker_info["touch_id_available"] = True  # Assume available on modern Macs
        broker_info["authenticator_app_available"] = True  # Assume available
    else:
        broker_info["recommendations"].append("Use device code flow for other platforms")

    return broker_info


def authenticate_user_with_broker(tenant_id=None, use_device_code=False, force_broker=False):
    """Authenticate user using broker-based authentication."""
    if not AZURE_AVAILABLE:
        click.echo(f"{Fore.RED}Azure SDK not available. Install required packages:{Style.RESET_ALL}")
        click.echo("pip install azure-identity azure-mgmt-core azure-core msal")
        click.echo(f"{Fore.RED}❌ Authentication failed{Style.RESET_ALL}")
        return False

    try:
        # Get broker information
        broker_info = get_broker_info()

        if not broker_info["platform_support"] and not use_device_code:
            if force_broker:
                click.echo(
                    f"{Fore.RED}❌ Force broker specified but platform doesn't support native broker authentication{Style.RESET_ALL}"
                )
                return False
            click.echo(f"{Fore.YELLOW}Broker authentication is primarily supported on Windows.{Style.RESET_ALL}")
            click.echo(f"{Fore.YELLOW}Consider using device code flow with --use-device-code flag.{Style.RESET_ALL}")
            return False

        credential, auth_method = get_azure_credential(tenant_id, use_broker=True, use_device_code=use_device_code)
        if not credential:
            click.echo(f"{Fore.RED}Failed to create Azure credential{Style.RESET_ALL}")
            return False

        # Check if we got a fallback method when force_broker is specified
        if force_broker and auth_method in ["browser_with_broker", "browser", "browser_interactive"]:
            click.echo(
                f"{Fore.RED}❌ Force broker specified but only browser authentication is available{Style.RESET_ALL}"
            )
            if platform.system() == "Darwin":  # macOS
                click.echo(
                    f"{Fore.YELLOW}💡 Try setting up Touch ID/Face ID or Microsoft Authenticator{Style.RESET_ALL}"
                )
                click.echo(f"{Fore.YELLOW}💡 Install Microsoft Company Portal from the App Store{Style.RESET_ALL}")
            else:
                click.echo(f"{Fore.YELLOW}💡 Try setting up Windows Hello or Microsoft Authenticator{Style.RESET_ALL}")
            return False

        # Display authentication method info
        if auth_method in ["broker_cached", "broker_interactive"]:
            click.echo(f"{Fore.BLUE}🔐 Authenticating with Azure using native broker...{Style.RESET_ALL}")
            if broker_info["windows_hello_available"]:
                click.echo(f"{Fore.GREEN}✓ Windows Hello available{Style.RESET_ALL}")
            if broker_info["keychain_available"]:
                click.echo(f"{Fore.GREEN}✓ macOS Keychain available{Style.RESET_ALL}")
            if broker_info["touch_id_available"]:
                click.echo(f"{Fore.GREEN}✓ Touch ID/Face ID available{Style.RESET_ALL}")
            if broker_info["authenticator_app_available"]:
                click.echo(f"{Fore.GREEN}✓ Microsoft Authenticator support available{Style.RESET_ALL}")
            if auth_method == "broker_cached":
                click.echo(f"{Fore.GREEN}✓ Using cached broker credentials{Style.RESET_ALL}")
            else:
                if platform.system() == "Darwin":
                    click.echo(
                        f"{Fore.BLUE}💡 Look for authentication prompt in macOS or Authenticator app{Style.RESET_ALL}"
                    )
                else:
                    click.echo(f"{Fore.BLUE}💡 Look for authentication prompt in Windows Security{Style.RESET_ALL}")
        elif auth_method == "broker_cache":
            click.echo(f"{Fore.BLUE}🔐 Authenticating with Azure using cached broker tokens...{Style.RESET_ALL}")
        elif auth_method == "browser_with_broker":
            click.echo(f"{Fore.BLUE}🔐 Authenticating with Azure using browser (broker fallback)...{Style.RESET_ALL}")
            click.echo(
                f"{Fore.YELLOW}💡 Native broker authentication not available, using browser fallback{Style.RESET_ALL}"
            )
        elif auth_method == "device_code":
            click.echo(f"{Fore.BLUE}🔐 Authenticating with Azure using device code...{Style.RESET_ALL}")
        else:
            click.echo(f"{Fore.BLUE}🔐 Authenticating with Azure using {auth_method}...{Style.RESET_ALL}")

        # Perform authentication
        if hasattr(credential, "__class__"):
            click.echo(f"{Fore.BLUE}Credential Type: {credential.__class__.__name__}{Style.RESET_ALL}")

        token = credential.get_token("https://management.azure.com/.default")

        if token:
            _auth_state["is_authenticated"] = True
            _auth_state["credential"] = credential
            _auth_state["tenant_id"] = tenant_id
            _auth_state["auth_method"] = auth_method
            _auth_state["broker_info"] = broker_info

            # Extract user information from the token
            user_info = parse_jwt_token(token.token)
            if user_info:
                _auth_state["user_info"] = user_info
                # Update tenant_id from token if not provided
                if not tenant_id and user_info.get("tenant_id"):
                    _auth_state["tenant_id"] = user_info["tenant_id"]
            else:
                # Fallback to generic info if token parsing fails
                _auth_state["user_info"] = {
                    "user_id": "authenticated_user@domain.com",
                    "display_name": "Authenticated User",
                }

            save_auth_state()
            return True

    except ClientAuthenticationError as e:
        click.echo(f"{Fore.RED}Authentication failed: {str(e)}{Style.RESET_ALL}")
        if "broker" in str(e).lower():
            click.echo(
                f"{Fore.YELLOW}💡 Tip: Ensure Windows Hello or Microsoft Authenticator is set up{Style.RESET_ALL}"
            )
    except Exception as e:
        click.echo(f"{Fore.RED}Unexpected error during authentication: {str(e)}{Style.RESET_ALL}")

    return False


def authenticate_user(tenant_id=None, use_broker=False, use_device_code=False, force_broker=False):
    """Authenticate user with Azure."""
    if use_broker or force_broker or use_device_code:
        return authenticate_user_with_broker(tenant_id, use_device_code, force_broker)

    if not AZURE_AVAILABLE:
        click.echo(f"{Fore.RED}Azure SDK not available. Install required packages:{Style.RESET_ALL}")
        click.echo("pip install azure-identity azure-mgmt-core azure-core msal")
        click.echo(f"{Fore.RED}❌ Authentication failed{Style.RESET_ALL}")
        return False

    try:
        credential, auth_method = get_azure_credential(tenant_id)
        if not credential:
            click.echo(f"{Fore.RED}Failed to create Azure credential{Style.RESET_ALL}")
            return False

        # Test authentication by getting a token
        click.echo(f"{Fore.BLUE}🔐 Authenticating with Azure...{Style.RESET_ALL}")

        # This will trigger browser authentication if needed
        if isinstance(credential, InteractiveBrowserCredential):
            click.echo(f"{Fore.YELLOW}Opening browser for authentication...{Style.RESET_ALL}")
        elif hasattr(credential, "__class__"):
            click.echo(f"{Fore.BLUE}Using {credential.__class__.__name__}...{Style.RESET_ALL}")

        token = credential.get_token("https://management.azure.com/.default")

        if token:
            _auth_state["is_authenticated"] = True
            _auth_state["credential"] = credential
            _auth_state["tenant_id"] = tenant_id
            _auth_state["auth_method"] = auth_method

            # Extract real user information from the token
            user_info = parse_jwt_token(token.token)
            if user_info:
                _auth_state["user_info"] = user_info
                # Update tenant_id from token if not provided
                if not tenant_id and user_info.get("tenant_id"):
                    _auth_state["tenant_id"] = user_info["tenant_id"]
            else:
                # Fallback to generic info if token parsing fails
                _auth_state["user_info"] = {
                    "user_id": "authenticated_user@domain.com",
                    "display_name": "Authenticated User",
                }

            save_auth_state()
            return True

    except ClientAuthenticationError as e:
        click.echo(f"{Fore.RED}Authentication failed: {str(e)}{Style.RESET_ALL}")
    except Exception as e:
        click.echo(f"{Fore.RED}Unexpected error during authentication: {str(e)}{Style.RESET_ALL}")

    return False


def is_authenticated():
    """Check if user is currently authenticated."""
    return _auth_state.get("is_authenticated", False)


def clear_auth_state():
    """Clear authentication state."""
    _auth_state.update(
        {
            "is_authenticated": False,
            "user_info": None,
            "tenant_id": None,
            "credential": None,
            "auth_method": None,
            "broker_info": None,
        }
    )
    save_auth_state()


def parse_jwt_token(token_string):
    """Parse JWT token to extract user information."""
    try:
        # JWT tokens have 3 parts separated by dots: header.payload.signature
        parts = token_string.split(".")
        if len(parts) != 3:
            return None

        # Decode the payload (middle part)
        payload = parts[1]
        # Add padding if needed for base64 decoding
        payload += "=" * (4 - len(payload) % 4)

        # Decode base64
        decoded_bytes = base64.urlsafe_b64decode(payload)
        payload_json = json.loads(decoded_bytes)

        # Extract user information
        user_info = {}

        # Common claims in Azure AD tokens
        if "upn" in payload_json:  # User Principal Name
            user_info["user_id"] = payload_json["upn"]
        elif "unique_name" in payload_json:
            user_info["user_id"] = payload_json["unique_name"]
        elif "email" in payload_json:
            user_info["user_id"] = payload_json["email"]
        else:
            user_info["user_id"] = payload_json.get("sub", "unknown")

        # Display name
        user_info["display_name"] = payload_json.get("name", user_info["user_id"])

        # Tenant information
        user_info["tenant_id"] = payload_json.get("tid")
        user_info["tenant_name"] = payload_json.get("tenant_name")

        # Additional info
        user_info["object_id"] = payload_json.get("oid")
        user_info["roles"] = payload_json.get("roles", [])

        return user_info

    except Exception as e:
        click.echo(f"{Fore.YELLOW}Warning: Could not parse token for user info: {e}{Style.RESET_ALL}")
        return None


# Load auth state on startup
load_auth_state()


@click.group(invoke_without_command=True)
@click.option("--version", "-v", is_flag=True, help="Show version information")
@click.pass_context
def cli(ctx, version):
    """MyCliApp - A simple CLI application with dummy commands."""
    if version:
        click.echo(f"MyCliApp version {__version__}")
        return

    if ctx.invoked_subcommand is None:
        click.echo("Welcome to MyCliApp!")
        click.echo("Use 'mycli --help' to see available commands.")


@cli.group()
def resource():
    """Manage resources (dummy commands)."""
    pass


@resource.command()
@click.option("--name", "-n", required=True, help="Name of the resource")
@click.option("--location", "-l", default="eastus", help="Location for the resource")
@click.option(
    "--type",
    "-t",
    default="vm",
    type=click.Choice(["vm", "storage", "database"], case_sensitive=False),
    help="Type of resource to create",
)
def create(name, location, type):
    """Create a new resource."""
    click.echo(f"{Fore.GREEN}✓{Style.RESET_ALL} Creating {type} resource...")
    click.echo(f"  Name: {Fore.CYAN}{name}{Style.RESET_ALL}")
    click.echo(f"  Location: {Fore.CYAN}{location}{Style.RESET_ALL}")
    click.echo(f"  Type: {Fore.CYAN}{type}{Style.RESET_ALL}")
    click.echo(f"{Fore.GREEN}✓{Style.RESET_ALL} Resource '{name}' created successfully!")


@resource.command()
@click.option("--location", "-l", help="Filter by location")
@click.option("--type", "-t", help="Filter by resource type")
def list(location, type):
    """List all resources."""
    click.echo(f"{Fore.YELLOW}📋{Style.RESET_ALL} Listing resources...")

    # Dummy data
    resources = [
        {"name": "myvm-001", "type": "vm", "location": "eastus", "status": "running"},
        {"name": "mystorage-001", "type": "storage", "location": "westus", "status": "active"},
        {"name": "mydb-001", "type": "database", "location": "eastus", "status": "running"},
    ]

    # Apply filters
    filtered_resources = resources
    if location:
        filtered_resources = [r for r in filtered_resources if r["location"] == location]
    if type:
        filtered_resources = [r for r in filtered_resources if r["type"] == type]

    if not filtered_resources:
        click.echo(f"{Fore.YELLOW}No resources found matching the criteria.{Style.RESET_ALL}")
        return

    # Display table header
    click.echo(f"\n{Fore.BLUE}{'Name':<15} {'Type':<10} {'Location':<10} {'Status':<10}{Style.RESET_ALL}")
    click.echo("-" * 50)

    # Display resources
    for resource in filtered_resources:
        status_color = Fore.GREEN if resource["status"] == "running" or resource["status"] == "active" else Fore.RED
        click.echo(
            f"{resource['name']:<15} {resource['type']:<10} {resource['location']:<10} {status_color}{resource['status']:<10}{Style.RESET_ALL}"
        )


@resource.command()
@click.argument("name")
@click.confirmation_option(prompt="Are you sure you want to delete this resource?")
def delete(name):
    """Delete a resource."""
    click.echo(f"{Fore.RED}🗑️{Style.RESET_ALL}  Deleting resource '{name}'...")
    click.echo(f"{Fore.GREEN}✓{Style.RESET_ALL} Resource '{name}' deleted successfully!")


@cli.group()
def config():
    """Manage configuration settings."""
    pass


@config.command()
@click.option("--key", "-k", required=True, help="Configuration key")
@click.option("--value", "-v", required=True, help="Configuration value")
def set(key, value):
    """Set a configuration value."""
    click.echo(f"{Fore.GREEN}✓{Style.RESET_ALL} Configuration set:")
    click.echo(f"  {key} = {Fore.CYAN}{value}{Style.RESET_ALL}")


@config.command()
@click.option("--key", "-k", help="Specific configuration key to show")
def show(key):
    """Show configuration values."""
    # Dummy configuration data
    config_data = {"default_location": "eastus", "output_format": "table", "subscription": "my-subscription-123"}

    if key:
        if key in config_data:
            click.echo(f"{key}: {Fore.CYAN}{config_data[key]}{Style.RESET_ALL}")
        else:
            click.echo(f"{Fore.RED}Configuration key '{key}' not found.{Style.RESET_ALL}")
    else:
        click.echo(f"{Fore.BLUE}Current configuration:{Style.RESET_ALL}")
        for k, v in config_data.items():
            click.echo(f"  {k}: {Fore.CYAN}{v}{Style.RESET_ALL}")


@cli.command()
@click.option("--tenant", "-t", help="Tenant ID to authenticate with")
@click.option("--use-device-code", is_flag=True, help="Use device code flow instead of browser")
@click.option("--use-broker", is_flag=True, help="Use broker-based authentication (Windows Hello, Authenticator)")
@click.option("--force-broker", is_flag=True, help="Force native broker authentication, fail if not available")
@click.option("--demo", is_flag=True, hidden=True, help="Demo mode (for testing)")
def login(tenant, use_device_code, use_broker, force_broker, demo):
    """Authenticate with Azure."""
    if is_authenticated():
        click.echo(f"{Fore.YELLOW}Already authenticated. Use 'logout' to sign out first.{Style.RESET_ALL}")
        return

    click.echo(f"{Fore.BLUE}🔐 Starting Azure authentication...{Style.RESET_ALL}")

    if tenant:
        click.echo(f"  Tenant: {Fore.CYAN}{tenant}{Style.RESET_ALL}")

    if use_broker or force_broker:
        click.echo(f"{Fore.BLUE}  Method: {Fore.CYAN}Broker-based authentication{Style.RESET_ALL}")
        broker_info = get_broker_info()
        if broker_info["platform_support"]:
            click.echo(f"  Available: {Fore.GREEN}{', '.join(broker_info['recommendations'])}{Style.RESET_ALL}")
        else:
            click.echo(f"{Fore.YELLOW}  Warning: Limited broker support on this platform{Style.RESET_ALL}")
            if force_broker:
                click.echo(
                    f"{Fore.RED}❌ Force broker specified but platform doesn't support native broker authentication{Style.RESET_ALL}"
                )
                sys.exit(1)

    if use_device_code:
        click.echo(f"{Fore.BLUE}  Method: {Fore.CYAN}Device Code Flow{Style.RESET_ALL}")

    # Demo mode for testing without actual Azure login
    if demo:
        click.echo(f"{Fore.YELLOW}[DEMO MODE] Simulating Azure authentication...{Style.RESET_ALL}")
        _auth_state["is_authenticated"] = True
        _auth_state["user_info"] = {"user_id": "demo.user@contoso.com", "display_name": "Demo User"}
        _auth_state["tenant_id"] = tenant or "demo-tenant-id"
        _auth_state["auth_method"] = "demo"
        save_auth_state()
        click.echo(f"{Fore.GREEN}✓ Successfully authenticated! (Demo Mode){Style.RESET_ALL}")
        click.echo(f"  User: {Fore.CYAN}demo.user@contoso.com{Style.RESET_ALL}")
        return

    # Determine actual authentication method to use
    final_use_broker = use_broker or force_broker

    if authenticate_user(tenant, final_use_broker, use_device_code, force_broker):
        user_info = _auth_state.get("user_info", {})
        auth_method = _auth_state.get("auth_method", "unknown")
        click.echo(f"{Fore.GREEN}✓ Successfully authenticated!{Style.RESET_ALL}")
        click.echo(f"  User: {Fore.CYAN}{user_info.get('user_id', 'unknown')}{Style.RESET_ALL}")
        click.echo(f"  Method: {Fore.CYAN}{auth_method}{Style.RESET_ALL}")
        if tenant:
            click.echo(f"  Tenant: {Fore.CYAN}{tenant}{Style.RESET_ALL}")
    else:
        click.echo(f"{Fore.RED}❌ Authentication failed{Style.RESET_ALL}")
        if not AZURE_AVAILABLE:
            click.echo(f"{Fore.YELLOW}💡 Tip: Install Azure packages with:{Style.RESET_ALL}")
            click.echo("    pip install azure-identity azure-mgmt-core azure-core msal")
        elif use_broker or force_broker:
            click.echo(f"{Fore.YELLOW}💡 Broker authentication tips:{Style.RESET_ALL}")
            if os.name == "nt":  # Windows
                click.echo("    - Ensure Windows Hello is set up")
                click.echo("    - Ensure Microsoft Authenticator is installed and configured")
                click.echo("    - Try running as administrator if issues persist")
            elif platform.system() == "Darwin":  # macOS
                click.echo("    - Ensure Touch ID is enabled in System Preferences")
                click.echo("    - Install Microsoft Company Portal from the App Store")
                click.echo("    - Ensure Microsoft Authenticator is installed and configured")
                click.echo("    - Check keychain access permissions")
            else:
                click.echo("    - Consider using device code flow on this platform")
            click.echo("    - Use 'mycli broker' to check broker capabilities")

        # Exit with error code when authentication fails
        sys.exit(1)


@cli.command()
def logout():
    """Logout from Azure authentication."""
    if not is_authenticated():
        click.echo(f"{Fore.YELLOW}Not currently authenticated.{Style.RESET_ALL}")
        return

    click.echo(f"{Fore.YELLOW}👋 Logging out...{Style.RESET_ALL}")
    clear_auth_state()
    click.echo(f"{Fore.GREEN}✓ Successfully logged out!{Style.RESET_ALL}")
    click.echo(f"{Fore.BLUE}💡 Note: You may need to clear your browser cache for complete logout.{Style.RESET_ALL}")


@cli.command()
def whoami():
    """Show current authenticated user information."""
    if not is_authenticated():
        click.echo(f"{Fore.RED}Not authenticated. Use 'mycli login' to sign in.{Style.RESET_ALL}")
        return

    user_info = _auth_state.get("user_info", {})
    tenant_id = _auth_state.get("tenant_id")
    auth_method = _auth_state.get("auth_method", "unknown")
    broker_info = _auth_state.get("broker_info")

    click.echo(f"{Fore.BLUE}Current Authentication:{Style.RESET_ALL}")
    click.echo(f"  User: {Fore.CYAN}{user_info.get('user_id', 'unknown')}{Style.RESET_ALL}")
    click.echo(f"  Display Name: {Fore.CYAN}{user_info.get('display_name', 'unknown')}{Style.RESET_ALL}")
    click.echo(f"  Tenant: {Fore.CYAN}{tenant_id or 'common'}{Style.RESET_ALL}")

    click.echo(f"  Auth Method: {Fore.CYAN}{auth_method}{Style.RESET_ALL}")
    click.echo(f"  Status: {Fore.GREEN}Authenticated{Style.RESET_ALL}")

    if broker_info and auth_method == "broker":
        click.echo(f"\n{Fore.BLUE}Broker Information:{Style.RESET_ALL}")
        click.echo(
            f"  Platform Support: {Fore.GREEN if broker_info.get('platform_support') else Fore.RED}{'Yes' if broker_info.get('platform_support') else 'No'}{Style.RESET_ALL}"
        )
        if broker_info.get("recommendations"):
            click.echo(f"  Available Methods: {Fore.CYAN}{', '.join(broker_info['recommendations'])}{Style.RESET_ALL}")

    click.echo(
        f"\n{Fore.BLUE}Azure SDK: {Fore.GREEN if AZURE_AVAILABLE else Fore.RED}{'Available' if AZURE_AVAILABLE else 'Not Available'}{Style.RESET_ALL}"
    )


@cli.command()
def broker():
    """Show broker authentication capabilities and information."""
    click.echo(f"{Fore.BLUE}🔐 Broker Authentication Information:{Style.RESET_ALL}")

    broker_info = get_broker_info()

    # Platform support
    click.echo(f"\n{Fore.BLUE}Platform Support:{Style.RESET_ALL}")
    click.echo(f"  Operating System: {Fore.CYAN}{os.name}{Style.RESET_ALL}")
    platform_color = Fore.GREEN if broker_info["platform_support"] else Fore.RED
    click.echo(
        f"  Broker Support: {platform_color}{'Available' if broker_info['platform_support'] else 'Limited'}{Style.RESET_ALL}"
    )

    # Available methods
    if broker_info.get("recommendations"):
        click.echo(f"\n{Fore.BLUE}Available Authentication Methods:{Style.RESET_ALL}")
        for method in broker_info["recommendations"]:
            click.echo(f"  • {Fore.GREEN}{method}{Style.RESET_ALL}")

    # Windows Hello status
    if broker_info.get("windows_hello_available"):
        click.echo(f"\n{Fore.BLUE}Windows Hello:{Style.RESET_ALL}")
        click.echo(f"  Status: {Fore.GREEN}Available{Style.RESET_ALL}")
        click.echo("  Benefits: Biometric authentication, PIN-based auth")

    # macOS Keychain and Touch ID status
    if broker_info.get("keychain_available"):
        click.echo(f"\n{Fore.BLUE}macOS Keychain:{Style.RESET_ALL}")
        click.echo(f"  Status: {Fore.GREEN}Available{Style.RESET_ALL}")
        click.echo("  Benefits: Secure credential storage, seamless authentication")

    if broker_info.get("touch_id_available"):
        click.echo(f"\n{Fore.BLUE}Touch ID / Face ID:{Style.RESET_ALL}")
        click.echo(f"  Status: {Fore.GREEN}Available{Style.RESET_ALL}")
        click.echo("  Benefits: Biometric authentication, secure hardware-backed keys")

    # Microsoft Authenticator status
    if broker_info.get("authenticator_app_available"):
        click.echo(f"\n{Fore.BLUE}Microsoft Authenticator:{Style.RESET_ALL}")
        click.echo(f"  Status: {Fore.GREEN}Supported{Style.RESET_ALL}")
        click.echo("  Benefits: Push notifications, time-based codes")

    # Usage instructions
    click.echo(f"\n{Fore.BLUE}Usage:{Style.RESET_ALL}")
    click.echo("  • Use 'mycli login --use-broker' for broker authentication")
    click.echo("  • Use 'mycli login --force-broker' for native broker only (no fallback)")
    click.echo("  • Use 'mycli login --use-device-code' for device code flow")
    click.echo("  • Use 'mycli login' for standard browser authentication")

    # Platform-specific setup instructions
    if platform.system() == "Darwin":  # macOS
        click.echo(f"\n{Fore.BLUE}macOS Setup:{Style.RESET_ALL}")
        click.echo("  • Install Microsoft Company Portal from the App Store for enhanced broker features")
        click.echo("  • Ensure Touch ID is enabled in System Preferences > Touch ID & Password")
        click.echo("  • Configure Microsoft Authenticator app if using multi-factor authentication")

    # Dependency information
    click.echo(f"\n{Fore.BLUE}Dependencies:{Style.RESET_ALL}")
    if platform.system() == "Darwin":  # macOS
        click.echo(
            f'  For native broker support on macOS: {Fore.CYAN}pip install "msal[broker]>=1.20,<2"{Style.RESET_ALL}'
        )
        click.echo("  Recommended: Microsoft Company Portal (App Store)")
    else:
        click.echo(f'  For native broker support: {Fore.CYAN}pip install "msal[broker]>=1.20,<2"{Style.RESET_ALL}')
    click.echo("  Without this, broker authentication falls back to browser")

    if not broker_info["platform_support"]:
        click.echo(
            f"\n{Fore.YELLOW}Note: Broker authentication is optimized for Windows and macOS platforms.{Style.RESET_ALL}"
        )
        click.echo(f"{Fore.YELLOW}Consider using device code flow on other platforms.{Style.RESET_ALL}")

    # Current authentication status
    if is_authenticated():
        auth_method = _auth_state.get("auth_method", "unknown")
        click.echo(f"\n{Fore.BLUE}Current Session:{Style.RESET_ALL}")
        click.echo(f"  Authentication Method: {Fore.CYAN}{auth_method}{Style.RESET_ALL}")
        if auth_method in ["broker_cached", "broker_interactive"]:
            click.echo(f"  Status: {Fore.GREEN}Using native broker authentication{Style.RESET_ALL}")
        elif auth_method in ["broker_cache", "browser_with_broker"]:
            click.echo(f"  Status: {Fore.YELLOW}Using broker-enabled authentication{Style.RESET_ALL}")


@cli.command()
def account():
    """Manage account and authentication settings."""
    if not is_authenticated():
        click.echo(f"{Fore.YELLOW}Account Information:{Style.RESET_ALL}")
        click.echo(f"  Status: {Fore.RED}Not Authenticated{Style.RESET_ALL}")
        click.echo("  Use 'mycli login' to sign in")
        return

    user_info = _auth_state.get("user_info", {})
    tenant_id = _auth_state.get("tenant_id")
    auth_method = _auth_state.get("auth_method", "unknown")

    click.echo(f"{Fore.BLUE}Account Information:{Style.RESET_ALL}")
    click.echo(f"  Status: {Fore.GREEN}Authenticated{Style.RESET_ALL}")
    click.echo(f"  User: {Fore.CYAN}{user_info.get('user_id', 'unknown')}{Style.RESET_ALL}")
    click.echo(f"  Display Name: {Fore.CYAN}{user_info.get('display_name', 'unknown')}{Style.RESET_ALL}")
    click.echo(f"  Tenant: {Fore.CYAN}{tenant_id or 'common'}{Style.RESET_ALL}")
    click.echo(f"  Auth Method: {Fore.CYAN}{auth_method}{Style.RESET_ALL}")

    if CONFIG_FILE.exists():
        click.echo(f"  Config File: {Fore.CYAN}{CONFIG_FILE}{Style.RESET_ALL}")


@cli.command()
@click.option("--all", is_flag=True, help="Clear all cache including MSAL broker cache")
def clear_cache(all):
    """Clear authentication cache and credentials."""
    import shutil
    from pathlib import Path

    cleared_count = 0

    # Clear mycli config and cache
    if CONFIG_DIR.exists():
        try:
            shutil.rmtree(str(CONFIG_DIR))
            click.echo(f"{Fore.GREEN}✓ Cleared MyCliApp config directory{Style.RESET_ALL}")
            cleared_count += 1
        except Exception as e:
            click.echo(f"{Fore.RED}Failed to remove config directory: {e}{Style.RESET_ALL}")

    if all:
        # Clear MSAL cache (Windows)
        if os.name == "nt":
            msal_locations = [
                Path.home() / ".cache" / "msal_http_cache",
                Path.home() / "AppData" / "Local" / "Microsoft" / "MSAL",
                Path.home() / "AppData" / "Roaming" / "Microsoft" / "MSAL",
            ]

            for cache_path in msal_locations:
                if cache_path.exists():
                    try:
                        shutil.rmtree(str(cache_path))
                        click.echo(f"{Fore.GREEN}✓ Cleared MSAL cache{Style.RESET_ALL}")
                        cleared_count += 1
                    except Exception as e:
                        click.echo(f"{Fore.YELLOW}Could not clear MSAL cache: {e}{Style.RESET_ALL}")

        # Clear MSAL cache (macOS)
        elif platform.system() == "Darwin":
            msal_locations = [
                Path.home() / ".cache" / "msal_http_cache",
                Path.home() / "Library" / "Caches" / "Microsoft" / "MSAL",
                Path.home() / "Library" / "Application Support" / "Microsoft" / "MSAL",
                Path.home() / "Library" / "Preferences" / "com.microsoft.msal.cache",
            ]

            for cache_path in msal_locations:
                if cache_path.exists():
                    try:
                        if cache_path.is_file():
                            cache_path.unlink()
                        else:
                            shutil.rmtree(str(cache_path))
                        click.echo(f"{Fore.GREEN}✓ Cleared MSAL cache (macOS){Style.RESET_ALL}")
                        cleared_count += 1
                    except Exception as e:
                        click.echo(f"{Fore.YELLOW}Could not clear MSAL cache: {e}{Style.RESET_ALL}")

            # Clear macOS Keychain MSAL entries (if accessible)
            try:
                # Note: This is a placeholder - actual keychain clearing would require
                # more specific implementation or user interaction
                click.echo(
                    f"{Fore.BLUE}💡 Tip: To clear keychain entries, run: security delete-generic-password -s 'Microsoft MSAL'{Style.RESET_ALL}"
                )
            except Exception:
                pass

        # Clear Azure CLI tokens
        azure_config = Path.home() / ".azure"
        if azure_config.exists():
            for pattern in ["*token*", "*cache*"]:
                for item in azure_config.glob(pattern):
                    try:
                        if item.is_file():
                            item.unlink()
                        elif item.is_dir():
                            shutil.rmtree(str(item))
                        click.echo(f"{Fore.GREEN}✓ Cleared Azure CLI cache item{Style.RESET_ALL}")
                        cleared_count += 1
                    except Exception as e:
                        click.echo(f"{Fore.YELLOW}Could not clear Azure item: {e}{Style.RESET_ALL}")

    # Clear in-memory auth state
    clear_auth_state()

    if cleared_count == 0:
        click.echo(f"{Fore.YELLOW}No cache files found to clear{Style.RESET_ALL}")
    else:
        click.echo(f"{Fore.GREEN}✓ Successfully cleared {cleared_count} cache location(s){Style.RESET_ALL}")

    if all:
        click.echo(f"\n{Fore.BLUE}💡 Additional cleanup recommendations:{Style.RESET_ALL}")
        click.echo("  • Clear browser cache for login.microsoftonline.com")

        if os.name == "nt":  # Windows
            click.echo("  • Sign out from Windows Hello/Authenticator if needed")
        elif platform.system() == "Darwin":  # macOS
            click.echo("  • Sign out from Touch ID/Face ID authentication if needed")
            click.echo("  • Clear keychain entries: security delete-generic-password -s 'Microsoft MSAL'")
            click.echo("  • Sign out from Microsoft Authenticator app if needed")

        click.echo("  • Restart your terminal")


@cli.command()
def status():
    """Show current status and health."""
    auth_status = "Active" if is_authenticated() else "Not Authenticated"
    auth_color = Fore.GREEN if is_authenticated() else Fore.RED

    user_info = _auth_state.get("user_info", {}) if is_authenticated() else {}
    user_display = user_info.get("user_id", "None") if is_authenticated() else "None"
    auth_method = _auth_state.get("auth_method", "None") if is_authenticated() else "None"

    click.echo(f"{Fore.BLUE}📊 System Status:{Style.RESET_ALL}")
    click.echo(f"  Service: {Fore.GREEN}Online{Style.RESET_ALL}")
    click.echo(f"  Authentication: {auth_color}{auth_status} ({user_display}){Style.RESET_ALL}")
    if is_authenticated():
        click.echo(f"  Auth Method: {Fore.CYAN}{auth_method}{Style.RESET_ALL}")

    # Broker support information
    broker_info = get_broker_info()
    broker_color = Fore.GREEN if broker_info["platform_support"] else Fore.YELLOW
    broker_status = "Available" if broker_info["platform_support"] else "Limited"
    click.echo(f"  Broker Support: {broker_color}{broker_status}{Style.RESET_ALL}")

    click.echo(
        f"  Azure SDK: {Fore.GREEN if AZURE_AVAILABLE else Fore.RED}{'Available' if AZURE_AVAILABLE else 'Not Available'}{Style.RESET_ALL}"
    )
    click.echo(f"  Version: {Fore.CYAN}{__version__}{Style.RESET_ALL}")

    if not AZURE_AVAILABLE:
        click.echo(f"\n{Fore.YELLOW}💡 Install Azure packages for full functionality:{Style.RESET_ALL}")
        click.echo("    pip install azure-identity azure-mgmt-core azure-core msal")

    if not broker_info["platform_support"]:
        click.echo(
            f"\n{Fore.YELLOW}💡 For enhanced security, use broker authentication on Windows or macOS platforms{Style.RESET_ALL}"
        )


def main():
    """Entry point for the CLI application."""
    try:
        cli()
    except KeyboardInterrupt:
        click.echo(f"\n{Fore.YELLOW}Operation cancelled.{Style.RESET_ALL}")
        sys.exit(1)
    except Exception as e:
        click.echo(f"{Fore.RED}Error: {e}{Style.RESET_ALL}")
        sys.exit(1)


if __name__ == "__main__":
    main()
