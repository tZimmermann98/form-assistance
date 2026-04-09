"""Detect BundID / eID / login authentication gates on municipal forms.

When an auth gate is detected, we always take the anonymous/guest path.
BundID requires a physical eID card + PIN — cannot be automated via MCP.
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Keywords that indicate an authentication gate
AUTH_KEYWORDS = [
    "bundid", "bund-id", "bund id",
    "eid", "e-id",
    "servicekonto",
    "mein münster", "mein muenster",
    "personalausweis online",
    "mit personalausweis",
    "online-ausweisfunktion",
    "ausweisapp",
]

# Keywords for the anonymous/guest bypass option
ANON_KEYWORDS = [
    "weiter ohne anmeldung",
    "weiter ohne bundid",
    "ohne bundid",
    "ohne anmeldung",
    "als gast",
    "ohne servicekonto",
    "ohne registrierung",
    "anonym",
    "ohne login",
    "weiter ohne",
    "überspringen",
    "ueberspringen",
]


@dataclass
class AuthGateResult:
    """Result of auth gate detection."""
    detected: bool
    auth_type: str  # "bundid" | "eid" | "servicekonto" | "login"
    anon_button_text: str | None  # Text of the anonymous bypass button/link
    auth_button_text: str | None  # Text of the authenticated path button/link


async def detect_auth_gate(page) -> AuthGateResult | None:
    """Scan the current page for authentication gates.

    Returns AuthGateResult if an auth gate is found, None otherwise.
    """
    result = await page.evaluate("""() => {
        const bodyText = document.body.innerText.toLowerCase();

        // Check for auth keywords in page text
        const authKeywords = """ + repr(AUTH_KEYWORDS) + """;
        const foundAuth = authKeywords.some(kw => bodyText.includes(kw));
        if (!foundAuth) return null;

        // Determine auth type
        let authType = 'login';
        if (bodyText.includes('bundid') || bodyText.includes('bund-id') || bodyText.includes('bund id')) {
            authType = 'bundid';
        } else if (bodyText.includes('eid') || bodyText.includes('e-id') || bodyText.includes('personalausweis')) {
            authType = 'eid';
        } else if (bodyText.includes('servicekonto')) {
            authType = 'servicekonto';
        }

        // Find anonymous/guest bypass buttons/links
        const anonKeywords = """ + repr(ANON_KEYWORDS) + """;
        const clickables = Array.from(document.querySelectorAll(
            'button, a, input[type="submit"], input[type="button"], [role="button"]'
        ));

        let anonButton = null;
        let authButton = null;

        for (const el of clickables) {
            const text = (el.textContent || el.value || '').toLowerCase().trim();
            if (!text) continue;

            // Check if this is the anonymous path
            const isAnon = anonKeywords.some(kw => text.includes(kw));
            if (isAnon && !anonButton) {
                anonButton = (el.textContent || el.value || '').trim();
            }

            // Check if this is the auth path
            const isAuth = authKeywords.some(kw => text.includes(kw));
            if (isAuth && !authButton) {
                authButton = (el.textContent || el.value || '').trim();
            }
        }

        // If no explicit anon button found, look for a generic "Weiter" button
        // that exists alongside auth options
        if (!anonButton) {
            const weiterBtn = clickables.find(el => {
                const text = (el.textContent || el.value || '').toLowerCase().trim();
                return text === 'weiter' || text === 'weiter ohne anmeldung'
                    || text.includes('fortfahren') || text.includes('überspringen');
            });
            if (weiterBtn) {
                anonButton = (weiterBtn.textContent || weiterBtn.value || '').trim();
            }
        }

        return {
            detected: true,
            authType: authType,
            anonButtonText: anonButton,
            authButtonText: authButton,
        };
    }""")

    if result is None:
        return None

    return AuthGateResult(
        detected=result["detected"],
        auth_type=result["authType"],
        anon_button_text=result.get("anonButtonText"),
        auth_button_text=result.get("authButtonText"),
    )


async def bypass_auth_gate(page, gate: AuthGateResult) -> bool:
    """Bypass the auth gate by selecting the anonymous/guest option.

    The common pattern on Münster forms is:
    1. Radio buttons: "BundID" vs "Weiter ohne Anmeldung"
    2. Then a "Weiter" button to proceed

    We must select the anonymous radio FIRST, then click Weiter.

    Returns True if bypass was successful (page navigated).
    """
    before_url = page.url

    # Step 1: Select the anonymous radio button if present
    # Look for radio/checkbox with anonymous keywords in its label
    anon_radio_clicked = await page.evaluate("""() => {
        const anonKeywords = ['ohne anmeldung', 'ohne bundid', 'als gast',
                              'ohne servicekonto', 'ohne registrierung',
                              'anonym', 'ohne login', 'weiter ohne'];
        const radios = document.querySelectorAll('input[type="radio"], input[type="checkbox"]');
        for (const r of radios) {
            let label = '';
            const wrap = r.closest('label');
            if (wrap) label = wrap.textContent.toLowerCase().trim();
            if (!label && r.id) {
                const lbl = document.querySelector('label[for="' + r.id + '"]');
                if (lbl) label = lbl.textContent.toLowerCase().trim();
            }
            if (label && anonKeywords.some(kw => label.includes(kw))) {
                r.click();
                return label;
            }
        }
        return null;
    }""")

    if anon_radio_clicked:
        logger.info("Selected anonymous radio: %s", anon_radio_clicked)
        await page.wait_for_timeout(300)  # Wait for any UI updates

    # Step 2: Click the Weiter/proceed button
    clicked = False
    weiter_patterns = ["Weiter", "Fortfahren", "Ohne Anmeldung fortfahren"]
    for pattern in weiter_patterns:
        try:
            btn = page.get_by_role("button", name=pattern)
            if await btn.count() > 0:
                await btn.first.click()
                clicked = True
                break
        except Exception:
            pass

    if not clicked:
        # JS fallback for the Weiter button
        clicked = await page.evaluate("""() => {
            const btns = Array.from(document.querySelectorAll('button, input[type="submit"]'));
            const next = btns.find(b => {
                const text = (b.textContent || b.value || '').toLowerCase();
                return text.includes('weiter') || text.includes('fortfahren');
            });
            if (next) { next.click(); return true; }
            return false;
        }""")

    if not clicked:
        # Last resort: if we found the anon_button_text from detection, try it as link/button
        if gate.anon_button_text:
            try:
                link = page.get_by_role("link", name=gate.anon_button_text)
                if await link.count() > 0:
                    await link.first.click()
                    clicked = True
            except Exception:
                pass

    if not clicked:
        logger.warning("Auth gate: could not find any button to bypass")
        return False

    # Wait for navigation
    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        await page.wait_for_timeout(3000)

    # Check if we actually navigated: URL change or content change
    after_url = page.url
    if before_url != after_url:
        return True

    # Also check if page content changed (for SPA-style navigation)
    after_text = await page.evaluate('() => document.body.innerText.substring(0, 500)')
    before_text = await page.evaluate('() => ""')  # We don't have before_text saved, so check for auth keywords gone
    # If the auth keywords are no longer on the page, bypass succeeded
    still_auth = await page.evaluate("""() => {
        const text = document.body.innerText.toLowerCase();
        return text.includes('bundid') || text.includes('servicekonto')
            || text.includes('anmeldung');
    }""")
    return not still_auth
