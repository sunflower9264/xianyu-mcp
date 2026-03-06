"""Anti-detection configuration for Playwright."""

from playwright.async_api import BrowserContext


# Fixed user agent - most common Windows Chrome
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Stealth scripts to inject
STEALTH_SCRIPTS = """
// Hide webdriver property
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined
});

// Override plugins
Object.defineProperty(navigator, 'plugins', {
    get: () => [
        { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
        { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
        { name: 'Native Client', filename: 'internal-nacl-plugin' }
    ]
});

// Override languages
Object.defineProperty(navigator, 'languages', {
    get: () => ['zh-CN', 'zh', 'en']
});

// Override platform
Object.defineProperty(navigator, 'platform', {
    get: () => 'Win32'
});

// Override hardwareConcurrency
Object.defineProperty(navigator, 'hardwareConcurrency', {
    get: () => 8
});

// Override deviceMemory
Object.defineProperty(navigator, 'deviceMemory', {
    get: () => 8
});

// Hide automation indicators
window.chrome = {
    runtime: {}
};

// Override permissions
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications' ?
        Promise.resolve({ state: Notification.permission }) :
        originalQuery(parameters)
);
"""


def get_random_user_agent() -> str:
    """Get the fixed user agent."""
    return USER_AGENT


async def apply_stealth_to_context(context: BrowserContext) -> None:
    """Apply stealth configurations to a browser context."""
    # Add init script to hide automation
    await context.add_init_script(STEALTH_SCRIPTS)



def get_stealth_context_options() -> dict:
    """Get context options for stealth mode."""
    return {
        "user_agent": get_random_user_agent(),
        "viewport": {"width": 1920, "height": 1080},
        "locale": "zh-CN",
        "timezone_id": "Asia/Shanghai",
        "geolocation": {"latitude": 31.2304, "longitude": 121.4737},  # Shanghai
        "permissions": ["geolocation"],
    }
