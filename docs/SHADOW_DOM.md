# D2L Shadow DOM — Clicking Buttons

All buttons on the quiz edit page live inside deeply nested shadow DOMs
(`d2l-activity-quiz-editor`). Standard Playwright clicks fail silently.

## The only approach that works

```python
coords = await page.evaluate("""
    () => {
        function find(root) {
            for (const el of root.querySelectorAll('SELECTOR')) {
                const r = el.getBoundingClientRect();
                if (r.width > 0) return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
            }
            for (const el of root.querySelectorAll('*')) {
                if (el.shadowRoot) { const c = find(el.shadowRoot); if (c) return c; }
            }
            return null;
        }
        return find(document);
    }
""")
await page.mouse.click(coords["x"], coords["y"])
```

Use `page.evaluate()` with recursive shadow DOM walk to get real viewport
coordinates, then `page.mouse.click()`. Never use `locator.click()`,
`force=True`, `bounding_box()`, or `el.click()` via evaluate — all fail.

For confirming a dialog closed, use the same recursive walk in
`page.wait_for_function()` checking `getBoundingClientRect().width === 0`.

## Timer OK button special case

After clicking the radio, use `await page.keyboard.press("Enter")` —
d2l-button visibility checks fail all other approaches.
