import asyncio
import json
import base64
from playwright.async_api import async_playwright

from llm.azure_llm import evaluate_with_azure_llm, markdownify

# =============================
# CONFIG
# =============================
BSE_URL = "https://www.bseindia.com/corporates/comp_resultsnew"


# =============================
# HELPER: Encode screenshot
# =============================
def encode_image(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


# =============================
# DOM EXTRACTION (FIXED)
# =============================
async def extract_dom_clusters(page):
    return await page.evaluate(r"""
    () => {

        function getContainer(el) {
            return el.closest("form, section, article, div") || document.body;
        }

        function countVisibleMatches(selector) {
            if (!selector) return 0;
            try {
                return Array.from(document.querySelectorAll(selector)).filter(node => node.offsetParent !== null).length;
            } catch (e) {
                return 0;
            }
        }

        const elements = Array.from(document.querySelectorAll("input, button, select, table"));
        const clusters = [];
        const suggestionContainers = [];

        function findCluster(container) {
            return clusters.find(c => c.container.isSameNode(container));
        }

        // ✅ STEP 1: RAW CLUSTER BUILD
        elements.forEach(el => {
            const container = getContainer(el);
            let cluster = findCluster(container);

            if (!cluster) {
                cluster = {
                    container: container,
                    container_tag: container.tagName,
                    container_class: container.className || "",
                    container_id: container.id || "",
                    container_selector: container.id ? `${container.tagName.toLowerCase()}#${container.id}` : (container.className ? `${container.tagName.toLowerCase()}.${container.className.trim().split(/\s+/).join('.')}` : container.tagName.toLowerCase()),
                    inputs: [],
                    buttons: [],
                    dropdowns: [],
                    suggestions: [],
                    tables: []
                };
                clusters.push(cluster);
            }

            if (el.tagName === "INPUT" && el.type !== "button" && el.type !== "submit") {
                const classes = (el.className || "").split(' ').filter(x => x);
                const class_selector = classes.length > 0 ? el.tagName.toLowerCase() + "." + classes.join(".") : el.tagName.toLowerCase();
                const selector_id = el.id ? "#" + el.id : "";
                const selector = selector_id || class_selector;
                cluster.inputs.push({
                    tag: el.tagName,
                    selector,
                    selector_id,
                    selector_class: class_selector,
                    selector_id_visible_match_count: countVisibleMatches(selector_id),
                    selector_class_visible_match_count: countVisibleMatches(class_selector),
                    visible_match_count: countVisibleMatches(selector),
                    id: el.id,
                    name: el.name,
                    placeholder: el.placeholder,
                    class: el.className,
                    type: el.type,
                    label: document.querySelector(`label[for="${el.id}"]`)?.innerText.trim() || "",
                    container_tag: container.tagName,
                    container_id: container.id || "",
                    container_class: container.className || "",
                    container_selector: cluster.container_selector,
                    container_text: container.innerText ? container.innerText.trim().replace(/\s+/g, " ").slice(0, 300) : "",
                    nearby_text: (el.parentElement?.innerText || "").slice(0, 150),
                    visible: el.offsetParent !== null,
                    value: el.value
                });
            }

            if (el.tagName === "BUTTON" || (el.tagName === "INPUT" && ["button", "submit"].includes(el.type))) {
                const classes = (el.className || "").split(' ').filter(x => x);
                const class_selector = classes.length > 0 ? el.tagName.toLowerCase() + "." + classes.join(".") : el.tagName.toLowerCase();
                const selector_id = el.id ? "#" + el.id : "";
                const selector = selector_id || class_selector;
                cluster.buttons.push({
                    tag: el.tagName,
                    selector,
                    selector_id,
                    selector_class: class_selector,
                    selector_id_visible_match_count: countVisibleMatches(selector_id),
                    selector_class_visible_match_count: countVisibleMatches(class_selector),
                    visible_match_count: countVisibleMatches(selector),
                    id: el.id,
                    text: el.innerText || el.value || "",
                    class: el.className,
                    type: el.type,
                    container_tag: container.tagName,
                    container_id: container.id || "",
                    container_class: container.className || "",
                    container_selector: cluster.container_selector,
                    visible: el.offsetParent !== null
                });
            }

            if (el.tagName === "SELECT") {
                const classes = (el.className || "").split(' ').filter(x => x);
                const class_selector = classes.length > 0 ? "select." + classes.join(".") : "select";
                const selector_id = el.id ? "#" + el.id : "";
                const selector = selector_id || class_selector;
                cluster.dropdowns.push({
                    tag: el.tagName,
                    selector,
                    selector_id,
                    selector_class: class_selector,
                    selector_id_visible_match_count: countVisibleMatches(selector_id),
                    selector_class_visible_match_count: countVisibleMatches(class_selector),
                    visible_match_count: countVisibleMatches(selector),
                    id: el.id,
                    name: el.name,
                    class: el.className,
                    container_tag: container.tagName,
                    container_id: container.id || "",
                    container_class: container.className || "",
                    container_selector: cluster.container_selector,
                    options: Array.from(el.options).map(o => ({ value: o.value, text: o.text, selected: o.selected })),
                    visible: el.offsetParent !== null
                });
            }

            if (el.tagName === "TABLE") {
                const selector = el.id ? `#${el.id}` : el.className ? `table.${el.className.trim().split(/\s+/).join('.')}` : 'table';
                cluster.tables.push({
                    tag: el.tagName,
                    selector,
                    selector_id: el.id ? `#${el.id}` : "",
                    selector_class: el.className ? `table.${el.className.trim().split(/\s+/).join('.')}` : "table",
                    selector_id_visible_match_count: countVisibleMatches(el.id ? `#${el.id}` : ""),
                    selector_class_visible_match_count: countVisibleMatches(el.className ? `table.${el.className.trim().split(/\s+/).join('.')}` : "table"),
                    visible_match_count: countVisibleMatches(selector),
                    id: el.id,
                    class: el.className,
                    rows: el.rows.length,
                    preview: el.innerText.slice(0, 200),
                    visible: el.offsetParent !== null
                });
            }
        });

        // ✅ STEP 2B: DETECT SUGGESTION CONTAINERS (AJAX-GENERATED)
        const suggestionPatterns = document.querySelectorAll(
            '[id*="ajax"], [class*="suggestion"], [class*="dropdown"], [class*="autocomplete"], [class*="smartsearch"], [role="listbox"], [role="list"], [role="menu"]'
        );
        suggestionPatterns.forEach(el => {
            if (el.offsetParent === null && el.style.display === 'none') return;
            const classes = (el.className || "").split(' ').filter(x => x);
            const selector = el.id ? `#${el.id}` : classes.length > 0 ? el.tagName.toLowerCase() + "." + classes.join(".") : el.tagName.toLowerCase();
            suggestionContainers.push({
                tag: el.tagName,
                selector: selector,
                selector_id: el.id ? `#${el.id}` : "",
                selector_class: classes.length > 0 ? el.tagName.toLowerCase() + "." + classes.join(".") : "",
                selector_id_visible_match_count: countVisibleMatches(el.id ? `#${el.id}` : ""),
                selector_class_visible_match_count: countVisibleMatches(classes.length > 0 ? el.tagName.toLowerCase() + "." + classes.join(".") : ""),
                visible_match_count: countVisibleMatches(selector),
                id: el.id,
                class: el.className,
                role: el.getAttribute('role'),
                visible: el.offsetParent !== null,
                children_count: el.children.length,
                text_content: el.innerText.slice(0, 200)
            });
        });

        // ✅ STEP 2: CLEAN CLUSTERS
        const cleanedClusters = clusters.map(c => ({
            container_tag: c.container_tag,
            container_id: c.container_id,
            container_class: c.container_class,
            container_selector: c.container_selector,
            container_html: c.container.outerHTML ? c.container.outerHTML.slice(0, 1500) : "",
            container_text: c.container.innerText ? c.container.innerText.trim().replace(/\s+/g, " ").slice(0, 500) : "",
            inputs: c.inputs,
            buttons: c.buttons,
            dropdowns: c.dropdowns,
            suggestions: c.suggestions,
            tables: c.tables
        }));

        const inputs = cleanedClusters.flatMap(c => c.inputs);
        const buttons = cleanedClusters.flatMap(c => c.buttons);
        const dropdowns = cleanedClusters.flatMap(c => c.dropdowns);
        const suggestions = suggestionContainers;
        const tables = cleanedClusters.flatMap(c => c.tables);


        // ✅ STEP 3: SCORING-BASED FORM DETECTION (FIXED)

        function getFormScore(cluster) {
            let score = 0;

            score += cluster.inputs.length * 5;
            score += cluster.dropdowns.length * 4;
            score += cluster.buttons.length * 3;

            // ✅ boost if real text input (avoid checkbox noise)
            const hasTextInput = cluster.inputs.some(i =>
                i.type === "text" ||
                (i.placeholder && i.placeholder.toLowerCase().includes("search"))
            );

            if (hasTextInput) score += 10;

            return score;
        }

        let bestFormCluster = null;
        let bestScore = 0;

        cleanedClusters.forEach(c => {
            const score = getFormScore(c);

            if (score > bestScore) {
                bestScore = score;
                bestFormCluster = c;
            }
        });


        // ✅ STEP 4: RESULT DETECTION (GENERIC + FILTERED)

        function isRelevantTable(table) {
            const cls = (table.class || "").toLowerCase();
            const id = table.id || "";

            return (
                id.length > 0 ||
                cls.includes("table")
            );
        }

        const resultCluster = {
            cluster_type: "result_cluster",
            inputs: [],
            buttons: [],
            dropdowns: [],
            tables: []
        };

        cleanedClusters.forEach(c => {
            if (c.tables.length > 0) {
                resultCluster.tables.push(...c.tables.filter(isRelevantTable));
            }
        });


        // ✅ STEP 5: FINAL FORM CLUSTER

        const formCluster = {
            cluster_type: "form_cluster",
            inputs: bestFormCluster ? bestFormCluster.inputs : [],
            buttons: bestFormCluster ? bestFormCluster.buttons : [],
            dropdowns: bestFormCluster ? bestFormCluster.dropdowns : [],
            tables: []
        };


        return {
            clusters: cleanedClusters,
            raw_clusters: cleanedClusters,
            logical_clusters: [
                formCluster,
                resultCluster
            ],
            inputs: inputs,
            buttons: buttons,
            dropdowns: dropdowns,
            suggestions: suggestions,
            tables: tables,
            debug: {
                best_form_score: bestScore,
                suggestion_containers_found: suggestionContainers.length
            }
        };
    }
    """)



# =============================
# REUSABLE DOM EXTRACTOR
# =============================
async def extract_dom_from_url(url, headless=True, screenshot_path="bse_page.png"):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        page = await browser.new_page()

        print(f"[DOM TOOL] Navigating to {url} headless={headless}")
        await page.goto(url, wait_until="networkidle", timeout=60000)
        await page.wait_for_timeout(5000)

        dom = await extract_dom_clusters(page)
        html = await page.content()
        text = await page.inner_text("body")

        screenshot_bytes = await page.screenshot(path=screenshot_path, full_page=True)
        screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")

        await browser.close()

        return {
            "url": url,
            "dom": dom,
            "html": html,
            "text": text,
            "screenshot_path": screenshot_path,
            "screenshot_b64": screenshot_b64
        }




def build_dom_combined_prompt(dom_data):
    dom = dom_data.get("dom", {})
    clusters = dom.get("clusters", [])
    url = dom_data.get("url", "")
    page_text = dom_data.get("text", "")[:5000]
    screenshot_b64 = dom_data.get("screenshot_b64", "")[:1000]

    return f"""
You are an expert UI automation DOM analysis agent.

INPUT:
- FULL PAGE DOM JSON with clusters and extracted elements
- DOM CLUSTERS WITH CONTAINER CONTEXT
- SCREENSHOT BASE64 FOR VISUAL REFERENCE
- PAGE TEXT CONTENT
- PAGE URL

DUAL TASK:
1. FILTER THE DOM: Remove duplicates, keep stable selectors, preserve form/result clusters, identify suggestion boxes
2. UNDERSTAND THE DOM: Identify UI roles (search input, filters, buttons, results table, suggestion containers, data links) and their selectors

FILTERING RULES:
- Analyze all extracted inputs, dropdowns, buttons, suggestions, and tables
- For duplicate selectors, choose the one with:
  * visible=true over visible=false
  * Better proximity to labels or descriptive text
  * Presence in form_cluster over isolated elements
- IDENTIFY SUGGESTION BOXES
- Return deduplicated, stable selectors only
- Include container context and suggestion container selectors
- Ensure chosen selectors are unique and match exactly one visible element in the DOM

UNDERSTANDING RULES:
- Identify PRIMARY ROLES: search inputs, filter controls, action buttons, result containers
- For each role, list ALL possible selectors (id-based, class-based, attribute-based) while marking the best unique selector
- Explain WHY each selector is relevant based on cluster neighbors, labels, and screenshot context
- Map selectors to automation steps
- Prefer selectors that are unique and stable; do not recommend selectors that may match multiple elements

FULL DOM DATA:
{markdownify(dom)}

DOM CLUSTERS:
{markdownify(clusters)}

PAGE TEXT:
{page_text}

PAGE URL:
{url}

SCREENSHOT (truncated):
{screenshot_b64}

OUTPUT FORMAT:
- Return valid markdown output only, with no extra text.
- Use markdown headings and bullet lists for structure.
- If you need to include code snippets, use fenced markdown code blocks.

Example structure:
- filtered_dom:
  - source: llm_dom_combined
  - url: {url}
  - counts:
    - inputs: 0
    - dropdowns: 0
    - buttons: 0
    - suggestions: 0
    - tables: 0
  - elements:
    - inputs:
      - selector: ""
        id: ""
        name: ""
        type: ""
        placeholder: ""
        class: ""
        label: ""
        container_selector: ""
        visible: true
    - dropdowns: []
    - buttons: []
    - suggestions:
      - selector: ""
        id: ""
        role: listbox|list|menu|none
        visible: false
        description: "AJAX suggestion container for search input"
    - tables: []
  - clusters: []
  - logical_clusters: []
  - form_based_dom:
    - primary_form_cluster: {{}}
    - result_cluster: {{}}
    - elements:
      - inputs: []
      - dropdowns: []
      - buttons: []
      - suggestions: []
      - tables: []
- dom_understanding:
  - goal: Describe page purpose from URL and content
  - roles:
    - search_input:
      - selectors:
        - #id_or_selector
        - input.class_name
      - reason: Input field for company name or search query
      - suggestion_container: Related suggestion box selector if applicable
    - filter_controls:
      - selectors:
        - #select_id
      - reason: Dropdown for filtering by criteria
    - suggestion_boxes:
      - selectors:
        - #suggestions
        - div.autocomplete
      - reason: AJAX suggestion container that appears after typing in search input
      - linked_to_input: search_input
    - submit_action:
      - selectors:
        - #search_btn
        - button.search
      - reason: Button to submit search or apply filters
    - results_table:
      - selectors:
        - table#results
        - table.data-table
      - reason: Container for displaying search/filtered results
    - data_links:
      - selectors:
        - a.result-link
        - a[href*=xbrl]
      - reason: Links to XBRL or detailed data
  - recommended_flow:
    - Select filter dropdowns if required
    - Enter search/company identifier in search input
    - Wait for and interact with suggestion box if available
    - Select suggestion from dropdown or autocomplete
    - Click submit button
    - Wait for results table
    - Extract or click data links
  - notes: Additional context about page structure and challenges
- agent_thoughts: ""

"""


def analyze_dom_combined(dom_data, cache_path="cache/dom_analysis_combined.md"):
    prompt = build_dom_combined_prompt(dom_data)
    result = evaluate_with_azure_llm(
        prompt=prompt,
        cache_path=cache_path
    )
    return result


