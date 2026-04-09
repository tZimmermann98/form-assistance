"""Debug: test improved fill_for_navigation on the real form."""
import asyncio

URL = "https://formulare.stadt-muenster.de/metaform/Form-Solutions/sid/assistant/6710d9f5b702d90afb085027"

async def main():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(URL, wait_until="networkidle")

        from explorer.extractors.navigation import fill_for_navigation, _click_next_button
        from explorer.extractors.auth_detector import detect_auth_gate, bypass_auth_gate
        from explorer.extractors.field_extractor import extract_fields

        # Consent
        await fill_for_navigation(page)
        await _click_next_button(page)
        await page.wait_for_load_state("networkidle", timeout=15000)

        # BundID
        gate = await detect_auth_gate(page)
        if gate:
            await bypass_auth_gate(page, gate)
            await page.wait_for_load_state("networkidle", timeout=15000)

        # Info pages
        for _ in range(3):
            fields = await extract_fields(page)
            if len(fields) == 0:
                await _click_next_button(page)
                await page.wait_for_load_state("networkidle", timeout=15000)
            else:
                break

        # Form step
        fields = await extract_fields(page)
        print(f"=== Step 1: {len(fields)} fields ===")

        recipe = await fill_for_navigation(page)
        print(f"Filled {len(recipe)} fields:")
        for r in recipe:
            print(f"  {r.get('label','?'):40} = {r.get('value','?')}")

        # Try Weiter
        before_url = page.url
        await _click_next_button(page)
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except:
            await page.wait_for_timeout(5000)

        after_url = page.url
        print(f"\nNavigated: {before_url != after_url}")

        # What's on the next page?
        heading = await page.evaluate('() => (document.querySelector("h2, h3") || {}).textContent || ""')
        print(f"Next heading: {heading}")

        fields2 = await extract_fields(page)
        print(f"Next page fields: {len(fields2)}")
        for f in fields2[:5]:
            print(f"  {f.get('label','?'):40} ({f.get('type','?')})")

        await browser.close()

asyncio.run(main())
