"""Debug: list all clickable elements on the BundID gate page."""
import asyncio

URL = "https://formulare.stadt-muenster.de/metaform/Form-Solutions/sid/assistant/6710d9f5b702d90afb085027"

async def main():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(URL, wait_until="networkidle")

        from explorer.extractors.navigation import fill_for_navigation, _click_next_button
        await fill_for_navigation(page)
        await _click_next_button(page)
        await page.wait_for_load_state("networkidle", timeout=15000)

        # List ALL clickable elements
        elements = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('button, a, input[type="submit"], [role="button"]'))
                .map(el => ({
                    tag: el.tagName,
                    text: (el.textContent || el.value || '').trim().substring(0, 80),
                    href: el.href || null,
                    classes: el.className || ''
                }))
                .filter(el => el.text);
        }""")
        for el in elements:
            print(f"{el['tag']:8} | {el['text']:60} | href={el.get('href', '')}")

        await browser.close()

asyncio.run(main())
