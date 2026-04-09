"""Debug: test full BundID bypass flow."""
import asyncio

URL = "https://formulare.stadt-muenster.de/metaform/Form-Solutions/sid/assistant/6710d9f5b702d90afb085027"

async def main():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(URL, wait_until="networkidle")

        # Consent
        from explorer.extractors.navigation import fill_for_navigation, _click_next_button
        await fill_for_navigation(page)
        await _click_next_button(page)
        await page.wait_for_load_state("networkidle", timeout=15000)
        print(f"1. After consent - URL: {page.url}")

        # BundID bypass with the fix
        from explorer.extractors.auth_detector import detect_auth_gate, bypass_auth_gate
        gate = await detect_auth_gate(page)
        print(f"2. Auth gate: {gate}")

        if gate:
            bypassed = await bypass_auth_gate(page, gate)
            print(f"3. Bypassed: {bypassed}")
            print(f"4. URL after bypass: {page.url}")

            text = await page.evaluate('() => document.body.innerText.substring(0, 300)')
            print(f"5. Page text: {text[:200]}")

            from explorer.extractors.field_extractor import extract_fields
            fields = await extract_fields(page)
            print(f"6. Fields found: {len(fields)}")
            for f in fields[:5]:
                print(f"   - {f.get('label', '?')} ({f.get('type', '?')})")

        await browser.close()

asyncio.run(main())
