"""Debug script: test consent step navigation on a real Münster form."""
import asyncio
import logging

logging.basicConfig(level=logging.INFO)

URL = "https://formulare.stadt-muenster.de/metaform/Form-Solutions/sid/assistant/6710d9f5b702d90afb085027"


async def main():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(URL, wait_until="networkidle")

        # 1. Page state
        title = await page.evaluate('() => (document.querySelector("h1, h2, h3") || {}).textContent || ""')
        print(f"Title: {title}")

        text = await page.evaluate('() => document.body.innerText.substring(0, 400)')
        print(f"Text sample: {text[:300]}")

        # 2. Checkboxes
        cbs = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('input[type="checkbox"]')).map(cb => ({
                name: cb.name, checked: cb.checked,
                visible: cb.offsetParent !== null,
                label: (cb.closest('label') || {}).textContent ? cb.closest('label').textContent.trim().substring(0,80) : 'no-wrap-label'
            }));
        }""")
        print(f"Checkboxes: {cbs}")

        # 3. Buttons
        btns = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('button, input[type="submit"], a.btn, a[role="button"], [type="button"]'))
                .map(b => ({text: (b.textContent || b.value || '').trim().substring(0,60), tag: b.tagName, disabled: b.disabled}))
                .filter(b => b.text);
        }""")
        print(f"Buttons: {btns}")

        # 4. Is consent page?
        from explorer.tree_explorer import _is_consent_page
        is_consent = await _is_consent_page(page)
        print(f"Is consent page: {is_consent}")

        # 5. Try fill_for_navigation
        from explorer.extractors.navigation import fill_for_navigation
        recipe = await fill_for_navigation(page)
        print(f"Fill recipe ({len(recipe)} items): {recipe}")

        # 6. Check if checkbox is now checked
        cbs_after = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('input[type="checkbox"]')).map(cb => ({
                name: cb.name, checked: cb.checked
            }));
        }""")
        print(f"Checkboxes after fill: {cbs_after}")

        # 7. Try click Weiter
        before_url = page.url
        from explorer.extractors.navigation import _click_next_button
        clicked = await _click_next_button(page)
        print(f"Clicked next button: {clicked}")

        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            await page.wait_for_timeout(3000)

        after_url = page.url
        url_changed = before_url != after_url
        print(f"URL changed: {url_changed}")
        print(f"  Before: {before_url}")
        print(f"  After:  {after_url}")

        new_title = await page.evaluate('() => (document.querySelector("h1, h2, h3") || {}).textContent || ""')
        print(f"New title: {new_title}")

        new_text = await page.evaluate('() => document.body.innerText.substring(0, 300)')
        print(f"New text: {new_text[:200]}")

        # 8. Any validation errors?
        errors = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('[class*="error"], [class*="feedback"], .alert'))
                .map(e => e.textContent.trim()).filter(Boolean);
        }""")
        print(f"Validation errors: {errors}")

        await browser.close()


asyncio.run(main())
