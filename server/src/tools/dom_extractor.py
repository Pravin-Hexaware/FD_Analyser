import asyncio
from playwright.async_api import async_playwright

BSE_URL = "https://www.bseindia.com/corporates/comp_resultsnew"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/121 Safari/537.36"
)


async def extract_bse_dom(headless: bool = False):
    print("[DOM] Extracting DOM from BSE page (headless=" + str(headless) + ")")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"]
        )

        context = await browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent=USER_AGENT
        )

        # ✅ Anti-detection tweaks
        await context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
        Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
        """)

        page = await context.new_page()

        print(f"[Opening] {BSE_URL}")
        await page.goto(BSE_URL, wait_until="networkidle", timeout=60000)
        print("[OK] Page loaded (networkidle)")
        
        # Multiple wait strategies to ensure dynamic content loads
        await page.wait_for_timeout(5000)
        
        # Trigger any lazy-loading by scrolling
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(2000)
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(1000)

        # ✅ INPUTS (IMPROVED)
        inputs = await page.evaluate("""
        () => {
            const all = Array.from(document.querySelectorAll('input, textarea')).map(el => {
                const label = document.querySelector(`label[for="${el.id}"]`);
                const container = el.closest('div, form');
                const classes = (el.className || "").toString().split(' ').filter(cls => cls.trim().length > 0);
                const class_selector = classes.length > 0 ? el.tagName.toLowerCase() + "." + classes.join(".") : "";
                let selector_smart = "";
                if (classes.includes("smartsearch__input")) {
                    selector_smart = "input.smartsearch__input:not(.smartsearch__input__global)";
                } else {
                    selector_smart = class_selector;
                }
                return {
                    tag: el.tagName,
                    id: el.id,
                    name: el.name,
                    placeholder: el.placeholder,
                    type: el.type,
                    class: el.className,
                    label: label ? label.innerText.trim() : "",
                    container_class: container ? container.className : "",
                    nearby_text: (el.parentElement?.innerText || "").slice(0, 100),
                    selector_id: el.id ? "#" + el.id : "",
                    selector_class: class_selector,
                    selector_smart: selector_smart,
                    visible: el.offsetParent !== null,
                    value: el.value
                }
            });
            console.log("Found " + all.length + " inputs");
            return all;
        }
        """)


        # ✅ DROPDOWNS
        dropdowns = await page.evaluate("""
        () => {
            const all = Array.from(document.querySelectorAll('select')).map(el => {
                const classes = (el.className || "").split(' ').filter(cls => cls.trim().length > 0);
                const class_selector = classes.length > 0 ? "select." + classes.join(".") : "";
                return {
                    id: el.id,
                    name: el.name,
                    class: el.className,
                    selector_id: el.id ? "#" + el.id : "",
                    selector_class: class_selector,
                    options: Array.from(el.options).map(o => ({ value: o.value, text: o.text, selected: o.selected }))
                }
            });
            console.log("Found " + all.length + " dropdowns");
            return all;
        }
        """)

        # ✅ BUTTONS
        buttons = await page.evaluate("""
        () => {
            const all = Array.from(document.querySelectorAll('button, input[type="submit"]')).map(el => {
                const classes = (el.className || "").split(' ').filter(x => x);
                const class_selector = classes.length > 0 ? el.tagName.toLowerCase() + "." + classes.join(".") : "";
                return {
                    text: el.innerText || el.value || "",
                    id: el.id,
                    class: el.className,
                    selector_id: el.id ? "#" + el.id : "",
                    selector_class: class_selector
                }
            });
            console.log("Found " + all.length + " buttons");
            return all;
        }
        """)

        # ✅ TABLES
        tables = await page.evaluate("""
        () => {
            const all = Array.from(document.querySelectorAll('table')).map(el => ({
                id: el.id,
                class: el.className,
                selector_id: el.id ? "#" + el.id : "",
                rows: el.rows.length,
                preview: el.innerText.slice(0, 200)
            }));
            console.log("Found " + all.length + " tables");
            return all;
        }
        """)

        # ✅ SUGGESTION CONTAINERS & BOXES (AJAX-GENERATED)
        suggestions = await page.evaluate("""
        () => {
            const candidates = [];
            
            // Look for common suggestion container patterns
            const containers = document.querySelectorAll(
                '[id*="ajax"], [class*="suggestion"], [class*="dropdown"], [class*="smartsearch"], [role="listbox"], [role="list"]'
            );
            
            containers.forEach(el => {
                // Skip hidden elements
                if (el.offsetParent === null && el.style.display === 'none') return;
                
                const classes = (el.className || "").split(' ').filter(x => x);
                const class_selector = classes.length > 0 ? el.tagName.toLowerCase() + "." + classes.join(".") : "";
                
                // Count anchor tags inside (these would be the actual suggestions)
                const anchors = el.querySelectorAll('a, [role="option"], li, div[role="option"]');
                
                if (el.id || classes.length > 0 || anchors.length > 0) {
                    candidates.push({
                        id: el.id,
                        tag: el.tagName,
                        class: el.className,
                        role: el.getAttribute('role'),
                        selector_id: el.id ? "#" + el.id : "",
                        selector_class: class_selector,
                        child_anchors_count: anchors.length,
                        child_anchors_selectors: Array.from(anchors).slice(0, 3).map(a => ({
                            tag: a.tagName,
                            text: (a.innerText || "").slice(0, 50),
                            class: a.className,
                            selector_class: (a.className || "").split(' ').length > 0 ? a.tagName.toLowerCase() + "." + (a.className || "").split(' ').join(".") : ""
                        })),
                        visible: el.offsetParent !== null,
                        parent_classes: el.parentElement ? el.parentElement.className : ""
                    });
                }
            });
            
            // Also extract direct anchor tags that might be suggestions
            const allAnchors = Array.from(document.querySelectorAll('a[role="option"], li a, div[role="option"] a, .suggestion a, [class*="smartsearch"] a')).slice(0, 5).map(el => ({
                text: (el.innerText || "").slice(0, 50),
                class: el.className,
                parent_class: el.parentElement ? el.parentElement.className : "",
                selector_class: (el.className || "").split(' ').filter(x => x).length > 0 ? "a." + (el.className || "").split(' ').join(".") : ""
            }));
            
            console.log("Found " + candidates.length + " suggestion containers");
            return {
                containers: candidates,
                sample_anchors: allAnchors
            };
        }
        """)

        print("\n[UI COUNTS]")
        print(f"Inputs: {len(inputs)}")
        print(f"Dropdowns: {len(dropdowns)}")
        print(f"Buttons: {len(buttons)}")
        print(f"Tables: {len(tables)}")
        print(f"Suggestion containers: {len(suggestions.get('containers', []))}")
        print(f"Sample suggestion anchors: {len(suggestions.get('sample_anchors', []))}")

        dom = await page.content()
        text = await page.inner_text("body")

        await browser.close()

        return {
            "dom": dom[:15000],
            "text": text[:5000],
            "ui": {
                "inputs": inputs,
                "dropdowns": dropdowns,
                "buttons": buttons,
                "tables": tables,
                "suggestions": suggestions
            }
        }


async def main():
    result = await extract_bse_dom()
    print("\n✅ FINAL RESULT:")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
